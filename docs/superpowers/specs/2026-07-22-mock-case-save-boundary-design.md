# MockCase 保存边界修复设计

## 问题

vNext MockCase 已使用 `intent + live_request` 作为规范存储格式，但 `save_mock_cases` 仍按旧式 `case.input` 校验。当前应急兼容虽能读取 `live_request`，规范 MockCase 随后仍会经过 `SingleTurnCase` 往返转换，导致 `intent.query`、`system_understanding` 和 `intent.scenario` 丢失。

## 目标

- 规范 MockCase 原样、保真保存。
- 旧式 `SingleTurnCase`/`case.input` 只通过明确的兼容迁移路径保存。
- 统一复用 LiveSchemaCheck，不在保存函数内复制请求字段选择规则。
- 不修改 MockCase、Live、Draft/Production 或前端加载协议。

## 设计

保存入口先把每条输入转换为唯一的规范 MockCase：

1. 输入已经是 MockCase dataclass，或字典含 `live_request`：调用 `parse_mock_case` 严格解析，校验项目 ID 和未知字段，保留完整 intent。
2. 输入是旧式 `SingleTurnCase` 或 `case.input`：调用 `normalize_mock_case`，再由 `single_turn_to_mock_case` 完成一次性迁移。
3. 将规范 MockCase 序列化为字典后，调用项目 `LiveSchemaCheck.case_errors` 校验 request、ready/output/reference 契约。
4. 任意输入无效且 `skip_invalid=False` 时不写文件；`skip_invalid=True` 只写通过校验的规范 MockCase。
5. 写盘阶段直接序列化规范 MockCase，不再转回运行时 Case。

## 错误处理

- 解析错误、项目不一致、未知字段和 schema 错误均记录到 `invalid_cases`。
- 保持现有原子门禁语义：默认存在任何无效 case 就拒绝写盘。
- 不吞掉格式错误，也不把规范 MockCase 静默降级成旧格式。

## 验证

- 规范 MockCase 保存后 intent 所有字段完全保真。
- `intent=None` 的 request-first MockCase 可保存。
- 旧式 `case.input` 可迁移到规范格式。
- 非法 REQUEST_SCHEMA、跨项目 MockCase 和未知字段被拒绝。
- CLI `mock-cases --save` 使用动态生成的规范 MockCase 时可以落盘。
- DeerFlow 新固化数据仍能由前端读取前三条。
