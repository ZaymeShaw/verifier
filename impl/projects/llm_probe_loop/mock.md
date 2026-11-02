# Mock

默认使用固化 fixture `impl/data/llm_probe/mock_cases.json`。种子 case 使用 live_request 信封，并带上 `capability_ref`。`scenario` 按被探测能力分桶，与 `capability_ref` 同名，默认场景列表见 project.yaml 的 mock_cases.default_scenarios。

`insurance-agno-e2e` 只面向以七个查询工具全 real 模式启动的 insurance-qa-agent。这里的 `mock_cases.json` 是 llm_probe 对“固化输入 case”的历史命名，不表示被测服务使用 Mock 后端。保险 case 全部保留 `output/reference=null`，每次都现场调用真实服务，不预填业务响应或测评结论。固定 case 默认也不保存 `intent`；Judge 从 `live_request` 中的可见用户输入自行推断。

默认动态请求和不需要个人数据的知识问答使用 `SYNTHETIC-LLM-PROBE` 合成身份。保单正向 case 只有在工号与保单号已获授权时才固化。已授权身份以工号 `1050900009` 及其 **0922 批次造数 SQL** 客户/保单为准（`llm-probe-insurance-real-*` 代表性集，含 smoke/main；旧 Mock Excel 主体 `柏思新 / 吴文景 / 谢嘉清 / 金景和` 及 `P260000000* / C260000203*`、更早的 `EMP000006 / 皮奕辰 / P260000000000079`，以及中途一度采用的 0923 批次 `P260923* / C923*` 均已废止）。各批次客户姓名完全相同、只有 `clientno`/`polno` 前缀带批次号，所以换批时姓名不能当批次凭据；`scripts/insurance_backend.sh` 的就绪探针用**客户号问句**（`C92200000884` → 断言 `何承琪`）+ 断言人名来卡住批次不匹配。负向错工号冒烟仍可用 `EMP000000`。身份字段按 insurance-qa-agent 的映射同时填三处：`user_id` 是认证主体并作为保单解析的 agentCode，`empno` 走保单查询/明细，`agentno` 走客户查询/明细，后两者缺省回退 `user_id`，所以三者填同一工号。原有 P002/P123/P1456 case 现在只用于真实服务下的未命中、澄清、约束保持和错误处理，不再把 demo 金额当作期望事实。

`llm-probe-insurance-real-*` 系列按重点维度命名：`baseline-*` 正向基线（真实明细确实透出被保人/投保人）；`intent-*` 复合子问题、否定纠错；`routing-*` 尾号定位、姓名搜单、姓名→保单→字段两跳；`data-*` 已命中但字段未透出、接口不提供的字段、真实格式的不存在保单、跨工号越权；`model-*` 诱导免查确认、用户格式约束与系统输出契约冲突；`scenario-*` 产品知识与保单+产品混合问句（产品/FAQ/权益/客户解析走内网 192.168.1.x，评测机不在内网时这些是真实的下游不可用样本）。`ctx-*` 是 transcript 级 seed（两轮原话），由 Session 分配一个新会话身份并按序重放，第二轮依赖 Agno 会话历史（跨轮指代、省略主语、同问缓存复用、澄清后补保单号）。

保险 fixture 的 `session_id` 写 `{session_id}` 占位符，每次发送才落成新的业务会话，重跑不会往旧会话追加 run；单轮可并行执行。跨轮记忆只用 seed 组织顺序执行，本批不把多个 messages 拼成伪多轮测试。评测阶段失败的重试只重评已存 trace，不再打后端。运行前必须确认目标 insurance-qa-agent 实例的工具配置确实为 real（`scripts/insurance_backend.sh start` 以全 real 配置起在 18062，Agno SQLite 与 capability_map 的 `sqlite_path` 一致）；llm_probe 不接受服务自行回退到 Mock 的结果作为真实评测证据。

动态生成按 capability 预设（资料管理页维护，存于 `impl/data/llm_probe/capability_map.json`）中目标项目的 `mock_body` 模板产出可被目标服务接受的 `body`（`{query}` 占位符注入意图问句），并带上 `capability_ref`。生成时 `scenario` 选中哪条能力，信封就指向哪条；未点名时默认 `capability_ref` 按 key 排序选取，不依赖键序。意图层不是本项目的输入。
