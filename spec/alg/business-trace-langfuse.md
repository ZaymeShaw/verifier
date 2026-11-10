# 业务 Trace：Langfuse 关联方案

> 状态：2026-11-02 用户确认。
> 上游：`demand/business_trace_langfuse.md` §2 第 5 条、§4；`demand/information_sources.md` 要求 2、8、12（2026-11-02 修订，记录 `demand/draft-20261102/README.md`）。
> 下游：`spec/implementation/business-trace-langfuse.md`（采集、读取、快照已有实现；本篇只改"怎么关联到这一轮"）。

## 1. 两种关联方式

关联方式写在 Langfuse 信息源的登记里，所有用这个信息源的场景都按同一种方式关联。

| | W3C（默认） | 指定标识（可选） |
|---|---|---|
| 登记里的 `match_field` | `id` | `metadata.<键>` |
| trace 标识谁定 | 评测方定 | 评测方定（`{request_id}` 等），业务记进 trace 的 metadata |
| 怎么交给业务 | 请求头 `traceparent` | 场景里写明放在请求的哪里（mock_body） |
| 评测方怎么取回 | 读本次请求记录里记下的 `traceparent` | 按场景 bindings 从请求或响应里取 |
| 怎么查 | `GET /api/public/traces/{trace-id}` | 按 metadata 过滤，必须唯一匹配 |
| 场景要配 bindings 吗 | 不配，配了拒绝保存 | 必配 |
| 发不发 `traceparent` | 发 | 不发 |
| 业务要做什么 | 支持 W3C Trace Context（§4） | 把评测方给的标识写进 trace 的 metadata |

不再支持"`id` 模式下从响应里取业务自己的 trace id"（2026-11-02 用户定）：这要求每个业务专门在返回里加字段，和"业务支持标准就能接入"相反；而且 `id` 会有两种意思。从响应里取标识的能力留在指定标识方式里（例：业务把评测方的标识原样回显在响应里）。

两种方式都满足 `information_sources.md` 要求 2：要么只对上一条，要么算取不到，不按时间、会话、正文猜。

## 2. W3C 方式

### 2.1 生成

每次投递（每发一次 HTTP 请求，多轮的每一轮都算一次）生成一个新值：

```
traceparent: 00-<trace-id>-<parent-id>-01
```

- `trace-id`：32 位小写十六进制，随机，不能全为 0。
- `parent-id`：16 位小写十六进制，随机，不能全为 0。只是 W3C 格式要求带的一段，不记、不用；关联只靠 `trace-id`（2026-11-03 用户定）。
- 版本固定 `00`，采样位固定 `01`（要记录）。发 `00` 的话，按标准实现的业务不会上报（实验 C 组）。
- 不发 `tracestate`、`baggage`。

### 2.2 记录与取回

生成的值合并进本次发出的请求头，同时记进本次请求记录（和 case 自己的请求头分开记）。采集时**只**从这条记录里读 `traceparent`，解出 `trace-id` 去查，不从场景配置推，也不认 case 请求头里的同名头，这样查的就是发出去的那个。多轮沿用同一份请求时，上一轮记下的值被下一轮覆盖，不会当成手写的头。

场景的 service 请求头或 case 里自己写了 `traceparent` 时，W3C 方式下拒绝保存或拒绝执行：请求头里只能有一个 `traceparent`，不能让两处来源打架。

### 2.3 查找

- 按 `trace-id` 读 trace 详情。查不到（404）算异步入库还没到，按现有轮询规则等；等到超时仍查不到，记"没采到"（`information_sources.md` 要求 1），不改用别的方式找。
- trace id 本身唯一，不存在多条匹配。详情返回的 `id` 不等于发出的 `trace-id` 时，算关联失败。
- 步骤（observation）取 trace 详情自带的完整对象，不再调 `/observations` 列表与单条详情接口（2026-11-06，见 implementation 文档）；稳定判定、同 session 历史、快照沿用现有实现，不变。

### 2.4 读取：只看 trace 本身认根（2026-11-03 修订）

业务沿用 `traceparent` 后，根步骤的上一级在 trace 外（是调用方），Langfuse 里没有这一级的记录。认根只看 trace 本身，不看是谁发起的，现场与按 trace 复评同一认法（`langfuse.root_id`）：

- 上一级为空的步骤恰好一个时，它就是根；
- 一个都没有、而上一级不在本 trace 里的步骤恰好一个时，它就是根，上一级是 trace 外的调用方，不算"缺失父节点"；
- 以上都认不出（顶层挂空的不止一个，或上一级在 trace 外的步骤不止一个）时，在这些"顶层候选"（上一级为空，或上一级不在本 trace 里）里再收窄，只用 trace 自带的信息：
  1. 步骤名等于 trace 名的恰好一个，它就是根；同名有多个，只在这几个同名的里面按开始时间，最早且唯一的是根；
  2. 没有同名的，在全体候选里按开始时间，最早且唯一的是根；
  3. 仍然认不出（开始时间并列或缺失、成环），不猜，没有根；按复评时报"找不到唯一的根步骤"，现场采集标层级不全。
- 认出根后，其余上一级不在本 trace 里的步骤照旧列入缺失父节点，层级标为不全。缺的那一层不补、不猜。

收窄的原因（2026-11-09 公司库实测）：业务上报漏了一层。一条 trace 的 4 个步骤里，入口步骤 `gateway-koudai-e-chat` 的上一级是占位值 `0000000000000001`，意图理解、保单查询两个步骤的上一级是同一个没有上报的步骤 `a5ba…`，上一级在 trace 外的步骤有 3 个，原规则认不出根，按 trace 复评报"找不到唯一的根步骤"；现场采集虽不报错，意图理解、规划路由、知识数据三个环节没有输出端、交付环节缺失。入口步骤名与 trace 名相同、开始最早，按上述规则认出后环节补全（输出端补上、交付环节出现），缺失的那一层仍如实标为层级不全。原规则认得出的 trace 不受影响：收窄只在原规则返回认不出时才启用（185 条存档 trace 前后认出的根完全一致）。

修订原因：原规则是"上一级等于本次发出的 parent-id 才当作根"，要用到 trace 以外的信息，按 trace 复评时没有这个信息，同一条 trace 就被标成层级不全，意图理解环节缺输出端、交付环节缺失，4/11 条判成不确定（2026-11-03 8036 实跑）。

## 3. 指定标识方式

和现在一样：场景 bindings 指明标识从请求（`/body/...`）或响应（解析后的 JSON；SSE 时是最后一帧）的哪里取，按 `metadata.<键>` 过滤，必须唯一匹配。这种方式下不发 `traceparent`。

## 4. 业务"支持 W3C"指什么

两件都要做到：

1. **入口沿用请求头**：HTTP 入口按 W3C 读 `traceparent`，把它当作本轮的上一级。用 OTel 的框架自动插桩（FastAPI、Flask、Spring 等）一般默认就会这样做。
2. **上报 Langfuse 用同一个上下文**：本轮的 span 用 OTel 上报 Langfuse（OTLP，或者建在 OTel 上的 Langfuse SDK），并且挂在第 1 步的上下文下面。

只用了 Langfuse 的装饰器、入口没接 OTel 的业务，不算支持，要用指定标识方式。业务自己再按比例抽样的，本轮可能没有记录，按"没采到"处理。

Insurance 现在不沿用 `traceparent`（实验 E 组），它的评测分支要换成标准做法。具体怎么换写在实施文档里，原则是：

- 入口沿用 `traceparent`，替换掉写 `request_trace_id` 的那个提交（`e433d80d`）；
- 那个提交里给 Agno 根 span 补身份的部分保留；
- 网关用的两个提交这次不动；
- 仍按 rebase 方式管理。

## 5. 范围

| 信息源 | 本次 |
|---|---|
| Langfuse | 按本篇改 |
| Agno | 不动，不发 `traceparent`。Agno 3.0.6 只从没有上一级的 span 上读 `run_id`、`session_id` 来建 trace 索引（`agno/tracing/schemas.py`）。业务入口沿用外部上下文以后，Agno 可能就找不到根了（读源码得出，未实跑） |
| 模型中转（llmtracing） | 不动，仍用 `X-Eval-*` 头。中转代码已经支持从 `traceparent` 取 id，以后统一时再改 |

## 6. 依据：2026-11-02 实验

实验脚本在 `scratchpad/w3c_exp/`。模拟业务只用了 opentelemetry-sdk 1.44：入口用 TraceContext 传播器，采样器用默认的 ParentBased(AlwaysOn)，通过 OTLP 上报本机 Langfuse 3.184.1。

| 组 | 发了什么 | 结果 |
|---|---|---|
| A | `traceparent`，采样位 01 | Langfuse 里的 trace id 等于发出的 `trace-id`，按 id 直接查到，2 个步骤都在；根步骤的上一级是发出的 `parent-id` |
| B | 不发 | 业务自己生成了 trace id（对照组） |
| C | `traceparent`，采样位 00 | 业务沿用了 id，但没有上报，查不到 |
| D | 用现有 provider、`match_field: id` 采集 A | succeeded，1 条 trace、2 个步骤；层级标为不全（缺的就是发出的 `parent-id`） |
| E | 给 Insurance 18066 发 `traceparent` | 按发出的 id 查不到；按 metadata 找到的 trace id 是业务自己生成的 |

## 7. 还没验的

- 业务按 Langfuse 官方 SDK v3 加 FastAPI 自动插桩接入时，能不能自然沿用 `traceparent`。要装包才能测，需用户同意。
- Insurance 换成标准做法以后，在 8036 上实跑单轮和多轮。
