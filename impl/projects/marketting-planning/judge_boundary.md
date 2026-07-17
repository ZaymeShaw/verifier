# marketting-planning judge boundary

边界判断由 live 层作为每轮执行事实上报，由 trace 层写入 `RunTrace.application_boundary`；judge 只消费当前 case 的标准 trace 边界，不在 prompt 中重新猜测责任范围。

## 当前责任范围

- 请求归一化是否保留用户意图、多轮顺序和 expected stage。
- 意图识别是否进入正确阶段。
- 缺字段时是否澄清。
- 字段补齐后是否进入规划。
- path_types 是否按意图选择。
- 卡片摘要是否覆盖 required cards/path types。
- SSE 是否有可解释事件顺序、结束状态和错误信息。
- fallback 是否符合当前 boundary 的 allow_fallback。

## 外部依赖边界

外部服务、数据源、session store、模型依赖不可用时，adapter 记录 `dependency_status`。如果当前 reference/boundary 明确允许该不可用状态，judge 不应把外部依赖本身作为本系统错误；如果 fallback 掩盖了本应完成的内部阶段，则仍可判错。
