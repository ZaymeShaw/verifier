可以，而且这正是 schema.md 强调的"对接位置标准化"的应有方向。把 ready 逻辑下沉到协议层、项目层只声明配置，能消除你担心的"项目实现不稳定"问题。具体可以这样设计：

## 协议层统一接管 ready

**1. 声明源唯一化** —— `common.ready` 只在协议层读取一次。
- adapter 侧：`adapter.py:74` 已经是 `self.spec.common.get("ready")`，保留。
- judge 侧：`judge.py:344-351` 当前用 `load_project(trace.project_id)` 反查文件，**改成从 trace/spec 直取**，避免重载文件与内存 spec 不一致。建议在 `RunTrace` 上挂一个 `ready: list[str]`（或 `provided_fields`），由 pipeline 在构造 trace 时从 spec 注入一次，judge 直接 `trace.ready` 读取，单一数据源。

**2. provided 分支由协议层决定，不由项目 adapter 重写**
- 把 `has_provided_output` / `provided_output_raw` 留在 `ProjectAdapter` 基类作为**最终实现**，不再让子类 override。
- QA adapter `call_or_prepare` 里硬编码的 `execution_mode="provided_output"`(`QA/adapter.py:37`) 删掉，改由 `pipeline.live_run` 的 `has_provided_output` 分支统一构造 `LiveExecutionResult`（即 `pipeline.py:184-207` 那段）。这样 QA 改 `ready: []` 后会自动回落 live，配置与行为不再脱节。

**3. 把 ready 做成协议层的一个 gate/解析器，而不是散落在两处 if**
- 可以在协议层（比如 `interaction_protocol` 或新增 `ready_protocol`）定义一个 `resolve_ready(spec, case) -> {output: bool, reference: bool}` 的纯函数：
  - `output_ready = "output" in ready and bool(case.output)`
  - `reference_ready = "reference" in ready`
- adapter、pipeline、judge 都调这同一个函数，禁止各自再写 `"output" in spec.common.get("ready")` 这种内联判定。这才能保证"对接位置结构统一"。

**4. 项目层只留两件事**
- 在 `project.yaml` 声明 `common.ready`（配置）。
- 实现 `extract_output` / `build_request` 等纯业务钩子（行为）。
- 不再实现 `has_provided_output`、不再硬编码 `execution_mode`。

## 收益

- **稳定性**：ready 的真值只来自 `common.ready` 一处配置 + 一个协议函数，项目 adapter 无法旁路。
- **可审计**：QA 那种"声明 ready=[] 但 adapter 仍走 provided"的配置/行为脱节不会发生。
- **单一数据源**：judge 不再 `load_project` 反查，trace 携带 ready，与 adapter 同源。

## 需要向用户确认的点

- 是否允许在 `RunTrace`（schema）上新增 `ready` 字段？这属于 schema 变更，按 schema.md 规矩要先确认。
- QA 的 `call_or_prepare` 重写如果撤掉，要确认 QA 没有依赖那个硬编码 `_normalized_request` 注入的下游逻辑（`QA/adapter.py:40` 那段），否则要把这部分也下沉到协议层 provided 分支。

一句话：方向对，ready 该是协议层 gate，项目层只声明不实现。落地前需要你确认上面两个 schema/行为变更点。