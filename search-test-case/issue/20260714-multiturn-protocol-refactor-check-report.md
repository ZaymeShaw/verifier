# 20260714 多轮协议改造后 check 审查报告

## 审查范围
本轮 A1-A4 + B1 修复（19 次文件改动，10 个文件）的实测验证。

## Check List

### ✅ 通过

1. **A1 dead code 删除**：`mock_build_interaction` 相关 5 处全部清除（routes/service/models/pipeline/schema_api），前端不依赖。
2. **A2 `_MockProtocol.next_turn` 默认实现删除**：约束收敛到 MultiTurnInteractiveMock @abstractmethod + SingleTurnMock 禁止覆盖，无双重路径。
3. **A3 注释修正**：`mock_agent.py:135` 已改为"由协议层 MultiTurnInteractiveLive.deliver_multi_turn 调用"。
4. **A4 协议层默认实现通用化**：
   - `_should_stop` 默认只看 max_turns
   - `_build_turn_trace` 默认采集通用字段（turn_index/user_query/assistant_summary/call_status/runtime_ms）
   - `_collect_missing_fields` 默认返回空
   - `_summarize_assistant` 默认通用摘要
   - `_build_next_turn_input` 默认去掉 marketting 特化分支
   - 两处 try/except 改为 logger.warning 留痕
   - `_FORBIDDEN_OVERRIDES` 从 5 项缩到 1 项（只 deliver_multi_turn @final）
   - marketting-planning Live 覆盖 4 个方法恢复特化语义
   - deerflow Live 覆盖 3 个方法（无 card/path_type/missing_fields）
5. **B1 fixture 添加 + schema 合规**：marketting-planning 和 deerflow 各 1 条 interactive_intent fixture，通过 live_schema 校验。
6. **单元测试**：21 passed。
7. **marketting-planning 多轮实测**：4 轮跑通，trace.status=ok，output_source=interactive_adapter。
8. **deerflow 多轮实测**：4 轮跑通，trace.status=ok，planning_summary present。

### 🔧 修复中发现并修复的问题

**问题1 — `_batch_case` except 吞异常掩盖真实 bug**（pipeline.py:421）
- 原代码：`_run_interactive_case` 抛任何异常都被包装为 `_unsupported_interactive_run`（"not supported"）
- 真实影响：deerflow 多轮实际是 attribute 阶段 AttributeError，被错误报为"adapter 不支持"
- 修复：删除外层 except，让真实异常上抛；isinstance 不支持的兜底由 `_run_interactive_case` 内部处理
- 违反 check.md 原则 c（只优化展示不优化源头）

**问题2 — `_assemble_multi_turn_result` project_fields 硬编码为空**（live_protocol.py:902）
- 原代码：`project_fields={}`
- 真实影响：多轮聚合结果的 trace.project_fields 为空，下游 attribute 读 `project_fields.planning_summary` 拿到 None，触发 AttributeError
- 修复：`project_fields=last_result.project_fields if last_result and isinstance(...) else {}`
- 违反 check.md 协议对齐原则 + 原则 d（数据不同步）

**问题3 — B1 fixture 形状不合规**（已在 /aihacking 阶段修复）
- marketting-planning fixture 缺 `current_turn`，`user_intent` 类型错（dict vs str）
- deerflow fixture 多带 `case_id`（不在 REQUEST_SCHEMA）
- 修复：补 current_turn，user_intent 改 str，删 case_id

## 最终状态

- 协议层默认实现通用化 ✅
- 项目特化语义下沉到项目 Live ✅
- 多轮路径在 api-check 中有 fixture 覆盖 ✅
- marketting-planning + deerflow 多轮实测通过 ✅
- 无静默吞错 ✅
- 无 dead code ✅

## 备注

- 单条多轮 case 实测耗时：marketting-planning 283-598s，deerflow 425-505s（4-5 轮 LLM + 业务 API 调用）
- 后续若跑全量 api-check（含多轮 case），预计总耗时会显著增加
