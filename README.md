# verifier

通用评测与验证工具，用于把项目配置、实时请求、judge、归因、聚类、check 和前端视图串成一套可验证流程。
本项目的核心目标是旨在通过构建一些模拟case案例，对业务系统进行模拟交互、输出评估、问题归因，从而看到业务系统当前有哪些问题（包括业务系统功能、算法能力，特别是算法能力方面）

## 目录

- `impl/`：核心实现、项目适配、协议和前端页面。
- `impl/projects/<project>/project.yaml`：各项目唯一正式运行配置；同目录保存 adapter 和角色实现。
- `impl/frontend/`：本地分析界面。
- `.claude/skills/`：Claude Code skill 定义。
- `projects/<project>/project.yaml`：evals / harness AI 的唯一知识路由；`data/`、`search-test-case/` 保存样例和历史证据。

## 环境要求

- Python 3.11+（推荐通过 conda agno 环境提供，见 `impl/config.yaml` 的 `python.executable`）
- 可访问被测业务服务
- 复制根目录 `.env.example` 为本机 `.env`，填写已登记的本机值：

```bash
cp .env.example .env
# 编辑 .env：
# DEEPSEEK_API_KEY=你的本机密钥
# PYTHON_EXECUTABLE=/path/to/agno/python
```

公共默认值登记在 `impl/config.yaml`，项目值登记在 `impl/projects/<project>/project.yaml`，知识路由变量登记在 `projects/<project>/project.yaml`。进程环境优先于根 `.env`；未登记变量不能影响 verifier。模型秘密只使用规范变量 `DEEPSEEK_API_KEY`，旧别名不再接受。

### Python 解释器选择

verifier 依赖 agno，**必须用 `impl/config.yaml` 中 `python.executable` 指定的解释器**（通常是 conda 的 agno 环境）。直接 `python -m ...` 可能误用系统默认 python（缺 agno 或版本不对）。

为此提供统一入口 `run.sh`，自动从 `config.yaml` 读取正确的解释器，无需手动 `conda activate`：

```bash
bash run.sh help              # 查看所有子命令
bash run.sh server            # 启动 verifier 服务（端口 8020）
bash run.sh uat               # 启动 UAT 服务（端口 8021）
bash run.sh cli projects      # 跑 impl.cli
bash run.sh check1            # 跑 checklist check1
bash run.sh api-check         # 跑 api-check（自动启动/复用 UAT 服务）
bash run.sh config-check      # 校验三层配置、模板、.env、路径和消费者旁路
bash run.sh python <args>     # 用正确解释器跑任意 python 命令
```

环境变量 `PYTHON_EXECUTABLE` 可覆盖 config.yaml 的解释器；该覆盖仍由统一 resolver 解析。修改 YAML、`.env` 或进程环境后需要重启 verifier。

## 启动前端分析服务

在项目根目录执行：

```bash
bash run.sh server
```

默认 host/port 从 `impl/config.yaml` 读取。临时覆盖端口：

```bash
bash run.sh server --port 8023
VERIFIER_PORT=8022 bash run.sh server
```

启动后访问：

- `http://127.0.0.1:8020/frontend/index.html`
- `http://127.0.0.1:8020/frontend/live.html`
- `http://127.0.0.1:8020/frontend/summary.html`
- `http://127.0.0.1:8020/frontend/materials.html`（资料管理：槽位填充、自由资料、capability 预设）

以上地址对应 `impl/config.yaml` 中默认的 `server.host` / `server.port`。

健康检查：

```bash
curl http://127.0.0.1:8020/health
```

## 接入你自己的 API 做评测（llm_probe）

远程评测（API 在你本机、verifier 在 `154.9.252.35`）按三步走即可：建隧道、资料页配 API、Live/总结页评测。逐步说明见 [`docs/external-eval-deployment.md`](docs/external-eval-deployment.md) 第一章。下面是同一套流程的摘要，以及本机直连 verifier 时的差异。

这是最常见的场景：你有一个带 LLM 的 HTTP 接口，想接入 verifier 评测它"答得对不对"。
`llm_probe` 项目就是为此准备的——它不关心你接口的业务，只按你给的**能力描述**（capability）
和可选的**输出结构**（show_schema）来 judge。

### 整体图景：谁在哪

```
你的机器（本机）                     远程评测机（154.9.252.35）
┌────────────────────┐   ssh 隧道    ┌────────────────────┐
│ 你的 API :8000     │◄───── -R ────│ verifier :8022     │
│                    │              │  （judge/归因/页面） │
│ 浏览器 :18080      │───── -L ────►│                    │
└────────────────────┘              └────────────────────┘
```

verifier 跑在远程评测机上，它要**主动调你的 API** 拿真实输出。但你的 API 在本机、
没有公网地址，所以用一条 ssh 反向隧道把本机端口"搬"到评测机上。
`-L` 则把评测机的页面搬回你本机浏览器。

### 第 1 步：建隧道（人类做，一条命令）

```bash
ssh -N -o ServerAliveInterval=30 \
    -R 15001:127.0.0.1:8000 \
    -L 18080:127.0.0.1:8022 \
    eval-tunnel@154.9.252.35
```

参数怎么填：

| 参数 | 含义 | 怎么填 |
|---|---|---|
| `-R 15001:127.0.0.1:8000` | 把**你本机** 8000 端口映射到评测机 15001 | 右边 `127.0.0.1:8000` 改成你 API 的本机地址端口；左边 `15001` 是评测机上的端口，多人共用时每人固定一个（15001/15002/15003） |
| `-L 18080:127.0.0.1:8022` | 把评测机的 verifier 页面映射到你本机 18080 | 右边固定 `8022`（评测机 verifier 端口）；左边随便选个本机空闲端口 |
| `-N` | 只建隧道不开 shell | 固定 |
| `eval-tunnel@...` | 隧道专用账号（密钥登录、不可开 shell） | 固定；把公钥加进该账号 `authorized_keys` |

多个 API 就加多条 `-R`（15002、15003…）。评测期间保持终端开着，断了重跑即可。
内置业务项目的对应关系：client_search 8000→15001、policy_search 8050→15002、营销意图 9006→15003。

**隧道和 API 的联系**：verifier 在评测机上发请求到 `http://127.0.0.1:15001/...`，
经隧道落到你本机 `8000`。所以 capability 预设里的 service URL 一律写
`http://127.0.0.1:1500X/...`（评测机视角），不是你本机的真实端口。

建好后浏览器访问 `http://localhost:18080` 即 verifier 前端。

### 第 2 步：建 capability 预设（人类做，在资料页）

打开「资料管理」页 → 项目选 `llm_probe` → 「capability 预设」→ 新建。填：

1. **预设名**：小写标识，如 `my-api`，case 里用 `capability_ref` 引用它；
2. **能力描述**：judge 拿它当轴1评判依据。写成**系统定位**，回答三问（几行即可，但要准确）：
   - ① 用户拿它**办什么事**——用户视角的终局一句话（如「从客户库里检回正好符合描述的那群客户」），
     **不要写实现视角**（「输出正确的查询结构」这种写法会让 judge 只看输出形状）；
   - ② 交付物是什么、**被谁怎么消费执行**——judge 要据此把输出放到消费方语义下推演
     （如「条件是给 ES 执行的查询谓词，同从表多条件落同一记录」），不是做文本比对；
   - ③ **什么算办成/没办成**——等价表达算办成；互斥、放大、缩小、编造、丢条件算没办成。
   可以引用你上传的资料：`{material://llm_probe/<资料id>}`（见第 4 步）；
3. **能力边界**（选填）：这个接口**能做什么、不能做什么**，写成陈述句清单（体裁示例：
   「支持按客户姓名等值检索完整姓名」「仅对单姓输入做前缀匹配」「不支持按家庭结构筛选」）。
   填写后启用轴2承载性判定——当调用未达预期时，判断是「接口确实做不到」还是「本该做到但没做对」。
   同样可写 `{material://…}` 引用；引用的资料超出内联预算时自动转为检索式消费（轴2判定器
   用工具按需查资料正文，引用会带行号回指）。不填则轴2对每条未达成期望归位为「说不清（缺能力边界资料）」。
   注意体裁：边界写「能不能」，不要写「怎么解析」——解析规则会把轴2带偏；
4. **探测端点 service**（可选）：`url` 填 `http://127.0.0.1:1500X/你的路径`、method、超时。
   填了之后 case 可以不写 url，只写 `capability_ref`。

注意：预设里的 1500X 端口是**远程评测机**视角（经隧道）。本地用 CLI 直连跑时，
不写 `capability_ref`、直接写本机 `url`（如 `http://127.0.0.1:8000/...`）即可。

### 第 3 步：跑一个 case（人类做）

CLI 方式（本机直连 verifier）：

```bash
bash run.sh cli live-run --project llm_probe --input '{
  "capability_ref": "my-api",
  "url": "http://127.0.0.1:8000/你的路径",
  "body": {"query": "你的测试问题"}
}'
```

`capability_ref` 提供能力口径文本；`url` 覆盖本次请求的端点（本地直连写本机端口，
经远程页面跑时写 1500X）。不写 `url` 时用预设里的 service url。

或显式 url + 内联口径（不建预设时直接写 capability）：

```bash
bash run.sh cli live-run --project llm_probe --input '{
  "url": "http://127.0.0.1:8000/你的路径",
  "method": "POST",
  "capability": "这个接口应该……（能力口径，judge 据此评判）",
  "body": {"query": "你的测试问题"}
}'
```

case 信封字段：`body`（JSON 对象，必填）；`url`/`method`（POST/PUT/PATCH）/`headers`；
`capability_ref` 或 `capability` 二选一必填（预设或内联口径）；`show_schema`（可选，
描述期望输出结构，judge 据此校验）。`url` 和 `capability_ref` 也二选一必填。默认只允许非流式响应；
接口是伪流式（SSE 但最后一帧是全量内容）时，在 capability 预设的响应模式里选「SSE 取最后一帧」
（或信封加 `"response_mode": "sse_last_frame"`），verifier 取最后一个 data 帧评。帧是增量、要逐帧累加的真流式不支持。

页面方式：经隧道打开 `http://localhost:18080`，在 live 页提交同样形状的信封，
看 judge 结论和归因。

### 第 4 步：上传资料让评测更准（人类做，在资料页）

judge 默认只靠能力描述判断（轴1）。你的接口有领域知识（字段口径、业务规则、
接口说明）时，上传成**自由资料**，再在能力描述或能力边界里引用：

1. 资料页 → 「自由资料」→ 新建资料，粘贴正文或选择本地文件（.md/.txt/.yaml/.json）；
2. 保存后编辑器上方会给出可复制的标识符（`{material://llm_probe/<资料id>}`，含 {} 定界）；
3. 在 capability 预设里，能力描述/能力边界下方有「插入资料引用…」下拉：选中资料点插入，
   记号会插到光标处；随手写的记号若资料不存在或不是合法 `{material://…}` 会在保存前提示；
4. 也可以直接写：`字段口径见 {material://llm_probe/my-api-spec}`（轴1）、
   `能力范围见 {material://llm_probe/my-api-spec}`（轴2）。

仓库里已带一条样例资料 `client-search-match-rule`，可直接引用
`{material://llm_probe/client-search-match-rule}` 试效果。

资料内容哈希封口，手改会标记「内容已非原样」。引用展开预算 50k 字符：能力描述（轴1）超预算
直接报错，请精简或拆分；能力边界（轴2）超预算不报错，自动转检索式消费——正文不进上下文，
轴2判定器用 `material_search`/`material_read` 工具按关键词/行号查，结论引用带行号定位可回查。
所以几十万字符的字段定义表 YAML 可以整份上传后直接在能力边界里引用。

### 人类 vs AI 分工（全生命周期）

| 阶段 | 人类做 | AI 做 |
|---|---|---|
| 首次接入 | 提供 API、评测机账号；授权部署 | 部署、加固、首次调查/物化 |
| 日常评测 | 起本地 API；跑隧道命令；建预设/传资料；跑 case 看结果 | 无 |
| 业务代码更新 | 说一句"业务代码更新了"；确认增量范围；确认逻辑型漂移 | baseline→drift→increment→materialize→sync→deploy 全串 |
| 优化 judge / 重调查 | 发起意图；审 draft 结果；授权晋升 | Investigate/Solidify/Loop、晋升执行 |

人类真正要记的只有：一条隧道命令、建预设/传资料、对 AI 说"业务代码更新了"、两次确认。

## client_search 本地验证流程

1. 启动业务服务，确保业务接口在 `8000` 端口可访问。
2. 启动 verifier 前端分析服务，默认端口来自 `impl/config.yaml` 的 `server.port`。
3. 如果项目依赖 ES，先执行业务项目的 reindex 接口。
4. 在前端或 CLI 中执行实时请求、judge、归因和 check，确认链路可用。

## 新增项目

在 `impl/projects/<project_id>/` 下补齐：

- `project.yaml`
- `adapter.py`
- `application.md`
- `evaluation.md`
- `judge.md`
- `attribution.md`
- `checklist.md`
- `mock.md`

协议说明见 `impl/protocols/`。

## 附录：调查增量更新命令（AI 执行参考，人类不用记）

业务源码更新后 production 调查包哈希过期时，AI 按此顺序执行；人类只需说
"业务代码更新了"并确认增量范围。协议细则见 `spec/alg/investigate.md`「增量门禁」。

```bash
# Gate 1 baseline：production→draft 复制（纯机器）
bash run.sh cli investigation-lifecycle --project client_search --role judge --gate baseline
# Gate 2 drift：算增量范围（只读；逻辑型漂移只报不钉，待人复核）
bash run.sh cli investigation-lifecycle --project client_search --role judge --gate drift
# Gate 2 increment：按人确认的范围重钉
bash run.sh cli investigation-lifecycle --project client_search --role judge --gate increment \
  --refs business-field-definitions,business-field-enums,business-enhanced-rules,business-time-knowledge
# 物化 + 同步到评测机
bash run.sh cli materialize --project client_search --role judge --apply \
  --push root@154.9.252.35:/opt/verifier
# 部署代码（project.yaml / draft 文件有改动时）
scripts/deploy_verifier.sh root@154.9.252.35 /opt/verifier --dry-run
scripts/deploy_verifier.sh root@154.9.252.35 /opt/verifier
# 晋升（draft 验证通过后，可选）
bash run.sh cli draft-promote --project client_search --role judge --apply
```

开 draft 模式（首次）：`project.yaml` 里 `judge_investigation.candidate_path` 指向
`project://draft/investigation/judge`，并加 `roles.judge.draft.enabled: true`。
