# B 冻结样本真实重判与复核

B 真实重判和留档已完成，但业务语义验收未通过。low 实验六轴运行成功；程序接受提交不等于判断准确。

## 运行与对照

- B/：默认 high，约 9 分 32 秒完成。复核发现传递证据方向绕过和重复计数；保留原结果，不作为验收结果。
- B-r2/：修复后的 high，15 次模型请求，约 20 分 27 秒触发实例预算。六轴全部 failed，无 verdict/output，未发布中途已接受的部分结论。
- B-r3-low/：最终证据检查下的独立 low 实验，14 次模型请求，约 8 分 27 秒完成六轴。仅覆盖本次进程 judge 推理参数，未修改项目配置文件；20 分钟预算保持不变。

旧基线用 gemini-3.8-flash-medium（same_model）；三轮新运行均命中获授权的阿里云 fallback1，模型 qwen3.8-flash。模型及第三轮推理参数与基线不同，不能将 verdict 变化直接归因于协议修改。

| 轴 | 旧基线 | 首轮 high（含漏洞，不采纳） | 修复后 low 实验 |
|---|---|---|---|
| intent_understanding | sound | sound | sound |
| planning_routing | sound | not_evaluable | sound |
| tool_execution | sound | problematic | sound |
| knowledge_data | sound | not_evaluable | not_evaluable |
| model_capability | problematic | problematic | problematic |
| context_memory | not_evaluable | not_evaluable | not_evaluable |

## 原文复核：尚不能正式验收

1. **生日口径过度断言有依据归模型。** t1.c3.m6 明确要求先确认 birthday 年份口径，不能直接认定出生日期。该限制已进入 c3 实际输入，t1.c3.response 却断言已确认出生年月、未在 gaps 披露口径缺口。low 实验分别生成忠实整合与不编造两条问题，引用可对应原文。
2. **JSON 契约漏判，阻断语义验收。** t1.c1.system 要求输出 JSON，t1.c3 沿用 strict AgentOutput schema；t1.c3.response 实际全文为正文加 Markdown JSON 围栏。旧基线及前两轮模型提交识别过该问题，low 实验却将 output_contract @ t1.c3.response 判为 pass。契约和全文均已可见，这是评测漏判，不是业务缺证。
3. **工具字段投影归因不稳定。** t1.c2.m4 返回客户本人 clientSex 的值，却在 execution.gaps 将“性别”对应到 familyInfo.familyClientSex 并声明缺失。首轮归工具问题，第二轮中途提交及 low 实验均判工具正常。载荷不一致可查，具体产生层和工具能力归因还需复核；不采纳为稳定工具缺陷。
4. **最终交付影响未验证。** t1.final=null，桥接/结果组装不可见。low 两条模型问题的 impact=yes 是模型声明，不能当作用户最终实收受损的已验证事实；复核意见为影响未知。
5. **期望倒推来源未通过真实验收。** low 的规划、知识单位全部为 runtime_recall，无 expectation_deduction。共享 transcript 路径提示模型提交该来源，尚未强制检查期望行覆盖；不能据此宣称“该做没做”覆盖已验收。标准案卷路径已有 expected_exercises 支持及本地回归，真实 transcript 路径仍需补强。

后续重点是输出契约漏判、期望倒推覆盖、归因与影响校准，不以提高 sound 比例为目标。未改写原始模型判断或隐藏失败。

## 已落地修复与验证

- arrives_intact 正面判断要求独立模型 response → 后续请求中的 assistant 消息。工具实收消息放在任一端、call 元数据当到达正文，均不能证明无损。
- 同一传递两端不能用多个位置重复计数；检查收窄到传递义务，两个不同子问题可以共用同一段数据证据。
- 修复浏览器回归等待：编辑器不存在时不能判为就绪。
- 20 个相关模块：330 passed、1 个浏览器等待竞态失败；修正后该模块单独复验 1 passed。
- 最终证据检查修正：41 passed，含不同子问题共享证据的新增回归。
- low 真实输出按完整读取回执重验引用、方向、组成和问题 ID：通过。
- low 的真实 case 页面经 Chrome 检查：六轴、组成、两条原子问题与证据展开通过，无 JS 错误。
- B-r3-low/problem-material.json：2 个问题成员，保留 ID、归因、影响及引用；未再次调用聚类模型。

## 产物与边界

各轮 comparison.html / comparison.json 并排保存旧、新原始判断。case.html 为本地问题/证据下钻；超时轮 case.html 只展示运行失败，问题材料为空。

各轮 evaluator-context 保存实际模型材料、响应和端点记录；manifest 保存哈希。首轮 10 条，超时轮 15 条，low 轮 14 条。B-r3-low/replay-harness.py 保存本次 low 覆盖参数的复现方式。

两份需求/方案文档 SHA-256 与实施前一致，未修改。本次只重判获授权 B，A、C、D、E 未重判，未调用业务系统。
