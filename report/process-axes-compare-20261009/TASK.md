# 任务：现行六轴 vs「本应清单/实际清单」同模型对比实验

> 派发方：verifier 主会话（Claude Code）。用户已同意由你执行。
> 方案草稿：`spec/draft/process-axes-expected-actual.md`（必读，尤其第 3、4、5、10 节）。
> 背景与上一轮走查：`report/process-axes-reference-20261009/README.md`（必读）。
> 产出全部写在本目录 `report/process-axes-compare-20261009/` 下。

## 0. 硬性约束（违反任何一条请停下来，在 RESULT.md 里说明，不要绕过）

1. **不改** `demand/`、`spec/alg/`、`spec/draft/`、`impl/` 下的任何文件，不改测试。新方案的实现只写成本目录下的实验脚本。
2. **不提交、不推送 git**，不切分支。
3. **不重启、不停止**任何服务（8021 verifier、18062 业务服务、4008–4010 网关）。本实验只回放已记录的运行，不需要业务服务。
4. **不打印、不写入任何密钥值**。读 `.runtime/instances/inst-16fa340ac786414f/tracing/.env.verifier_*` 时只取值使用，不回显；值两端有引号要去掉。
5. **两边必须用同一个模型。** 先探测 primary 中转（`.env.verifier_primary`）上的 `gemini-3.8-flash-medium` 是否可用（2026-10-09 它返回 400 `User location is not supported`）。可用就两边都用它；不可用就两边都用 fallback2 的 `deepseek-flash`。deepseek 中转并发超过 3 会 429，并发 ≤3 并带退避重试。**现行这一臂的每一次六轴调用实际用了哪个模型，要从留档里核实并报告**，不能只看配置。
6. 输出被截断（`completion_tokens` 顶到上限）、限流耗尽、解析失败的调用，必须**补跑并保留失败那次的记录**，不得当作结果。

## 1. 样本：先登记已知问题，再跑

数据来源：job `fb5fda5628174ef6967116bd4ecca493`。导出文件已在
`/private/tmp/claude-501/-Users-xiaozijian-WorkSpace-projects-claude-code-verifier-runC-verifier/84d49b1f-9f6b-4ebc-bf2a-665a1fc62378/scratchpad/trace2.json`（约 343MB）；
不可用时重新导出：`http://localhost:8021/api/tracing/report?project=llm_probe&job_id=fb5fda5628174ef6967116bd4ecca493`（HTML 内嵌 `<script id="DATA" type="application/json">`）。
可复用 `report/process-axes-reference-20261009/build_case_files.py` 还原单个 case 的完整案卷。

候选 case（主会话之前逐 case 核实过，但**当时的序号与本批 case_id 的对应关系有一处对不上**，所以必须由你在本批 trace 上重新核实）：

| 候选 case_id（去掉前缀 `llm-probe-insurance-real-`） | 之前记录的业务缺陷 | 主会话核对状态 |
|---|---|---|
| smoke-customer-profile-fuyunping | agent_bridge 模板重写丢了模型草稿的内容；customer_detail 传了空的 customer_ids | 空 customer_ids 在本批 trace 中确认存在 |
| smoke-policy-list-fuyunping | 之前记作「customer_detail 传空 id」 | **本批 trace 中没有找到空 id**，需要你判断这里到底有什么缺陷 |
| smoke-agg-paid-prem-fuyunping | agent_bridge 模板重写；上游 UPSTREAM 错误后反复调用同一失败来源 | 未核 |
| smoke-multi-policy-anjinning | 交付漏了一张保单 P260922000007861 | 该保单号在本批案卷中存在；是否被漏需核 |
| main-A01-fuyunping-list-aggprem | agent_bridge 模板重写 | 未核 |
| main-B01-meeting-prep-fuyunping | 模型草稿写了三个开场问题，被 agent_bridge 模板重写覆盖 | 未核 |
| main-D01-same-surname-clarify | 见上一轮走查 R4–R7 | 已核（`report/process-axes-reference-20261009/problems_triage.md`） |
| smoke-policy-detail-renyanlin | 见上一轮走查 R1–R3、R8 | 已核（同上） |

**在跑任何一臂之前**，完成并冻结：
- `known_issues.md`：每个 case 的已知业务缺陷清单。每条写清「哪一步、现象、预期、实际、trace 记录 id」，必须在本批 trace 里找到证据；找不到的不列，写明「未在本批找到」。
- `triage_rules.md`：问题归类规则——命中已知问题 / 重复拆分 / 过度断言 / 被案卷反驳 / 无法判断，以及判定口径。可参考 `report/process-axes-reference-20261009/problems_triage.py` 的口径。
- 对这两个文件记 sha256 与时间到 `PREREG.sha256`。之后不得修改；确需修改，新开文件写明原因，旧文件保留。

## 2. 两臂

**现行臂**：用当前仓库代码（HEAD）的六轴实现，在同样的上游输入上跑（需求轴的期望 E、分析轴的案卷与选材、数据需求投影都复用本批已记录的结果，只重跑六轴）。可参考 `report/expectations-20261006/expectations-v2-axes-live12-slim-20261008/run.py` 的回放方式（它把网关地址指到各实例网关、复用已记录上游）。若某个 case 的上游无法复原，写明原因并跳过，不要用别的数据顶替。

**新方案臂**：按 `spec/draft/process-axes-expected-actual.md` 实现成实验脚本：
- 每个 case × 每个轴两次调用。第一次只给第 3 节表里该轴「看得到」的输入，写 `expected`（含 about、subcapability、statement、basis、needs_external）并冻结（存原文与哈希）；第二次给完整案卷，写 `actual`、`unexpected`、`problems`、`reason`、`scope_note`。
- **规划轴第一次调用不得给实际调用列表**。模型轴按每次模型调用单独请求。每个 case、每个轴做泄漏检查（该轴输出侧的原文不得出现在第一次调用的材料里），结果存档。
- 程序侧：`needs_external=是` 的条目把结论锁成「无法核」；传递检查（参数原样执行、工具返回原样进入下一次模型输入、交付是否保留模型草稿的事实与缺口、执行余量提示是否随用量更新）由程序逐字比对，作为程序判定条目并入。
- 可参考 `report/process-axes-reference-20261009/blind_pass.py` 的输入切片与两阶段写法，但要按草稿的新形状改（没有推出/守恒/外部真值三分类）。
- **保存模型回复的原始文本**，不要只存解析后的对象。

**每一臂跑两遍**（独立两次），用于一致性。

## 3. 评估

1. 已知问题召回：每一臂、每一遍，找到 `known_issues.md` 里的几条。
2. 误报率：把两臂四遍的全部问题**去掉来源标记、打乱顺序**，写成 `blind_problems.jsonl`，按 `triage_rules.md` 归类。归类可以用同一模型做一次独立调用，再由你抽查不少于 30% 并报告抽查与模型归类的一致率。归类完成后再还原来源统计。
3. 一致性：同一臂两遍之间，问题层面的重合（同一个已知问题或同一现象算重合，口径写清）。
4. 成本：两臂六轴部分的输入、输出 token 与累计耗时（模型的输出 token 是否含推理，查清并注明）。
5. 问题是否具体到「哪一步、现象、预期、实际、引用」；引用的记录 id 在案卷中是否真实存在（程序核）。

判优门槛（**用户尚未确认，仅作参考，报告里只给数字与对照，不要替用户下结论**）：召回不低于现行；误报率不高于 15%；成本不高于现行 1.2 倍。

## 4. 产出

- `RESULT.md`：做了什么、用的模型与核实方式、每个指标的数字（按臂、按遍、按 case）、偏离本任务书的地方与原因、已知局限。数字都要能从本目录文件重算。
- `PROGRESS.log`：每完成一个阶段追加一行（时间、阶段、状态）。主会话会读这个文件跟进。
- 全部脚本、原始回复、冻结清单、归类结果都留在本目录。

遇到需要用户拍板的事（例如两边都无法用同一模型、现行臂上游无法复原超过一半 case），停下来写进 `RESULT.md` 的「待决」一节，不要自行改变实验设计。
