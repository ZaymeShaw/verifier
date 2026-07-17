# VNext Case Protocol：Check / Business / AI-Hacking 审查报告

审查日期：2026-07-17  
审查范围：本轮 MockCase 硬切、batch request identity、summary 前端、fixture/data 迁移。  
审查方式：只读代码审查 + 已有回归/UAT 证据；本报告不修改实现。

## 结论

本轮修改解决了旧 `input` case 与前端按输入内容猜测关联的主要问题，单条 UAT 可以跑通；但尚不能判定为可推广的标准实现。发现 4 个高优先级问题和 3 个中低优先级问题，其中前 3 个会直接复现“结果跑完但页面没数据 / A 输入合并到 B / 二次运行行为改变”的业务故障。

## Findings

### P1-1：前端按 case id 回填 request_key，重复 id 时仍会串结果

- 证据：`impl/frontend/summary.html` 的 `requestByCase=Object.fromEntries(...)` 以 `request_case_id` 为 key，再按 `item.id` 回填。
- 机制：后端身份真正唯一的是 `job_id + request_index`；case id 并不保证在同一批次唯一。两个同 id case 会共享最后一个 request_key，第一个结果无法归位或被错误覆盖。
- Business：批量关联的业务目标是“提交的第 N 个 case 只接收第 N 个结果”，不是“相同业务 id 视作同一 case”。
- AI-hacking：单例 UAT 和当前 fixtures 的 id 恰好唯一，因此测试能通过，但机制没有满足不可变请求身份标准。
- 建议：前端按 `started.requests[index]` 与 `selected[index]` 原位绑定；case id 仅展示和诊断，禁止作为合并主键。增加重复 id、相同输入、不同输入三组契约测试。

### P1-2：运行结果覆盖 MockCase.output/reference，二次执行会改变被测链路

- 证据：`applyRunToCase()` 把 `run.trace.extracted_output` 写回 `item.output`，并把 judge-generated reference 写回 `item.reference`；`transportCase()` 下次又把二者提交给后端。
- 机制：页面展示的 actual output、持久化 MockCase 的 provided output、reference 三种职责混在一个对象。对 ready 含 output 的 provided-output 项目，第二次运行可能直接使用上次 actual，绕过真实执行。
- Business：用户要求的是 Output 和 Reference 同格式、相邻展示，不是把 actual 写成下次运行输入。
- AI-hacking：通过复用同一个 `output` 字段让展示测试变简单，但产生了参数越界和行为越界。
- 建议：MockCase 永远不可变；UI run state 独立保存为 `resultsByRequestKey`。渲染 Output 读取 run.trace.extracted_output，transport 只读原始 MockCase。judge-generated reference 只能属于 run view，除非用户明确执行“提升为 reference”。

### P1-3：没有 active job 恢复，刷新页面仍会丢失已运行结果

- 证据：启动后只把 request_key 混入 casePool；未持久化 active `job_id`、提交快照、轮询游标，也没有初始化恢复逻辑。
- 机制：刷新/切项目/标签页中断后轮询停止；后端任务继续完成，但前端没有入口重新拉取并合并。
- Business：这正对应历史问题“结果跑了，但数据不出来且没有报错信息”。清缓存只能隐藏旧状态，不能解决恢复机制。
- AI-hacking：通过升级 `PAGE_VERSION` 清掉旧 pending 数据让一次 UAT 看起来干净，但没有修复产生 pending/无结果的源头。
- 建议：独立持久化 `activeBatch={job_id, project_id, requests, submittedCases}`；页面初始化恢复轮询，completed 后按 request_key 合并并清理 active job。增加“提交后立即 reload”的浏览器 UAT。

### P1-4：协议错误被异步 fallback 包装，严格边界没有真正 fail-fast

- 证据：`parse_mock_case()` 位于 `_batch_case()` 的线程任务中且在其 retry try-block 外；future 抛错后由 `_batch_error_run()` 转成 `not_evaluable/error` run。`start_batch()` 不同步校验 cases。
- 机制：缺字段、project_id 不匹配等 transport 错误不会在 `/api/batch_start` 返回 4xx，而是先接受 job，再伪装成一条业务运行失败。
- Business：协议输入无效和业务系统运行失败必须可区分，否则用户只看到“归因失败”，无法修数据。
- AI-hacking：fallback 让批次“有结构化结果且不中断”，但掩盖了业务上应拒绝的协议错误，属于典型 fallback 逃避失败。
- 建议：`start_batch()` 在线程启动前同步解析全部 MockCase，协议错误直接 422；`_batch_error_run()` 只处理通过边界后的执行异常，并从 runtime case 构造 trace.input。

### P2-1：所谓严格 7 字段 parser 实际接受任意额外字段

- 证据：`parse_mock_case()` 只检查 missing，不检查 `set(value) - required`。
- 影响：后端仍默许 selected/status/trace 等 UI 字段穿越 transport 边界；“唯一存储/传输格式”的标准只由前端自觉维持。
- 建议：严格拒绝 unknown fields；若 API 需要 envelope，新增显式 envelope schema，不把 UI 字段塞进 MockCase。

### P2-2：迁移脚本把运行元数据污染到 intent.user_context

- 证据：迁移脚本把除少数字段外的 `source/status/expected_quality` 等全部放进 `user_context`。
- 影响：用户背景语义与测试编排状态混合；多轮 mock agent 可能看到 `fulfilled/pending/data_mock_seed` 等不属于用户的信息，形成参数越界和数据泄漏式过拟合。
- 建议：定义明确迁移映射白名单。业务背景进入 user_context；测试来源、状态、质量标签若 VNext 不再支持，应丢弃或放到 dataset envelope，不能伪装成用户上下文。

### P3-1：迁移无差别重写目录中的 index/provenance 文件

- 证据：脚本对传入目录所有 JSON 做格式化写回，`index.json`、`index_upload_batches.json` 即使无 case 语义变化也产生 diff。
- 影响：制造无意义数据 churn，降低审查可信度和 provenance 可追踪性。
- 建议：只在内容实际变化时写文件；显式排除 provenance/index，或为其定义独立迁移规则。

## 已通过项

- Output 与 Reference 相邻且使用同类 JSON 渲染；Trace 位于最后且较宽。
- RunTrace.input 在真实 client_search UAT 中是实际 live_request，不再是整个 MockCase。
- 后端 event 与 final run 已携带相同 request_key。
- 旧的前端 input 深比较和 volatile-field 忽略逻辑已移除。
- `impl/data/context_store` 未被本轮迁移脚本写入。
- 未发现为特定 family_property_claim 文案增加硬编码业务规则。

## 验证局限

- 当前真实 UAT 只证明单个唯一 id case 可以完成并按 request_key 返回，不能覆盖重复 id、刷新恢复和二次执行污染。
- 129 项回归和现有 schema/fixture 测试没有覆盖上述三类业务场景，因此“测试通过”不能作为完成依据。

## 建议修复顺序

1. 拆分 immutable MockCase 与 run view state，消除 output/reference 回写。
2. request identity 改为按提交 index 原位绑定，并补重复 id 测试。
3. 增加 active job reload recovery。
4. batch_start 同步严格校验，协议错误 fail-fast。
5. 清理迁移映射与无意义 provenance diff。

## 2026-07-17 修复复核

上述问题已按顺序处理：

- P1-1 已修复：前端按提交位置绑定后端 `requests[index]`；实际 UAT 使用两条相同 id、不同输入的 case，分别得到不同 trace/output，未串行。
- P1-2 已修复：MockCase 与 `caseResults` 分离；运行完成后导出两条 case，`output/reference` 仍为原始 `null`，actual 只存在于运行视图。
- P1-3 已修复：持久化 active batch 的 job_id 与 index bindings；实际运行中刷新页面后显示“正在恢复未完成批量任务”，最终自动合并 2/2 结果。
- P1-4 已修复：`batch_start` 在线程创建前严格解析；非法 legacy case 的实际 HTTP 响应为 422，不再生成 fallback run。
- P2-1 已修复：MockCase 顶层未知字段会被拒绝。
- P2-2 已修复：1361 条迁移数据扫描结果 `polluted_count=0`。
- P3-1 已修复：迁移脚本仅在语义变化时写入，并排除 index/provenance；两份 provenance 文件无 diff。

回归：138 passed；专项协议/前端测试 24 passed。UAT 页面未发现 console error。
