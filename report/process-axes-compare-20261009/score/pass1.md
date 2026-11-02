# 指标（pass1）

## 现行六轴（current）

- 轴数 48，管道失败 3，书账不符 0，泄漏 0
- 实际应答模型：gemini-3.8-flash-medium；请求数 58（每轴 1.29）
- 问题条目 31（已分类 31）
- 命中已知项 21：hard 14/22（召回 0.636）、soft 2/7（召回 0.286）
- 清单外真问题 2；误报 8（拆分 0、过度断言 3、被反驳 1）；误报率 0.258
- 无法判断 0；带引用 1.0，带现象描述 1.0
- 引用核验（triage_rules §6/F1）：可解析 103/105（0.981），内部定位符 0，无法解析 2，条目有可解析引用 31/31
- 未召回 hard：A01-3, AP-3, B01-2, CP-3, D01-3, PL-1, REN-2, REN-3
- 归因（按已知项主轴）：`{"context_memory": {"total": 7, "attributed": 7}, "model_capability": {"total": 4, "attributed": 4}, "planning_routing": {"total": 5, "attributed": 3}, "knowledge_data": {"total": 1, "attributed": 0}, "intent_understanding": {"total": 2, "attributed": 2}, "tool_execution": {"total": 2, "attributed": 1}}`
- 成本：{"calls": 64, "prompt_tokens": 2395212, "completion_tokens": 101387, "elapsed_seconds": 4772.2}

## 本应清单/实际清单（new）

- 轴数 48，管道失败 3，书账不符 0，泄漏 0
- 实际应答模型：gemini-3.8-flash-medium；请求数 122（每轴 2.71）
- 问题条目 55（已分类 55）
- 命中已知项 28：hard 14/22（召回 0.636）、soft 1/7（召回 0.143）
- 清单外真问题 9；误报 18（拆分 0、过度断言 3、被反驳 5）；误报率 0.327
- 无法判断 0；带引用 1.0，带现象描述 1.0
- 引用核验（triage_rules §6/F1）：可解析 138/227（0.608），内部定位符 63，无法解析 26，条目有可解析引用 44/55
- 未召回 hard：A01-2, AN-1, AP-2, B01-1, B01-2, B01-3, D01-3, PL-1
- 归因（按已知项主轴）：`{"context_memory": {"total": 12, "attributed": 12}, "planning_routing": {"total": 8, "attributed": 5}, "intent_understanding": {"total": 4, "attributed": 4}, "model_capability": {"total": 2, "attributed": 2}, "tool_execution": {"total": 2, "attributed": 0}}`
- 成本：{"calls": 135, "prompt_tokens": 3638913, "completion_tokens": 119047, "elapsed_seconds": 1531.776}
