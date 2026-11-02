# expectations-v2 独立复审：R1–R7 修复后

2026-10-07。只读源码/测试复审；唯一写入为本报告，没有修改源码、测试、冻结样本，没有启动 live 或 git commit。

## 结论

**原 R1–R7 列出的具体反例均已关闭；仍有一项同类集成缺口 F1（P1），不宜据此宣布 v2 完整验收。** R1 的原子上游依赖、逐问题归属与汇总修复有效，但读取回执及实际输入门禁尚未同步到逐判准：混合 `pass + insufficient_evidence` 可以绕过门禁，llmtracing 对合法的 `input_invalid + pass` 又会误拒。

独立执行 **602 passed / 2 deselected，0.95s**，并用实际函数/提交入口追加了下述探针。除 F1 外，本次指定范围没有发现其他实质阻塞项。这里不做无关风格审查，也不要求新架构、兼容层或放松 schema。

## R1–R7 逐项复验

下列代码路径除注明外，相对 `impl/projects/llm_probe/`。

| 原项 | 当前状态及独立证据 |
|---|---|
| **R1：混合上游、未定位问题、聚合丢失** | **原反例关闭；相关门禁残留见 F1。** `process_output.py:229–235` 对原子 `input_invalid` 要求并保存 upstream，`270–276` 从各问题自己的 breaks 派生 outcome；`process_protocol.py:28–94,114–128` 按问题归属、分别统计单位/判准；`coalesce()` 保留 upstream，主判 slim 保留混合 checks 和 issues。新增 `tests/test_process_v2_atomic.py` 四项通过。另实跑 `pass/fail/insufficient_evidence + input_invalid`：均保留具体上游；原单位总结果为 pass 时，`counts.input_invalid=0`、`criterion_counts.input_invalid=1` 是正确的不同统计口径，不要求改总结果。原“双规则 fail + 未定位缺证”经 `validate_submission → _outcome → _slim_process_axis_for_main` 保持两问题 `local / unresolved`，后者仍为 `insufficient_evidence`；错误单轴归因被拒。 |
| **R2：原文路径和完整性** | **关闭。** `design_rules.py` 保留工具 fields wrappers 及完整工具/function wrapper，不再剪掉 `strict`、`x-condition`、扩展字段。除 `test_design_rule_blocks.py:278–314` 的正反例外，实际把工具参数说明提交给共享 validator，再将保存的 `/fields/parameters/value/properties/id/description` 回查原 record，等于原 quote；旧 `/parameters/properties/...` 被拒。引号、换行、if/then、条件字段保留。此结论针对已登记原文/展开视图，不声称未经解码的传输字符串也能直接按 JSON pointer 下钻。 |
| **R3：persisted call 的配对 span 漏块** | **关闭。** `dossier_blocks()` 沿 provider 已建立的 `span_ref` 登记说明，使用 span 自己的 ref、`/fields/tool_description/value` 和 owning link；不按邻近/同名猜测。`test_design_rule_blocks.py:317–355` 验证 current→execution、collection 仍仅参考、无配对不借用、模型轴不升级该说明。旧冻结 `unit-format-full-live-20261007/result.json` 的 persisted policy_detail 配对 span **389 字**正文现在完整进入候选块。这里只枚举旧冻结材料，没有重判业务。 |
| **R4：内部首个 user 冒充原话** | **关闭。** `expectation_material.py:19–94` 使用外层 request/mock_message 或已注册且关联成立的 Agno run_input；模型消息只建立原文相等后的关联。`test_need_source_boundaries.py:53` 起的外层原话 vs PREPROCESSOR_RESULT、假历史、未知 provider、关联不符及缺原话测试全部通过。真实外层 `Tell me current status.` 不再被内部 ACTIVE 指令替换；没有独立原话时明确缺料，不恢复旧模型消息 fallback。 |
| **R5：交错 system/user 编号与 actual input** | **原编号反例关闭；混合判准变体见 F1。** transcript 使用原 messages 下标：c1.m1 是旧 query，c1.m3 才是当前原话；c2 不继承当前原话。provider 不再凭 trace_ref 命中放行，而核对实际正文。`test_need_source_boundaries.py:173–234` 穿过完整 `_submitter()`：c1 接受、仅有旧 query 的 c2 拒绝、重新收到原话的 c3 接受；伪 ref、调用元信息、渲染正文不能冒充送达。旧调用设计规则也不能仅凭已读/时间先后借给后次调用（`test_process_v2_entrypoints.py` 对应测试通过）。 |
| **R6：E/投影身份、B 绑定与结果回执** | **关闭。** `validate_expectations/validate_projection/required_units` 重算 E hash，核对 projection hash、唯一 E ID 及 data_needs 精确覆盖；两构造器在准备工具前拒绝错误身份，空 E/未启用轴也不绕过。原 `WRONG + [] → []` 反例现在拒绝。`test_expectations.py:595` 的 preparer 实收 B1，相对 `/description/value` 回填原长 design ID、原 ref、`/fields/description/value`，最终位置回查成功；E hash 和 `design_sha256=SHA256(json.dumps(tools, ensure_ascii=False, sort_keys=True))` 均核对。错误 B/长 ID/绝对路径/改写 quote/漏需求被拒，最多纠正一次。llmtracing 脚本全六轴测试及本次额外 Agno 父子 ScriptClient ToolLoop 均验证各轴 view 保存实际消费 E hash、有/无 design hash、调用方事后改对象不影响内部快照。已有实现指纹依赖表补项测试也通过。 |
| **R7：保存场景字段被删** | **关闭该规范化/消费接缝。** `impl/core/capability_store.py:61–74` 保留并校验 criterion/description，原空白和换行不改写；downstream 只占位。本次实际调用 `save_capability → validate_entry → active artifact registry → load_capability_map → 再保存 → project_requirements`，仅最底层文件 I/O 改用内存 sink，未替换业务校验；两次保存后字段仍原样，criterion→want、description→background、capability 未拆分仍 partial、downstream 不进需求。**没有独立执行磁盘落盘测试**；该项现有真实临时目录测试在协调方最终全仓日志中通过，本次为遵守只写报告而 deselect。 |

### 可选与 Nullable 契约：不重新提出 null 要求

本任务明确的契约是：**“path is optional string (omittable or empty), null rejected intentionally”**。

- `Quote.path` 与 preparer `ToolOption.path` 都是 `str`、默认 `''`、允许空串；**可省略不等于 nullable**。省略/显式空串通过，`null` 拒绝是有意行为，不是待修 bug。共享 Quote 正反例及本次 ToolOption 直接探针均符合。
- `Necessity` 使用 `@validated_dataclass(config={'extra': 'forbid'})`；嵌套额外字段的实际提交测试通过。没有建议绕过 Pydantic、启用其他输出格式或放松字段检查。

## F1 — P1：后续证据门禁仍看单位总结果，而非原子判准

这是 **R1/R5 的残留集成边界**，不是把已修的原反例再报一次。

**位置**

- `process_loop/evaluation.py:126–138::validate_read_endpoints()`：只有单位总 outcome 为 pass/fail 才要求运行端点完整读取。Agno 与 llmtracing ToolLoop 共用。
- `process_loop/expectation_projection.py:242–266::validate_dossier_expectations()`：外层按总 outcome 跳过，里面原有逐 expectation check 检查也就不执行。案卷批次与 Agno ToolLoop 共用。
- `business_trace/providers/llmtracing_evidence.py:195–207,246–257::validate()`：总 outcome 非 pass/fail 直接 continue；进入后又对全部 `expectation_ids` 要求原文送达，包括原子 `input_invalid`。

### 实测 A：没有读任何运行端点，也接受原子 pass

以下是实际执行过的最小探针，使用现有 fixture 和完整提交函数，不修改源码或绕过 validator。运行时置于原评审文末同样的只读/禁网络 audit hook 后：

```python
from tests.test_process_v2_entrypoints import fixture, rule_reply

for provider in ('agno', 'transcript'):
    ev, units, blocks, submit, read = fixture(provider, 'output_faithful')
    answer = rule_reply(units, blocks, 'insufficient_evidence')
    for unit in answer['units']:
        unit['rules'][0]['missing'] = ['Separate design applicability unresolved']
        for check in unit['checks']:
            check.update(outcome='pass', fact='CLAIMED PASS WITHOUT READING RUNTIME', missing=[])
    # 故意不调用 read()。
    print(provider, submit(**answer))
    print([(r['outcome'], [c['outcome'] for c in r['criterion_checks']], r['evidence'])
           for r in ev.submitted['model_capability']])
```

两个入口均返回 `accepted=True, issues=[]`；保存的是：

```text
outcome=insufficient_evidence
criterion_checks=[pass, insufficient_evidence]
evidence={input: [], output: []}
```

**对照**：新建同样 fixture，只删除那个缺证 rules、保留 pass，两个入口都正确拒绝“必要端点没有此前批次完整正文回执”。因此不是 fixture 自动提供了读取回执，而是混合总结果绕过了同一门禁。

### 实测 B：未送达 E 的 pass 被接受，正确 input_invalid 反而被拒

使用 `test_need_source_boundaries.interleaved_trace()/frozen()` 的原 R5 数据，正常 `build_transcript → TranscriptEvaluation`，只启用模型 `output_faithful` 子能力并将 E1 应发生单位 matched 到 c2.response；先完整读取运行正文、完成 post_batch。未改 E、投影、实际输入成员或来源值。

| E1 的原子结论 | 同单位通用义务 | 总结果 | llmtracing 完整 `_submitter()` 实测 |
|---|---|---|---|
| pass | pass | pass | **拒绝**：出处未证实进入本次输入（原 R5 已修） |
| pass | insufficient_evidence | insufficient_evidence | **错误接受**：保存 `expectation_checks[E1].outcome=pass`，但 c2 只有 Earlier request. |
| input_invalid + 已接受上游问题 | pass | pass | **错误拒绝**：仍要求 E1 出处进入本次输入 |

第三行的上游不是捏造 ID：先经同一 evaluator 的真实 `eval_context_memory` 提交 c2 `input_assembled` 失败，取得 accepted/local 问题，再经 `Call/History → post_batch` 提供下一批回执。共享原子校验已经接受此依赖，provider 随后误拒。

另用现有 `agno_instance('output_faithful')`，通过 `required_units/criteria_for/build_units` 建立含 E1 的 AxisCase，完整读取 call/answer：其实际输入是 `Check device A.`，而 E1 原话是 `Tell me current status.`。同样得到 **all-pass 拒绝、E1 pass + 通用缺证接受**，穿过的是实际 `_make_submit()`。案卷批次共享上述 `validate_dossier_expectations` 总结果门禁；本次没有另跑一轮批次模型调用来复现它。

**影响与边界**：前两种误接受的总 verdict 仍是缺证，不能夸大为“整轴被判 sound”。实际错误是通过正式提交保存了无证据/未收到需求的原子 pass，后续 composition、checks 与主判均会消费它；反向误拒又阻止合法的部分输入无效提交。这属于机械保证缺口，不是模型语义准确性争议。旧 `before/llm_probe/process_loop/expectation_projection.py:287` 已有相同总结果入口门禁，不归因于本轮修复新引入。

**最小修复**：让现有读取/两端/实际输入门禁按每条判准的 outcome 生效；存在原子 pass/fail 就不能被其他缺证项免检。E 的送达检查只约束其原子 pass/fail，不因别的判准 pass 而强迫 input_invalid 的 E 也已送达。保留当前 outcome 优先级、上游引用和未定位问题，不靠删除/改写原子结论过校验。补上述两个入口的无回执混合例及 actual-input 正反矩阵即可，不需新配置层。

## 验证范围与既有日志

独立 pytest：Python `/Users/xiaozijian/miniconda3/envs/agno/bin/python`，`-B`、`PYTHONDONTWRITEBYTECODE=1`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，参数 `-q -s -p no:cacheprovider -p no:logging --assert=plain`。audit hook 拒绝文件写入/目录变更、子进程及 socket connect/bind/sendto/getaddrinfo；所有额外探针同样守护，脚本仅经 stdin 执行，不落文件。

14 个测试文件（均在 `tests/`）：

- `test_process_v2_atomic.py`、`test_process_v2_rules.py`、`test_process_unit_output.py`、`test_process_criterion_checks.py`
- `test_design_rule_blocks.py`、`test_process_v2_entrypoints.py`、`test_expectations.py`、`test_expectations_v2_need_judge.py`、`test_need_source_boundaries.py`
- `test_process_prompt_contract.py`、`test_axis_materials.py`、`test_process_main_judge.py`、`test_process_axes_protocol.py`、`test_llmtracing_tool_loop.py`

**602 passed / 2 deselected**。排除精确测试名：`test_save_preserves_need_fields_through_active_artifact_and_projection`（写临时目录）和 `test_true_llm_client_and_tool_protocol_work_with_local_fake_server`（本地网络也不允许）。额外 Agno 全六轴身份探针使用 ScriptClient 跑真实父子 ToolLoop，非 SDK/网络集成测试；两次均完成，子/父调用数为 2/3。F1 是另做的实际函数反例，不在“602 通过”中伪装成已覆盖。

协调方已有 `tests-final.log:725–739`：**2406 passed / 14 failed / 5 skipped**。我读取了日志，并程序比较这 14 个失败 node ID 与 `tests-after-first.log`，集合完全一致；原评审遇到的 projection 错误文案断言现已通过。**没有独立重跑全仓，也不把相同失败名单说成全仓已绿。**

任务告知 live1 在 prep 失败、live2 正在运行；本次未启动、核验或评价它们，不宣称 live 成功、规则语义全部核实或性能目标达成。

## 源码版本定位

读取与探针时间约 **2026-10-07 20:55–21:01 UTC**。HEAD 为 `cde26b13a42dc7c8493d55d99552f0e3ebf420b3`，工作区大量未提交/未跟踪改动，**HEAD 不是本次被审实现快照**。下表 SHA-256 在开始与探针结束复核一致；结论仅覆盖这些工作区版本，不追认之后的并发修改或 live 产物。

路径相对 `impl/projects/llm_probe/`，`impl/core/` 行除外：

| 文件 | SHA-256 |
|---|---|
| `eval_axes/adapters/process_output.py` | `2dafb97c126e446ed9a6f8b6e73715e8cd28a1d8fd3edfedfbb8a29b6bc36cf8` |
| `eval_axes/adapters/process_protocol.py` | `65de3dd97b72404164430679582e9af7f574463d3f83d9f0b4f72b7a86202a09` |
| `eval_axes/adapters/process_common.py` | `cc73c1d1f1eed0ebed6b4385ede8aa6855cecac924d1b557b731f5f75d5c66c9` |
| `process_loop/expectation_projection.py` | `e39822bf2348916e9d58a6aa0ed2d398d344cc7097e5c5430852e7aa5f4529fd` |
| `process_loop/evaluation.py` | `b8a9977f58f9f3e5d9ced2d53387959a323aad8544bea4faf026b5876aba5e17` |
| `process_loop/llmtracing.py` | `0e7847eab9efa7167597c41005f8083beebb93ca2a4ab68398fa93c3602124c3` |
| `process_loop/llmtracing_report.py` | `8eaad49315b7eed632ade06faeca55918aa34a5793dc230dc7e0b889b46c9688` |
| `business_trace/design_rules.py` | `f53b4b9b70a73c23d145389a3886361d2803ab16d1304c0faeb774833679c61e` |
| `business_trace/expectation_material.py` | `c4907502fc8bbbd33c2e8cb2fb28d5278461e860b35dc1b5b7a6636d53e49a0e` |
| `business_trace/providers/llmtracing_transcript.py` | `588b20b9b3f3442ba4af672f37c66c4a6526ab6aefa13ab8f4638190ae9c65d4` |
| `business_trace/providers/llmtracing_evidence.py` | `251e2bd9fe250192fc5879144b7bbbaf65610307b96f3fcf5d2fc1e392b87129` |
| `judge.py` | `fec64d3a8cfad97c4a5b33b1a6dff874fc81e73f7a2c531e981ea82df3a4d37d` |
| `impl/core/capability_store.py` | `afba7143b9af1807b0f1d5ff3afab69d258ec40c842b7e0156417a30a2f38e52` |
| `impl/core/structured_output.py` | `434a442c3baf25fd795213a6d22ea0b3e7cc3d5f028c9309f1fb0d3754a2d497` |

**下一步只有一项代码阻塞：补 F1 的逐判准证据门禁并回归该矩阵；其余原修复保持。** 真实 live/语义/耗时验收另按最终运行事实记录，不能由本报告的离线通过代替。
