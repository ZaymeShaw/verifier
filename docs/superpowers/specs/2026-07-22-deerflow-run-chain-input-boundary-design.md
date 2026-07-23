# Live/RunChain MockCase 与业务请求边界设计

## 目标

消除 `/api/live_run` 和 `/api/run_chain` 中同一 `input` 字段同时表示“项目业务请求”和“完整 MockCase”的协议歧义。修复 DeerFlow 顶层 `input/config` 被误拆，同时保留 QA provided-output 的 `output/reference` 以及 MockCase 的可选 intent。

## 问题边界

2026-07-09 的实现将 `run_chain` 字典包装为裸请求，适合 DeerFlow，但不能携带 MockCase 的 `output/reference/intent`。2026-07-17 为保留 VNext MockCase 信息，改成由 `normalize_mock_case` 同时兼容完整 case 和裸请求，从而与 DeerFlow REQUEST_SCHEMA 自身的顶层 `input` 字段发生结构碰撞。

稳定边界不能再根据 `input`/`output`/`intent` 等业务字段猜测输入类型。

## 方案比较

1. **分离 transport 字段，在 service 转换一次（采用）**
   - `input` 始终表示项目 REQUEST_SCHEMA 业务请求。
   - `case` 始终表示标准 MockCase transport 对象。
   - service 要求两者恰好出现一个，并转换为 `SingleTurnCase`。
   - `pipeline.live_run/run_chain` 只接受运行时 `SingleTurnCase`。
   - 前端继续使用 `input`，不需要修改；API check 等 MockCase 调用者改用 `case`。

2. 根据项目 Schema 或特征字段自动猜测
   - 优点：旧调用者暂时不改。
   - 缺点：对合法业务字段存在长期误判风险，且违反 VNext “MockCase 只在指定边界转换一次”的原则。

3. 拆分为两组新 endpoint
   - 优点：长期边界最清楚。
   - 缺点：范围过大，不符合当前只修明确 Bug 的要求。

## 数据流

HTTP 裸请求：

`{project, input: REQUEST_SCHEMA} → service → SingleTurnCase(input=完整请求) → pipeline`

HTTP MockCase：

`{project, case: MockCase} → parse_mock_case → mock_case_to_single_turn → pipeline`

批量保持：

`MockCase[] → 逐个 parse/convert → typed SingleTurnCase → batch pipeline`

`MockCase.intent` 始终可选：存在时保留，不存在时单轮直接执行，多轮仍可在首轮后调用 `infer_user_intent`。`run_chain` 未显式传入 `user_intent` 时，才使用 runtime case 中的可选 intent。

## 错误处理

- `input` 与 `case` 缺失或同时出现：边界立即拒绝。
- `case` 不符合 MockCase 协议或 `project_id` 不匹配：立即拒绝。
- `input` 不是对象：立即拒绝。
- 业务请求字段缺失：继续由项目 Live Schema 校验。

## 验证

新增回归测试覆盖：

1. DeerFlow `input` 完整保留顶层 `input/config`。
2. QA `case` 完整保留 `output/reference`，provided-output 语义不退化。
3. MockCase intent 为 null 时仍可转换并执行；存在时保留。
4. pipeline 拒绝未转换字典，service 拒绝模糊输入。
5. CLI 裸请求显式构造 runtime case。
6. API check 将 `/api/mock_cases` 返回值放入 `case` 而非 `input`。
7. 运行定向 live/batch/cross-project 测试及全量回归。

## 非目标

- 不修改 Draft/Production Mock 生成策略。
- 不修改 DeerFlow 多轮 Mock Agent。
- 不修改 `normalize_mock_case` 的通用兼容逻辑。
- 不改变前端 Mock 数据集和批量归因协议。
- 暂不修改前端对 `intent: null` 的校验行为。
