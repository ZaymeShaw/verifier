# 新场景接入指南（llm_probe_loop）

来了一个新的被测接口，内容和已有场景差不多，但请求体、地址、返回方式不一样。本文按资料管理页从上到下的顺序，讲每一处怎么填。

例子用的是 2026-11-02 在 8036 上实测跑通的 `verify-insurance-langfuse-sse`：从 `verify-insurance-langfuse` 复制，改成 SSE 伪流式接口。

---

## 0. 先判断能不能只靠配置

下面几条都满足，就不用改代码，也不用新做页面，只填配置：

- [ ] 请求方法是 POST、PUT 或 PATCH，请求体是 JSON，地址是 http(s)。
- [ ] 返回是普通 JSON；或者是 SSE，并且**最后一个数据帧就是完整答复**（伪流式）。
- [ ] 业务 trace 能对上这一轮。默认方式：业务支持 **W3C Trace Context**（入口沿用请求头里的 `traceparent`，并用同一个上下文上报 Langfuse），这时业务不用为评测做任何改动。不支持的，退一步：业务把我们给的一个标识（如 `{request_id}`）记进 trace 的 metadata。
- [ ] 业务的 trace 上报到了一个 Langfuse（或 Agno）实例，我们有它的地址和 key。

有一条不满足，先看[第 7 节](#7-接不上时怎么办)。

---

## 1. 登记 trace 源（信息源登记）

位置：资料管理页左侧「信息源（各业务系统）」→「新建信息源」。

trace 源登记的是**去哪个 Langfuse、按什么方式找 trace**，和场景分开，多个场景可以共用一个。

按什么方式找由 `match_field` 决定，有两种：

| `match_field` | 方式 | 我们发什么 | 场景里的绑定 | 业务要做什么 |
|---|---|---|---|---|
| `id`（**默认**） | W3C | 每次请求自动在请求头里发一个新的 `traceparent`，按它的 trace id 直接查 | 写 `{}`，不用配 | 支持 W3C Trace Context |
| `metadata.<键>`（可选） | 指定标识 | 不发 `traceparent` | 必须配，写明标识从请求或响应的哪里取 | 把我们给的标识记进 trace 的 `metadata.<键>` |

### 能不能直接复用 `langfuse-local`

| 新系统的情况 | 怎么做 |
|---|---|
| 同一个 Langfuse 实例、同一个项目，业务支持 W3C | 直接复用 `langfuse-local`（`match_field: id`），跳过这一步 |
| 同一个实例，但业务不支持 W3C | 新登记一个，`match_field` 写 `metadata.<业务记标识用的键>` |
| 另一个 Langfuse 实例或项目 | 新登记一个，改 `base_url` 和两个 key 的变量名 |

### 各字段

| 字段 | 填什么 | 例子 / 规则 |
|---|---|---|
| 信息源名 | 小写字母或数字开头，可含 `_` `-` | `langfuse-bizb` |
| 类型 | 选 `langfuse`，下面会自动带出模板 | |
| base_url | Langfuse 地址，不带 `/api` | `http://127.0.0.1:3300` |
| public_key / secret_key | **只能写 `${变量名}`**，写明文会被拒绝保存 | `${LANGFUSE_PUBLIC_KEY}` |
| match_field | 关联方式，见上表。只能是 `id`（W3C，默认）或 `metadata.<键名>` | `id` |
| poll / timeout 等 | 照模板默认值即可。业务上报慢、trace 常常采不全时，再调大 `poll_timeout_seconds` | 默认 60 秒 |

现有 `langfuse-local` 的配置：

```json
{
  "base_url": "http://127.0.0.1:3300",
  "public_key": "${LANGFUSE_PUBLIC_KEY}",
  "secret_key": "${LANGFUSE_SECRET_KEY}",
  "match_field": "id",
  "timeout_seconds": 15,
  "poll_timeout_seconds": 60,
  "poll_interval_seconds": 1,
  "quiet_seconds": 3,
  "max_pages": 20,
  "page_size": 50,
  "content_char_limit": 20000
}
```

> **key 的值放哪**
>
> 程序先读进程环境变量，再读 `.env`。但 `.env` 只接受在 `impl/config.yaml` 里登记过的变量名，写了没登记的，配置加载会直接失败。所以新的变量名有两种办法：
>
> 1. 像现在一样，在启动 8036 的脚本里 `export`。现有的 `LANGFUSE_PUBLIC_KEY` 就是这么来的。
> 2. 先在 `impl/config.yaml` 里登记这个变量名，再写进 `.env`。
>
> 填完点「测试连接」，能看到连通和项目数就对了。

---

## 2. 新建预设（复制已有场景）

位置：左侧选中 `verify-insurance-langfuse`，把**预设名**改成新名字再保存，就得到一份副本，原预设不受影响。

| 页面字段 | 改不改 | 怎么填 |
|---|---|---|
| 预设名 | **必改** | 新名字，也就是 case 里的 `capability_ref`。例：`verify-insurance-langfuse-sse` |
| 能力描述 | 按需改 | 业务内容一样就照抄。接入方式有变化（比如走流式接口、历史由服务端保存），补一句说明 |
| 能力边界 | 按需改 | 新系统能做和不能做的事跟原来不同，才改 |
| 扩展评估轴 | 少量改 | 见[第 5 节](#5-扩展评估轴) |
| service 地址 | **必改** | 新接口的完整地址。例：`http://127.0.0.1:18067/api/v2/assistant/stream` |
| service 方法 | 按需改 | POST / PUT / PATCH 三选一 |
| 超时秒数 | 按需改 | 要覆盖一次业务答复的最长耗时。保险场景用的是 240 |
| 响应格式 | **流式必改** | 普通 JSON 选「非流式 JSON」；伪流式选「SSE 取最后一帧」 |
| 启动提示 | 选填 | 连不上时附在报错里的提示，比如怎么启动这个服务 |
| 业务 Trace | **必改** | 见[第 4 节](#4-业务-trace-绑定provider-config) |
| mock_body 请求模板 | **必改** | 见[第 3 节](#3-mock_body-请求模板) |

### SSE「取最后一帧」具体怎么取

- 按空行切帧，同一帧里的多行 `data:` 拼起来。
- `event:` 行、注释行、`data: [DONE]` 都跳过。
- 剩下的最后一个数据帧，是 JSON 就按 JSON 解析，不是就当纯文本。
- 评测用的「交付」就是这一帧，前面的进度帧、增量帧都不看。

---

## 3. mock_body 请求模板

照新接口的请求体原样写一份 JSON，把会变的地方换成占位符。结构随新接口，没有固定格式。

| 占位符 | 放哪 | 每次换成什么 |
|---|---|---|
| `{query}` | 用户问题所在的字段。**必须有**，没有会保存失败 | 这一轮用户说的话 |
| `{session_id}` | 会话号字段 | 同一个 case 的各轮用同一个新会话号 |
| `{request_id}` | 请求标识字段（按 metadata 关联时，业务会记进 trace 的那个；接口本身要求有请求号时也可用） | 每发一次请求都换一个新的，形如 `llm-probe-req-…` |

按 W3C 关联时，trace 标识在请求头 `traceparent` 里，由我们自动生成，**mock_body 里不用、也不能自己写**（service 请求头和 case 里写了会被拒绝）。

每个占位符要**单独占满一个字段的值**，比如 `"id": "{request_id}"`。不要拼在别的文字里，像 `"id": "abc-{request_id}"` 这样是认不出来的。

### 多轮对话：历史由谁带

程序看 `{query}` 放在哪，自动决定历史由谁带：

| `{query}` 的位置 | 程序怎么发 | 适合的接口 |
|---|---|---|
| 消息数组里某一条的 `content`，如 `messages[0].content` | 每轮把前面各轮的问答都放进这个数组，再加上本轮的问题 | OpenAI 风格、服务端不存历史的接口（原场景 `/v1/chat`） |
| 其他任何位置，如 `request.input.text` | 只发本轮这一句，靠 `{session_id}` 让服务端自己接上历史 | 服务端按会话号存历史的接口（实测的新接口） |

> 第一种情况有个限制：程序把上一轮的答复放进历史时，写死了取返回里的 `answer` 字段（`impl/projects/llm_probe_loop/mock.py` 的 `_answer_text`）。新接口的答复字段要是不叫 `answer`，历史里放的就是整个返回 JSON。能跑，但历史很脏。见第 7 节。

### 例子

原场景 `/v1/chat`（调用方带历史）：

```json
{"messages": [{"role": "user", "content": "{query}"}],
 "session_id": "{session_id}", "stream": false,
 "user_id": "1050900009", "empno": "1050900009", "agentno": "1050900009",
 "trace_id": "{request_id}"}
```

新场景 `/api/v2/assistant/stream`（服务端存历史）：

```json
{"conversation": {"id": "{session_id}"},
 "request": {"id": "{request_id}", "input": {"text": "{query}"}},
 "operator": {"emp_no": "1050900009", "agent_no": "1050900009"}}
```

手写 case 时，`live_request.body` 也要用同一个结构：`{query}` 的位置换成真实问题，`capability_ref` 填新预设名。例：

```json
{"id": "llm-probe-verify-insurance-langfuse-sse-main-G01-short-answer",
 "project_id": "llm_probe_loop",
 "scenario": "verify-insurance-langfuse-sse",
 "live_request": {
   "capability_ref": "verify-insurance-langfuse-sse",
   "method": "POST",
   "body": {"conversation": {"id": "{session_id}"},
            "request": {"id": "{request_id}", "input": {"text": "保单P260922000009116的累计已交保费是多少？只回答金额。"}},
            "operator": {"emp_no": "1050900009", "agent_no": "1050900009"}}}}
```

---

## 4. 业务 Trace 绑定（Provider config）

上面的下拉框选第 1 步登记的 trace 源。下面的框只填 `bindings`，写法取决于这个源的 `match_field`。

**按 W3C 关联（`match_field: id`，默认）：写 `{}`。** 选中这种源时页面会自动填 `{}`，并提示"每次请求自动发 traceparent"。写了非空绑定会被拒绝保存。

```json
{}
```

**按指定标识关联（`match_field: metadata.<键>`）：必须写 `business_trace_id`**，告诉程序标识从哪里取。

| source | pointer 从哪算起 | 什么时候用 | 例子 |
|---|---|---|---|
| `request` | 我们发出的请求。根是请求信封，请求体在 `/body` 下 | 标识是我们发过去的 `{request_id}`，业务把它记进了 trace | `/body/trace_id`、`/body/request/id` |
| `response` | 业务的返回；SSE 时就是解析后的最后一帧 | 业务把我们给的标识原样回显在返回里 | `/meta/traceId` |

pointer 用 JSON Pointer 写法：以 `/` 开头，一级一级往下写，数组用下标，比如 `/items/0/id`。

```jsonc
// 从请求里取
{"business_trace_id": {"source": "request", "pointer": "/body/trace_id"}}

// 从最后一帧里取（业务回显的我们给的标识）
{"business_trace_id": {"source": "response", "pointer": "/meta/traceId"}}
```

取到的值要等于业务记在 trace `metadata.<键>` 里的那个。

---

## 5. 扩展评估轴

不用做轴自定义页面，也不用改后端。每个轴框就是「选类型 + 写本场景描述 + 勾启用」，轴的代码所有场景共用。

复制过来的 19 个轴照抄，只改描述里**写到原接口字段名**的几句：

| 轴 | 原描述里要改的 | 新场景改成 |
|---|---|---|
| 需求分析 `expectations` | 交付物为 /v1/chat JSON 中的 answer，以及与回答相关的 gaps、fact_refs、sources、followup_actions。 | 交付物为 SSE 最后一帧 JSON 中的 data.content（答复正文），以及与回答相关的 data.refs。 |
| 能力兑现 `fulfillment` | 接口成功、status=null 或存在 fact_refs 均不能单独证明答案正确 | 接口成功或 data.refs 非空均不能单独证明答案正确 |
| 上下文本应 `context_memory_expected` | 交付给调用方的 trace_id 字段，原值回显调用方请求里传的 trace_id…… | 交付给调用方的 meta.traceId 字段，原值回显调用方请求里传的 request.id……<br>「执行余量」这条说的是被测系统内部的事：背后还是同一个系统就保留；换了系统就删掉，或换成新系统的同类说明 |
| 其余 16 个轴 | 不涉及接口字段 | 照抄 |

判断方法：在轴描述里搜原接口的字段名（`answer`、`trace_id`、`fact_refs`、`gaps`、`status` 等），出现的地方换成新接口的说法。不提字段名、只讲业务的描述不用动。

---

## 6. 检查和试跑

1. **保存预设。** 保存时会校验这几项：
   - 预设名和能力描述；
   - `{query}` 在不在；
   - 方法和响应格式是否合法；
   - bindings 写法；
   - 引用的 trace 源有没有登记。
2. **点「测试 Trace 连接与配置」。** 返回 `ok · provider=langfuse · project_count=1` 就是连上了。这一步只能验连接和配置格式，验不到标识能不能对上 trace。
3. **拿 1～2 条 case 试跑。** 挑一条短的、一条复合问题的。跑完重点看三件事：
   - 交付（`output_text`）是不是你要的那一帧、那个字段；
   - 业务 trace 有没有采到，有没有步骤记录（observations）；
   - 需求分析轴认出的交付物对不对。

---

## 7. 接不上时怎么办

下面这些情况，只改配置接不上。表里的「改哪层」只标出要动的位置；真要改，先出方案，确认了再动。

| 情况 | 现在会怎样 | 改哪层 |
|---|---|---|
| SSE 最后一帧只是结束标记（如 `{"event":"end","usage":…}`），答案在前一帧 | 交付取成了结束标记，判成没给答复 | 响应读取：加「跳过哪类帧」，或「取最后一个带某字段的帧」 |
| 真流式：每帧只有一小段增量，要拼起来才完整 | 只取到最后一小段 | 响应读取：加一种「拼接增量」的响应格式 |
| 调用方带历史，且答复字段不叫 `answer` | 能跑，但历史里放的是整个返回 JSON | 投递：在 service 里加「答复正文在哪个字段」 |
| 业务入口不沿用 `traceparent`（不支持 W3C） | 按 id 查不到，业务 trace 采集失败 | 不改代码：登记一个 `metadata.<键>` 方式的源，业务把我们给的标识记进 trace metadata（只为关联改业务） |
| 业务自己按比例抽样 | 有的轮没有记录，记「没采到」 | 不改。如实记录，不猜 |
| 请求体不是 JSON（表单、multipart），或方法是 GET | 保存时被拒 | 投递层 |
| 业务埋点不标观测类型，全是普通 SPAN | 能读到，但模型调用和工具调用都归成「步骤」，过程轴证据变少，可能判缺证 | 不改。业务给多少证据就用多少 |

---

## 附：实测样例（2026-11-02，8036）

这次的新接口是 scratchpad 里的一个转接服务（端口 18067）。它对内转发真实业务 18066，业务本身没改。（下表是改成 W3C 之前按 metadata 关联跑的；现在转接服务会把 `traceparent` 原样传给 18066，场景绑定为 `{}`。）返回四帧：

```text
event: status
data: {"type":"status","stage":"thinking"}

event: delta
data: {"type":"delta","text":"1089.1元"}

event: final
data: {"type":"final","data":{"content":"1089.1元","refs":["F-CALL-TR-…"]},"meta":{"traceId":"llm-probe-req-…","conversationId":"…"}}

data: [DONE]
```

| case | 新场景 | 原场景（候选区里的结果） | 评测耗时 新 / 原 |
|---|---|---|---|
| A02 余昕雅两张保单 | 做成了，过程轴全 sound | 做成了 | 511 s / 588 s |
| G01 只回答金额 | 没做成 | 没做成 | 480 s / 489 s |

已核对：

- 最后一帧取对了。
- 从 `/meta/traceId` 取到了标识，在 Langfuse 里找到了对应的业务 trace。
- 过程轴引用的就是这条 trace 里的步骤。

G01 没做成，是业务这次降级了。模型已经算出 1089.1，交付时却被换成了「部分内容未能完成整理……」，违反了「只回答金额」。

没测到的：多轮对话；SSE 最后一帧不是全量的两种情况（第 7 节前两行）。

---

依据代码：

- 资料管理页 `impl/frontend/materials.html`
- 预设校验 `impl/core/capability_store.py`
- 占位符 `impl/projects/llm_probe_loop/capability.py`
- 历史拼接 `impl/projects/llm_probe_loop/mock.py`
- SSE 解析 `impl/core/live_transport.py`
- Langfuse 绑定 `impl/projects/llm_probe_loop/business_trace/providers/langfuse.py`
