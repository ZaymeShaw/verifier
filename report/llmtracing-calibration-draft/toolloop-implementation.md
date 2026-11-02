# llmtracing ToolLoop：本地实施与隔离验收

## 本批范围

只替换 llmtracing 的六轴过程执行。主裁决仍走原入口；本批不宣称解决主轴自由文本中的 UI/内部根因推断。没有真实模型或业务调用，没有重启共享服务、修改业务配置、提交代码。

路径：`eval_axes.build_report` → 仅 llmtracing → `llmtracing_report.build_loop_results` → 确定性分析 → 单个六轴 ToolLoop → 现有 AxisResult 报告 → 原主裁决。

- provider 仍只负责证据。ToolLoop 核心保持业务无关。
- 整案共享一次 loop；单轴 API 委托同一实例实现但只启用该轴。
- 删除 transcript_axes 内旧 complete_json/一次重试/salvage，不保留自动回退。
- 六轴定义、前端/报告结构不变；loop 未完成整次过程评判 failed，不伪造业务缺证结论。

## 文件

新增：
- `impl/projects/llm_probe/business_trace/providers/llmtracing_evidence.py`
- `impl/projects/llm_probe/process_loop/llmtracing.py`
- `impl/projects/llm_probe/process_loop/llmtracing_report.py`
- `tests/test_llmtracing_tool_loop.py`

更新：
- `llmtracing_transcript.py`：输入成员、证据来源、别名原文关系；final 脱敏。
- `transcript_axes.py`：保留确定性分析/委托/主轴材料，删除旧执行器。
- `eval_axes/__init__.py`：唯一新增的共享分派点，非 llmtracing 不进入新 loop。
- 原 llmtracing 和证据边界测试：改测 ToolLoop 契约，不再要求旧 salvage。
- `spec/adapter/business-trace-llmtracing.md`：第6期。

未动：`core/tool_loop.py`、`core/llm_client.py`、`core/session.py`、`judge.py`、Agno reader/dossier/links、在建 Agno process_loop 的 Analysis/Evaluation/tools/入口。

## 已验证

- 工具请求不能证明工具产出无损；错误提交收到具体反馈，随后能接受有依据的缺证。
- 读取与提交在同批时没有先读回执；正文分页未完成、只读别名未读原文都不能冒充读全。
- μ 输入成员按实际请求继承；被替换的系统规则与被丢弃历史不能因为更早出现就被接受。
- 六轴全交才完成；提前结束被 RequireDone 拦回；预算失败无部分结果/无salvage。
- 正常引用可直接通过，无需额外调查；案例间回执和提交不共享。
- 项目契约进入模型输入，项目义务漏答会打回，不因共用六轴而丢失业务描述。
- 共享 complete_step 调用数只记一次；模型请求异常记录为执行失败，保留已执行工具轨迹。
- Agno/无 trace 场景不进入新 loop；llmtracing 采集失败在创建模型前阻断。
- 真实 LlmClient + 本地假 OpenAI 的流式工具协议闭环通过。

验证记录：
- 全量：1592 passed、11 failed、5 skipped，477.68秒；11项均为此前已记录的失败集合。
- 全量后追加项目契约覆盖并做微调，最新定向：49 passed，1.80秒。
- 新增 ToolLoop 测试18项；断言的是确定性机制，不是模型评判准确率。

## 已知边界

- Hook/提交校验只能保证已编码的来源与结构关系，不能证明全部自然语言判断正确。
- 现有 flattened 历史对话稿没有输入成员元数据时，不猜测补齐；从真实快照重新构建才有可靠成员信息。
- final 来源根据 raw_response 是否存在标记，不能识别有人伪造整份原始 trace；历史重放仍需真实来源核验。
- 主轴尚未接入提交反馈，先前重放发现的因果/影响越界仍须后续处理。
- 输入工具分页有明确回执；主轴仍使用原有有预算的渲染路线，长稿渲染硬上限问题不在本批修复范围。
- provider 报告有独立实现指纹；公共轴类型原有指纹仍引用 transcript 源码，所以 Agno 的实现版本元数据可能变化，不代表其执行切换。
- 墙钟在工具调用及模型步边界检查，单个进行中的请求仍依赖 LlmClient 的超时控制；不宣称可强制中断任意阻塞调用。

下一步：经用户批准后，用完整冻结 A/B trace 跑真实 ToolLoop；分别检查是否会利用反馈、正常行为误报、缺证与不适用边界、成本。不得以假模型脚本成功替代这一步。
