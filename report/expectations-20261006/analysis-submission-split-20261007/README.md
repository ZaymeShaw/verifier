# 分析轴提交结构拆分：实施与验证

## 范围

仅实施已确认的第一批：删除用空字符串切换两种发现的提交协议。未修改需求轴、上下文容量、重试/超时、六轴判定与调度。未修改现有需求或方案文档，未重启 8021/8022/8030，未重新请求业务系统。

## 实现

模型调用 `submit_structure` 时必须提交四个字段：

```json
{
  "route": [],
  "coverage_note": "本次可还原的范围",
  "existing_link_suspects": [],
  "new_link_suspects": []
}
```

- 已有环节记录只含 `link_id / why / source_refs`，必须引用原环节表。类型与端点从表里取得。
- 补充环节记录只含 `link_type / input_refs / output_refs / why / source_refs`，表示运行证据中实际发生、原表漏列的可疑步骤；编号由程序在提交通过后分配。
- 没有某类发现就提交该列表 `[]`，不填空字符串或空对象。类型枚举中不再包含空字符串。
- 两类记录均必须提供非空发现依据；补充环节至少一端有证据。未知类型保留已有 `unclassified`，不强行归轴。
- 顶层和记录拒绝额外字段；旧的 `suspects + new_link_type` 提交被明确拒绝，不提供兼容解析。
- prompt、工具 schema、结构校验、引用收集与回执门禁同步更新。
- 通过后仍物化为下游既有的统一 `suspects` 记录。这是模型输入到内部结果的转换，不是旧提交协议兼容。
- 原有程序发现不因两个模型列表为空而丢失；正常环节的完整下游材料仍然交付。

代码修改仅在：

- `impl/projects/llm_probe/eval_axes/adapters/trace_analysis.py`
- `impl/projects/llm_probe/process_loop/analysis.py`

测试同步更新 `test_trace_analysis.py`、`test_trace_analysis_submission.py`、`test_process_loop.py`，新增 `test_analysis_submission_contract.py`。

## 本地验证

新增测试先在修改前运行：7 failed、13 passed；确认旧实现无法处理新列表，且仍接受旧空字符串提交。

最终扩大回归 **255 passed**，覆盖：

- 两列表都空、仅已有发现、仅补充发现、两类同时存在；
- 非法编号、混填字段、空依据、两端皆空、旧协议均拒绝；
- 未读证据、同轮读取后立即提交仍被拒绝，下一轮有回执后可提交；
- 既有发现从表中取得类型和端点，重复线索合并但不丢理由；
- 无法分类的补充发现保留；正常材料与程序发现不丢失；
- 普通轴入口与父子 ToolLoop 经过真实 SDK 的本地假端点集成；
- 检查 SDK 实际发出的工具 schema 和 system prompt，不仅检查代码常量；
- 需求、六轴、证据边界和预算相关回归。

测试过程中禁止访问真实模型中转和业务服务，仅允许本地测试假端点。日志见 `tests-before.log`、`tests-after.log`。初次集成有一项测试因新增必填 source_refs 改变引用优先顺序而失败，已按现有“发现依据优先、再列端点”的语义修正该样例断言，没有改动下游选择算法。

## 实际供应商核验：仍被环境阻断

执行了一次独立、有限的空案卷 schema 探针：`analysis-submission-split-schema-20261007`。

它使用当前 Analysis 生成的六个工具定义，要求提交空列表；不发业务材料、不执行工具、不调用备用端点，SDK 自动重试关闭，60 秒超时。这不是实际 case 分析，也不是语义验收。

结果：约 7.8 秒后返回 HTTP 400，内容为 `User location is not supported for the API use`。

- 原始网关请求确实包含新的两个列表，类型枚举不含空字符串。
- 网关记录 3 次 pre_api_call 和最终 failure；这是网关内部行为，不应误报成三个独立模型评测轮次。
- 由于访问位置限制阻断，**不能据此声称 Gemini 已接受新 schema**，也不能声称真实分析轴已完整验收。
- 未切换备用端点、未扩大重试、未用放宽校验来制造通过。

请求、结果及网关事件分别在 `provider-probe-request.json`、`provider-probe-result.json`、`provider-probe-events.jsonl`。`probe_schema.py` 保留了可复核执行器。

后续需在可用的同供应商连接上验证 schema 接受，并用保存的业务 trace 完成分析轴读取、提交及下游材料验收；此前的 184,320 字符容量问题和重试预算问题仍未处理。

## 未改变的边界

162 份现有 demand/spec 文件哈希全部未变，见 `protected-documents.json` 与 `implementation-manifest.json`。没有变更共享客户端、模型配置、场景配置或业务代码。

8021 现有进程不会热加载这些修改。本轮没有重启服务，也没有把旧进程结果当成新版本验收。

仓库全局 `git diff --check` 开始时已存在两个无关空行警告（`impl/core/live_protocol.py`、`impl/projects/policy_search/mock.py`），本轮未触碰它们。
