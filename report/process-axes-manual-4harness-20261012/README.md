# 四套 Agent Harness 过程评测（2026-10-12 批次）

Claude Code、Pi、旧 Insurance（insurance-qa-agent）、新 Insurance harness（insurance-agent-harness）四套系统，用同一个模型、同一份保险业务题集（120 题、174 个用户轮次）作答。按 `demand/process_axes.md` 逐环检查查数、调工具、组织答案、交付给用户的过程。

| 文档 | 内容 |
|---|---|
| [harness-issues.md](harness-issues.md) | **最终版**：修正口径后的 120 题总表；后端接口问题（标明接口）；四家各自的问题分层、例子和修法；口径修正记录 |
| [full-120.md](full-120.md) | 120 题全量总表：过程六轴、最终回答、时间效率、token 成本；共性问题与各家特有问题；标注质量说明。标注数据在 `annotations/` |
| [harness-comparison.md](harness-comparison.md) | 四家对比：一页结论、用户最终拿到的答案、按流程分层的问题、各家发现、效率与 token、评测配置问题、和 10-08 批次的对比、建议、逐题判定 |

## 数据与复现

- 原始 trace：`package/llmtracing/eval_runs/share_20261012.zip`
- `scripts/extract.py <llm_trace.html> <out.json>`：抽出内嵌数据
- `scripts/digest.py <data dir> <out dir> [limit]`：每题过程摘要
- `scripts/scan.py <data dir> <out json>`：全量统计，结果在 `scan_signals.json`
- `scripts/paging.py`、`scripts/delivery.py`、`scripts/monologue.py <data dir>`：分页不全、交付形态、正文混入思考

脚本只读原始数据，Python 加 `-I` 运行。
