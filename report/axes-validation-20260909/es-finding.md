# ES 显式字段检索实测

状态：confirmed；影响：指定 keyword 字段的子串查询会漏掉库中确实存在的词，并返回“知识库里没有”的提示。默认检索路径在当前测试库表现正常。

真实服务：既有 `clause_kb`，13 条文档。整个验证只读，没有创建或修改索引。

| 查询 | fields | 实际返回片段数 |
|---|---|---:|
| 康宁 | 未指定 | 5 |
| 康宁 | product | 0 |
| 康宁终身险 | product | 5 |
| 犹豫 | clause_title | 2 |
| 犹豫 | clause_title.kw | 0 |
| 犹豫期 | clause_title.kw | 2 |

原始结果、回读内容、完整 13 条 corpus 和 receipts 位于 `es-field-probes.json`。以上数字是工具片段数，不统一等于文档数。

复现：从项目根执行 `PYTHONPATH=. /Users/xiaozijian/miniconda3/envs/agno/bin/python report/axes-validation-20260909/probe_es.py`。需要访问当前配置的 ES 服务。

定位：`impl/projects/llm_probe/eval_axes/sources/es_tools.py:103` 将显式字段全部放入 `text_fields`，第 106 行只在未指定字段时收集 keyword，第 110 行对显式 keyword 使用 phrase 查询。因此显式 `product` 没有走默认情况下的 wildcard 子串语义。这不是文档不存在：完整名称查询和原文回读都有命中。

工具参数校验允许 text/keyword 字段，而工具总体说明声明子串匹配；当前两者不一致。若模型使用字段限制后相信零命中说明，有将可核验事实错判为 unverifiable 的风险。该下游误判是风险，本次已确认的直接事实是检索漏命中。

默认路径的改善也有证据：`康宁 现金价值` 仅 matched 康宁；单查现金价值零命中；产品名只在 keyword 的文档仍给出可回读正文。没有把默认路径的正面结果推广到其他分析器、大索引或纯 keyword 索引。
