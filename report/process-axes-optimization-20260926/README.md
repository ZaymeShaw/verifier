# 六轴优化：证据补查与信息传递核验

本次完成首个可运行版本：上下文管理回到信息传递/状态/交付职责，六轴可从同一冻结案卷补查，证据沿读取回执进入最终裁决。没有使用 backup 中的 skill，没有新增依赖，也没有修改业务后端或 mock_cases。

**当前验证结论：机制与证据覆盖已验证；已对 B10、C09、D01 发起主模型实测。B10 规划轴与 C09 知识轴命中人工裁定；D01 工具轴首次误判为正常，修订后在部分案卷上改为证据不足，尚未证明能识别工具根因。不能据此宣布六轴整体更准。**

## 实现

- `context_memory.py`：检查步骤/工具结果传递、缓存和历史、模型输出到交付，并覆盖完整案卷中的每次模型输入。删除原始请求缺失时预置 not_applicable 的逻辑。没有模型调用记录时仍检查是未发生还是未采到。
- `process_common.py`：六轴复用现有案卷工具，可批量取件/下钻/搜索/核对顺序。3 次补查硬预算，格式重试共用预算；重试新会话不能引用前次未重新看到的材料。目录和对照入口共用初始材料预算。角色、模型配置和推理档位未提高。
- `comparisons.py`：只建立已有记录支持的对照入口。工具到模型输入使用 provider 明确关联；模型输出、后续步骤、落库和实收输出按轮列为候选对照，不推断因果或给语义判定。
- `dossier.py`：落库结果与调用方 extracted_output 独立保存，没采到实收输出时明确缺口；不把落库内容伪装成实际 HTTP 交付。原文、结构图和仅有指针的可引用性分开。
- 工具、知识、模型、规划轴：明确假空需核验，工具内部解析属于工具职责；未取得知识不等于证实全库不存在；准入拒绝应对照模型实际收到的规则；相同失败结果不自动证明缓存或重试错误；终止时须检查是否丢弃仍能完成的工作。
- `judge.py`：合并整理与六轴补查回执后渲染引用原文，再移除审计元数据。补查的大记录片段及源记录能抵达最终裁决；按原文核对跨轴事实矛盾，不按根因去重。
- `dossier.py`：每种记录须分别读取才有引用资格。修掉选中 `messages` 后，未展示正文的同源 `#reasoning` 编号也被默认为可引用的漏洞。
- `planning_routing.py`：单列工具返回后的整合与交付检查。工具事实被 bridge 提取、finalize 返回成功，不等于模型继续整合或交付了用户可读答复。
- `tool_execution.py`：单列拒绝与未命中依据检查。返回 `AMBIGUOUS`、`EMPTY` 或查询未执行时，必须核对原请求、公开能力与解析/后端证据；不能凭 HTTP 200 或响应形态给正常结论。
- `llm.py`：补齐同模型路由器的重试候选接口；固定同模型策略不再让预探活先把唯一获批端点标为冷却，真实请求失败仍如实记录。
- 同步保险场景的四处相关轴描述以及 `spec/adapter/business-trace-v1.md`，避免旧场景口径覆盖新轴职责。

输出继续使用当前六轴协议的 assessment/checks/evidence_refs/missing_evidence。检查项负责覆盖；每项 finding 必须说明事实、环节、影响与尚未确认的原因。程序不改写语义结论，只核查范围、格式、引用与读取资格。

pass/not_applicable 必须有范围与证据，不能同时带影响判断的缺口。已证明的问题可判 problematic 并保留其他缺口。未知或未读引用不会因还剩一个有效引用而被包装成完整裁定。

## 验证

- 改动前直接相关测试：63 passed。
- 改动后相关测试：241 passed（176 个无需本地服务的测试，加 65 个扩展轴测试）。最后新增的材料预算测试单独通过。
- 其中 `tests/test_process_axis_investigation.py`：18 passed，覆盖补查未选材料、目录/搜索/结构图不等于已读、重试证据隔离、共享预算、未选模型调用仍被检查、真实交付与落库分离、主轴保留读取粒度、缺证不能通过等。
- 冻结材料：`evidence-audit.json`，30/30 份离线核查通过，34 轮、65 次模型调用、54 条工具返回到重建输入的关联、34 份落库结果、29 份实收输出。5 份仅有原始快照的样本没有伪造实收输出。每份输入保留 SHA-256。
- Python 编译检查、修改文件空白检查通过。
- 继续复核时新增 [9 月 24 日事件级裁定集](adjudication-oracle.json) 和 [旧评测表逐格审计](adjudication-audit.md)。本地运行库只读核对 B10、E01、B02、E02 的模型与交付事实；证据资格漏洞加了端到端引用拒绝测试，相关测试 47 项通过。
- 主模型回放后的过程轴相关测试再次运行，83 passed；重放脚本与规划轴编译通过。

离线核查只证明原文保存、对照入口可解析和调用范围不遗漏；测试中的 LLM 替身不证明语义准确率。没有拿更多 nf 或更少缺证冒充改进。

仍有两项既有测试与当前用例数据不匹配，首轮扩大测试时均为 StopIteration：

- `test_insurance_agno_fixture_is_real_only_and_live_evaluated` 要求已不存在的 `llm-probe-insurance-real-policy-status-authorized`。
- `test_transcript_seed_replays_serially_in_one_fresh_session` 要求已不存在的 `llm-probe-insurance-real-ctx-ref`。

当前保险集是 32 条、8 个多轮 seed；旧测试还假设固定四个 seed 和固定两轮。这两项未通过，也未改测试标准或业务用例来凑通过数。其余关联测试通过。本地 HTTP 测试初次受沙箱监听限制，随后以只连接 127.0.0.1 的测试方式重跑，65 项全部通过。

## 主模型实测

用户批准冻结保险 Trace 发往主端点 `8.148.158.241`，模型为 `gemini-3.8-flash-medium`。回放脚本强制 `EVAL_AXES_MODEL_POLICY=same_model`，并拒绝同模型候选中出现其他主机。未向配置中的备用端点发送 Trace。

本次从只读 SQLite 重建了九个已人工裁定用例的 Agno run/span，最终调用方输出取自 9 月 24 日工作簿。AgentOS HTTP Trace API 未运行，因此这些是**部分案卷**：逐次精确模型请求、原始后端 HTTP 和完整会话快照未采到。结果只适用于已读到的证据。

| 用例/轴 | 新版实际结果 | 人工裁定对照 |
| --- | --- | --- |
| B10 规划与路由 | 初次全轴回放该轴因端点连接错误失败；复用成功的整理轴重测后判 `problematic`，`post_tool_integration` 与 `sensible_termination` 均 fail | 命中“工具返回后模型循环被取消，原始 QA 卡片直接交付”的事件；其余规划检查独立判定 |
| C09 知识与数据 | 整理轴完成；初次知识轴失败，间隔后复用相同整理结果重试判 `problematic`，指出保单数据已给出，但 `general_qa` 返回“趸交与年交”而非用户问的“年缴保费与累计已交保费” | 命中知识召回不相关的事件；没有把源头问题归为上下文传递 |
| D01 工具执行 | 整理轴完成；首次工具轴判 `sound`，把三次未执行查询的 `AMBIGUOUS` 当成合规拒绝。新增独立拒绝依据检查后复测判 `not_evaluable`，指出缺少解析器/后端原始证据，不能确认拒绝正确 | 首次与人工裁定冲突；修订版不再误判为正常，但部分案卷不足以独立证明已知的适配层故障，不能算命中根因 |

原始机器输出在 [`live-adjudicated/`](live-adjudicated/)。有效的定向结果见 [`retry-B10-planning_routing.json`](live-adjudicated/retry-B10-planning_routing.json)、[`retry-C09-knowledge_data.json`](live-adjudicated/retry-C09-knowledge_data.json) 和 [`retry-D01-tool_execution.json`](live-adjudicated/retry-D01-tool_execution.json)；D01 修订前误判见 [`D01--tool_execution.json`](live-adjudicated/D01--tool_execution.json)。连接错误及限流是模型端点/传输失败，不能算被测业务失败，也不能算语义误判。D01 的 `not_evaluable` 是证据边界改进，不是人工已知根因的自动确认。

下一步需要端点稳定后在同一冻结输入、同一模型/参数下完成剩余六例，并核对事实、轴归位、漏判、误判、缺证及成本。9 月 24 日七类裁定只能按事件对照；知识库不存在与事后解析探测结论须保留证据强度限制。

本版补查只访问冻结案卷。源码调查和外部依赖探测未接入，原因无法确认时报告缺口。

## 复现离线核查

```sh
/Users/xiaozijian/miniconda3/envs/agno/bin/python scripts/check_process_evidence.py \
  --out report/process-axes-optimization-20260926/evidence-audit.json
```

## 自审

- aihacking：没有按 case id 写规则，没有人工注入目标 verdict；缺证与预算耗尽不计为通过。
- generalization：比较入口使用已有记录类型和关联，不依赖保险步骤名、产品、保单号或预期文案。
- elegance_review：复用 EvidenceIndex 和现有 Agno 工具封装；删除旧预置分支；未新增配置层、兼容层或依赖。
