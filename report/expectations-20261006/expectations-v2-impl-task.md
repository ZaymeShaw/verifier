# 实施任务：需求轴 v2 与六轴判准来源

你负责把已定稿的方案落到代码。方案已经和用户逐条对齐过，**不要改需求文档和方案文档**；发现方案无法实现或自相矛盾，记进实施文档并在最终报告里说明，不要自己改口径。

## 必读（按顺序）

1. `AGENTS.md`（项目规则：不留兼容层、最简实现、先跑通最小端到端、优先复用已有库与代码）
2. `demand/expectations.md`：需求＝用户和下游对业务系统的期望；系统设计规则不是需求
3. `spec/alg/expectations.md`（v2 定稿）：全文，尤其 §2、§4–§7
4. `spec/alg/process-axes.md`：§2.2（应发生行使的四问）、§3.2、§3.4（判准来源）、§12 D9–D11
5. `spec/implementation/process-axes.md`：§4.2、§4.3（单位输出格式现状）、§7.2、§7.4、§7.5（改动接缝）、§7.9
6. `report/expectations-20261006/process-axes-output-abstraction-20261007.md`（模型只写判断、程序负责单位与引用的输出抽象）

## 现状速记

- 需求轴 `impl/projects/llm_probe/eval_axes/adapters/expectations.py` 与 `business_trace/expectation_material.py` 仍从用户原话＋系统提示词＋工具定义提取期望（一个冻结样本产出 160+ 条，其中用户侧 4 条）。
- `process_loop/expectation_projection.py`：`ContractBinding/Join.contracts` 把每条承诺映射到一个子能力；`attach_criteria` 据此挂判准；`data_needs.tool_expectation_ids` 引用承诺期望；`required_units` 展开应发生单位；`bind_results` 生成问题 `expected` 时只复制陈述（丢条件）。
- 六轴有三条评测入口：案卷批次 `eval_axes/adapters/process_common.run_process_axis`（已用新输出格式 `process_output.AxisJudgment`）、Agno ToolLoop `process_loop/evaluation.py`、llmtracing ToolLoop `process_loop/llmtracing.py`（后两者仍用旧 `ProcessAssessment`）。
- 结构化输出：保持现有"提示词写结构＋事后严格校验＋纠错轮"，**不启用 response_format**（用户决定）。

## 要做的事（先把案卷批次入口端到端跑通，再扩到其余入口）

1. **需求轴只取需求侧材料**（方案 §2）：y_need＝用户原话（历史只解指代）＋场景判准／描述。不再投影系统提示词、工具定义、输出格式声明、编排模板；删除相应缺料原因。`capability` 在维护者拆分确认前不进 y_need，verdict 记 partial 并写明"capability 未拆分"（方案 §2.1、§2.3）。下游要求只是占位：可以让场景配置形状校验接受 `downstream: list[str]`，但需求轴暂不读取，也不参与 verdict。需求轴提示词与校验同步改为只提取用户侧需求。
2. **删除全局承诺映射**（方案 §7、D9）：删掉 `ContractBinding`、`contracts`、按承诺挂判准的路径及其测试；不保留兼容层。
3. **应发生行使改为四问**（方案 §6.2、六轴协议 §2.2、D10）：
   - 投影阶段（不看运行）只回答①是否需要外部数据、②有哪些候选办法（引用工具说明原文位置，不再引用承诺期望 ID）；需求仍引用 E 的 ID。
   - ③当时是否仍必须行动（已满足／必须做／说不清）与④实际是否发生，需要看运行，放在六轴判定里：已满足须给证据且不报问题；必须做按应发生单位判，不能用 not_applicable；说不清落缺证并写明缺什么。
   - 应发生未发生时不预设规划责任，按证据定位，定位不了落缺证＋归因未定位并列候选轴（六轴协议 §3.2）。
4. **判准来源改为三种**（方案 §6.3、六轴协议 §3.4）：通用义务、E 的适用条目、设计规则原文。
   - 设计规则引用＝原文位置＋原样摘录，可关联多处（条件、例外在别处时）；程序核对每处摘录逐字出现在声明的位置，不补写条件。
   - 适用范围按轴：模型轴只用该次调用实际输入里的规则；上下文轴比较应交付端与实收端；工具／规划用适用当次执行的规则。采集时定义未核实为当次版本时只能作参考，不能单独定违约或漏传。
   - source=trace/case 义务既无适用需求也无设计规则引用时落缺判准。
5. **原文块覆盖**（方案 §6.4）：程序为每个待判单位预先列出候选原文块（按真实结构切：每条消息、每个工具定义、每个格式字段），随材料交付；判定者逐块标注 已核对／不适用及原因／无法确定，在同一次调用内完成；程序校验清单完整、逐块有标注。不得新增模型调用。
6. **结果传递**（方案 §6.5、D11）：单位保存每条判准的引用身份、结论、事实；问题记录的"预期"由程序从引用原样组成，带条件与关联原文。
7. **输出格式**：沿用"模型只写判断、程序负责单位／判准编号／端点／汇总"的抽象；新增的设计规则引用与块标注也按此原则设计（模型写短编号或位置＋摘录，不抄长编号）。把 llmtracing 与 Agno ToolLoop 两条入口也迁到同一输出格式与判准来源，删除旧 `ProcessAssessment` 路径，三条入口共用同一套校验。
8. **主判改读同一份 E**（方案 §5）：只在 llm_probe 项目路径内实现，不能改变其他项目主判的行为与 `JudgeResult` 公共语义。如果做不到不影响其他项目，就先不改，在实施文档记为待定并说明原因。

## 验证

- 离线回归：用 `report/expectations-20261006/` 下已有的离线 pytest 守护方式（屏蔽业务与付费端口）跑六轴、需求轴、主判相关测试；再跑全仓 `tests`。全仓已知与本任务无关的失败有 14 项（deerflow 归因、schema_validator、config_contract、tool_loop_lab、test_llm_probe 缺 case fixture 等），不要为它们改代码，但要确认没有新增失败。
- 每条改动补正反例测试；尤其：需求轴不再出现设计侧条目；挑漏规则时块标注能暴露；条件保留到问题记录；已满足／必须做／说不清三种必要性结论；三条入口用同一校验。
- 真实验证：参照 `report/expectations-20261006/unit-format-full-live-20261007/run_once.py`，新建运行目录（如 `report/expectations-20261006/expectations-v2-full-live-<日期>/`）对同一冻结样本完整重跑一次（需求轴→分析→六轴→主判）。本地网关端口 4008–4010。报告：需求轴条数与耗时、六轴通过情况、调用数、重试数、原文非法 JSON 次数、输出字符、主判结论，并和 `unit-format-six-axes-replay3-20261007`（六轴 6/6、13 次调用、2 次重试、3.9 万字符）对比。真实运行失败要如实记录，不能把失败改写成成功。

## 约束

- 不改 `demand/`、`spec/alg/`；不提交 git；不动与本任务无关的已修改文件（工作区里有大量他人的未提交改动，例如 `.agents/` 删除）。
- 不留兼容层、不加 fallback；结构问题不能靠放松校验或程序替模型补值来通过。
- 每完成一步，按 `spec/implementation/process-axes.md` §6 的维护规则更新该文档（改动位置、状态、验证证据、剩余问题），区分"已实现"和"已验证"。
- 最后在 `report/expectations-20261006/expectations-v2-impl-<日期>/README.md` 写最终报告：做了什么、删了什么、验证结果（含失败）、与方案不一致或未完成的地方。
