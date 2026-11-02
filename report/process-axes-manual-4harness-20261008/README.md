# 四套 Agent Harness 过程评测（2026-10-08 批次）

Claude Code、Pi、OpenCode、Insurance QA 四套系统，用同一个模型、同一份保险业务题集（120 题、174 个用户轮次）作答。我们逐步检查了每套系统查数、调工具、组织答案、交付给用户的过程。

## 先读哪份

| 文档 | 给谁看 | 内容 |
|---|---|---|
| [harness-comparison.md](harness-comparison.md) | 所有 harness 的开发 | 四家对等对比：各自做得好的与主要问题、共性结论、工具层共同缺陷、评测方法、逐题判定表 |
| [insurance-findings.md](insurance-findings.md) | Insurance QA 开发 | Insurance 的问题清单（按影响排序），每条附证据、代码位置和修复建议 |

两份文档的评测方法和数据相同，结论一致。只关心 Insurance，可以直接读第二份。

## 数据与复现

- 原始 trace：`package/llmtracing/eval_runs/comparison_20261008/results/new-run/`
- `scripts/digest.py`：生成每题的过程摘要（用户轮、工具调用与返回、终答）
- `scripts/scan.py`：全量 480 条的程序统计，结果在 `scan_signals.json`
- `scripts/pair_returns.py`：对比同参数工具调用在 MCP 和 Insurance 两侧的返回

脚本只读原始数据，用法写在各脚本开头。
