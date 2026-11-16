# 数据集 A 120 题的主轴 gold（120 条已标完）

对象：8036 上数据集 A 120 题那批，冻结下来的业务回答（`frozen-120.json`）。gold 绑定的是这一次冻结的回答，不能换一批回答来比。
标注范围：只标主轴三态（fulfilled / not_fulfilled / not_evaluable），格式同 `report/eval-main-axis/gold.json`。

## 当前进度

| 项 | 状态 |
|---|---|
| `gold.json` | **120 条全部标完**：兑现 64、没兑现 56、说不清 0 |
| 各类（兑现/没兑现） | A 17/3，B 8/12，C 9/11，D 13/7，E 8/12，F 9/11 |
| 抽查 | 用户 2026-11-08 决定不做全量抽查，以后使用时有疑问再回头改 |
| 待复核（`review: true`） | A09 B05 B08 C12 E05 F12，共 6 条：起草员拿不准，又没有你已定的口径可套，先保留起草结果 |
| 评测器对照（from-trace 复评、oracle/null） | 不在这次范围，以后用 gold 比效果时再做 |

`accept` 里有两个标签的 5 条（B08 C12 D06 D10 F12）：两种判法都算对。

## gold 怎么来的

- 起草：Opus 5.5，每条一个独立起草员。只看冻结的回答、业务 trace、`fulfilled.md` 和 `RULES.md`，并用只读工具独立查数据源核对（`q.py`，7 个只读工具，结果缓存在 `facts-cache/`）。没有看评测器的任何结论。
- 业务 trace 只当参考，不当真值；trace 只覆盖多轮题的第 1 轮，后几轮靠独立查询。
- 起草员标了拿不准的：前 42 条里的 8 条（A04 B01 B18 D10 E16 E18 E19 F10）由用户逐条定过；后 78 条里同类的（D02 D06 D03 A13 A15）按这些已定口径统一处理，记在 `decided` 字段；剩下 6 条没有现成口径，标 `review: true`。其余条目没有人工抽查，是模型起草结果。
- 口径见 `RULES.md`。其中规则 1、4、7 是在 `fulfilled.md` 之外新增的，评测器与之不一致时属于有用的差异，不一定是评测器错。

## 已知局限

- 120 条的噪声约 ±9 个百分点（1/√120，单次）；要看出几个点的差别需要多跑几次。
- 120 条里没有"说不清"。放开 `policy_detail` / `customer_detail` 后，明细都能查到，所以 gold 里没有 not_evaluable 这一类，不能用这份 gold 检验评测器会不会把该判"说不清"的判对。
- 没兑现的 56 条里，约一半是业务如实说知识库没收录（承载轴问题，兑现轴照判没兑现）；E13/E14/E15 是业务整个降级、什么都没给。
- gold 的真值来自测试库当时的数据，数据变了 gold 要重核。
- `policy_search` 传 `customer_id` 有时不过滤、每页只返回 5 条，起草员已绕过；以后复核时注意。

## 文件

`gold.json` 最终 gold（120 条）；`gold-sample42-draft.json` 前 42 条起草稿；`drafts/` 每条起草员原始输出；`cases/` 120 条材料（对话+回答+trace）；`DRAFT-PROMPT.md` 起草提示；`rest78.json` 后 78 条名单；`inputs-sample42.md` 输入清单；`RULES.md` 口径；`q.py` 只读查询；`dump_trace.py` 取业务 trace；`review-sample.md` 备好但未使用的抽查材料；`pilot5/` 试跑。
