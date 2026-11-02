# expectations 实施与验证记录

按 `spec/alg/expectations.md` 实施。需求轴是内部分析轴，输入只含需求侧材料；六个过程轴消费冻结的期望集。主轴仍使用原来的期望生成与裁决方式。

## 改了什么

1. **独立需求输入与需求轴**：新增 `sample.requirements`、`business_trace/expectation_material.py` 和 `eval_axes/adapters/expectations.py`。从用户原文、历史对话、单独采集的定义、工具声明和 API 输出格式投影材料；不传当前响应、工具返回、最终交付或 caller-stated capability。运行时 system 消息不直接进入需求轴；未独立登记模板时列为缺料。Agno 历史仅用于解析本轮指代，不能独立产期望。定义保留“采集时观察，未验证为当次版本”限定。
2. **结构约束**：E 只含标识、出处、关于、陈述、条件、歧义组。校验非空、唯一 ID、出处属于输入、历史不得单独产期望、歧义组至少两条；不能在一条期望里合并 want 与 commitment。`complete/partial` 由输入材料缺失清单决定，不表示 E 内容正确或完整。格式错误最多一次 reprompt；失败阻断消费者。
3. **六轴消费投影**：新增 `process_loop/expectation_projection.py`。自然语言需求与工具能力的对应、承诺所属部件由独立语义映射调用完成；这属于消费者，不回写 E。程序按映射展开应发生单位。两个映射阶段（需求提取、六轴 join）分别留痕；额外调用计入使用量。
4. **应发生单位与判准**：六轴依赖 `expectations`；普通案卷、共享 dossier ToolLoop 和 transcript 路径均接入。普通案卷串行顺序先产生规划/工具问题，再判依赖它们的知识单位。提交删掉自由 `expected`，改为 `expectation_ids` 和逐项核对；展示用 expected 由程序根据冻结 E 生成。应发生单位必须覆盖，且须对接实际事件或明确缺证/上游无效，不能用“未发生”消掉要求。指代、约束、歧义等不适用子能力保留各自边界。取数能力未定时为缺判准。
5. **汇总**：同一实际事件满足多条期望时，按义务与实际事件合并计数，原始逐项检查保存在 `checks`。上游问题引用仍按各检查验证，不因合并丢失。问题记录保留 E 引用及程序派生的预期。
6. **证据与 JSON**：参数成为独立 `.params` 原文记录，精确复用通过 canonical_ref 加入后续调用输入成员。模型轴逐次覆盖 response；不得把其他调用的规则当作当次输入。API 声明 JSON 格式且完整 content 不能解析时，禁止提交 output_contract=pass。这个检查只是阻止错误通过，不替模型伪造 fail 或问题记录。最终实收不可见时，问题 impact 不能宣称 yes/no。
7. **上下文与展示**：共享 transcript 会话中的 E 及出处只放一份；初始 briefing 列出完整 pending；无固定事件的义务使用显式 transcript 占位，避免空列表被误解为无需回答。工具 schema 限定本轴 obligation_id，并解释 required link 与 matched link 的区别。需求轴按 analysis 角色排除于业务分布和聚类，原始报告及问题出处仍可查看。主轴不把需求轴混入六轴结果。
8. **删除旧路径**：分析轴的 `expected_exercises` 及其生成/校验已删除，没有保留双轨兼容。
9. **完成时序**：ToolLoop 新增默认关闭的批尾完成条件；只有本实例六轴全部 accepted 才提前结束模型请求段，随后仍运行完成检查、结果提取和跨轴问题校验。消除结果交齐后额外结束回复跨越预算的失败。

## 本地验证

- 相关回归及通用 ToolLoop：406 passed、1 skipped，91.50 秒；见 tests.log。跳过项为既有非流式总时长看门狗条件。最后的通用字段含义提示词补充另有 post-review-tests.log。
- 八组方案样例标准 E：`tests/fixtures/expectations_gold.json`，覆盖并列需求、条件、输出形式、设计约定、指代、省略、互斥读法、规则模板。
- 新增专项测试：当前运行产出隔离、历史边界、E 不随消费者集合改变、格式重试、非法出处、工具能力缺失、应发生单位覆盖、事件合并、跨轮误接、参数继承、整段 JSON、影响未知、μ 实际输入验证、需求轴失败阻断、内部分析角色。
- 合成“该查却没查”样例通过真实 ToolLoop 框架和脚本模型：规划问题被记录；知识轴引用该上游问题，得到 untested。它证明接线、覆盖和汇总机制，不证明真实模型的判断质量。

## B 真实重判

仅重判此前授权的 B 冻结样本；不执行业务系统。原 trace SHA-256：`69e8a0513dec857fab62e3c5db92709782cc9e8ea7ccd8faec664de314ef3831`。沿用此前 low 实验的 judge 推理参数，六轴会话仍为 1200 秒、40 次工具调用。需求轴和语义 join 是新增阶段，时间与调用额外计入。

### 首轮 B-low

需求轴产出 12 条 E，状态 partial（独立系统模板缺失）。模型实际命中 fallback1 / qwen3.8-flash。首轮提取把“性别、出生年月”合为总项，并制造了“基本资料宽/窄范围”的歧义组；这一粒度不作为合格基线。

真实模型在中途提交中识别出 `mu-final-not-schema-json`，说明旧漏判在该次提交中被识别；但六轴会话经历多轮格式修复和证据补读，约 21 分钟超出合作式截止时间（在模型调用返回后检查）。整案六轴均 failed，不发布中途已接受部分为有效六轴结果。总耗时约 22 分 45 秒，含需求轴与投影阶段。原始上下文、错误回执、问题记录均保留在 `B-low/`。

该轮揭示了上下文工程问题：pending 未完整显式交付、六轴重复装入 E/原文、matched_link_id 使用规则不够明确。已补齐待判表、共享 E、细化 schema 说明。提取提示词增加并列拆分、正常宽泛表述不等于互斥歧义、工具能力陈述不能漏掉的通用规则。

### 第二轮 B-r2-low

需求轴将用户要求拆为性别、出生年月两条，没有虚构歧义组；同时从完整工具目录和格式声明提取 118 条承诺。材料 partial 的含义不变。该版本逐工具提供准确出处。第二轮运行开始时的实现哈希单独保存在 `B-r2-low/implementation-at-replay.json`；运行期间完成的 Agno 历史、分析角色展示、普通案卷顺序/输入边界、待判占位及完成时序修正，均有离线测试，未混入正在运行的解释器。第二轮真实请求仍因额外结束回复跨过会话截止而整案 failed，总耗时 1459.60 秒；原始结果未覆盖。冻结模型提交经最终代码离线回放，33 个步骤便可提取完整六轴结果，且最终非 JSON 问题保留；这不是再次外发重判。

人工复核发现 birthday 字段口径警告仍被模型忽略，μ 和知识轴存在语义误通过；中间工具响应的 JSON 适用范围也需另审。已补充通用字段限定提示词，尚无补充后真实重判证明。实施已接通，**语义验收尚未通过**。详见 `semantic-review.md`，不要以结构 accepted 或离线回放成功代替语义正确。

## 验收边界与可复核点

- 模型 E 的语义完整性不能由 schema 证明；八组标准样例尚未逐一做真实模型语义评审。B 第二轮也不能因字段合法或需求拆分改善就自动判全部 120 条 E 正确。
- 这次整体实现同时涉及 E、参数证据、待判覆盖与上下文整理。与旧 B-r3-low 的比较保持同 trace、推理参数和六轴预算，但不是只开关 E 的单变量消融；不能据此量化 E 单独贡献。
- 原始 P1-A/R132/C48 未新增外发重判。本地合成缺查询样例替代的是程序接线验证，不能代替该真实样本的语义验收。
- 模板只有运行时拼接实例时仍会 partial。登记模板的接入点已支持，但没有修改被测业务代码去补造模板或假定采集时定义就是当次版本。
- 所有需求/方案 Markdown 在实施开始保存哈希，应用脚本每次核对；最终校验另存 `protected-documents.json`。没有修改 `spec/alg/expectations.md`、`demand/process_axes.md`、相关主方案或其他保护文档。

## 复核入口

- 原始实现：`impl/projects/llm_probe/business_trace/expectation_material.py`、`eval_axes/adapters/expectations.py`、`process_loop/expectation_projection.py`。
- 需求轴实际输入：各次重判目录 `requirements.json`；实际模型上下文在 `evaluator-context/`，阶段为 `llm_probe_expectations`。
- 冻结 E：各次重判 `expectations.json`，或需求轴上下文的原始响应。
- 消费者 join：`llm_probe_expectations_process_projection` 上下文。
- 六轴原始结果与失败回执：`result.json`。
- 可独立审阅的 E 与出处：`expectations-review.html`。
- 独立人工意见及待验收项：`semantic-review.md`。
- 原始模型提交的确定性框架回放：`B-r2-recorded-replay/result.json`（不新增外部模型调用）。

## 8021 实测后的协议修复

8021 的 Agno 普通案卷实测暴露了必填空字符串与生成 schema 的 minLength=1 矛盾。现已修正 matched_link_id、ambiguity_group 的字段声明及消费者说明；不放宽必填、不补默认值。普通案卷、共享 dossier、transcript 三条路径共用修复后的 dataclass schema。

447 项扩大回归通过、1 项跳过；另外两项通用联合类型/Authority schema 既有失败在未修改 HEAD 上复现，独立保留并从扩大回归中 deselect。一次真实 primary/gemini 请求复用当前 B/Agno 原始上下文轴输入，生成 6 组合法空 matched_link_id，协议检查通过。当前 8021 运行进程未重启，不会热加载修复。详细来源、改动和验证见 `8021-schema-fix/review.md`，原始生成及日志同目录。
