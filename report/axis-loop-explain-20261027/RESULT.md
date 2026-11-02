# 说明回合 + 核事实改写 验收（T7，2026-10-27，8036）

跑法：8036 `/api/batch_start`，verify-insurance-mcp / agno / langfuse 各 11 条，真调业务 18066，并发 4。全部跑完，0 条失败。逐条数据见 `runs.json`。
mcp 场景配知识 + 核事实；agno / langfuse 只配 trace（不核事实，靠过程六轴）。

## 主结论对 gold

gold（`report/eval-main-axis/gold.json`）是按 10-19/20 的旧回答标的，这次是新回答，对不上的逐条看了新回答。有 gold 的 28 条对上 25 条：

| case | 这次 | gold | 看新回答后 |
|---|---|---|---|
| mcp-bizno | 没做成 | 做成了 | **判对**：这次被测系统答"客户号 C92200000884 查不到"，原文 customer_detail 里有这个客户号，c1 有矛盾成立 |
| mcp-G01 | 没做成 | 做成了 | **判错**：回答"1089.1元。"，c2"单位是元"判有矛盾，依据是业务说明"金额不带单位、禁止自行补元"+ 数据 unit 为空。这是"回答该怎么写"的规定，不是"事情不是这样"的证据，违反 claims §3.6；同批 mcp-F01 同类说法判的是查不到，不一致 |
| langfuse-D16 | 不确定 | 做成了 | 证据不全：trace 里 4 次外层工具调用 observations 的入参、输出都是 missing（后端调用都在、都成功），工具执行 8 条无法核 → 两条期望判不了。属"trace 里缺"，不是判法错 |

没有 gold 的 5 条（三场景 fuyunping、agno/langfuse 查不到的保单）：fuyunping 三条做成了；查不到的保单 mcp 判做不了（知识里能证明没有这张单），agno / langfuse 判"没做成，能不能做没分清"（只配 trace，证明不了没有），属证据降级。

## refuted 逐条复核（只有 mcp 核事实）

| case | 说法 | 判 | 复核 |
|---|---|---|---|
| mcp-bizno | 寿险客户号 C92200000884 对应的客户不存在 | 有矛盾 | 对 |
| mcp-B02 | 平安安佑福重大疾病保险与（惠享版）定期重大疾病保险从产品系列看为同一款产品 | 有矛盾 | 对（业务说明：险种代码不同即不同产品） |
| mcp-G01 | 累计已交保费的单位是元 | 有矛盾 | **错**，见上 |

C08（10-27 要修的那条）三场景都做成了；mcp-C08 38 条说法 0 条有矛盾。

## 其他看到的

- 查不到：mcp-E01"险种代码是 1836"、"销售状态是在售"判查不到（object_absent），被测系统从自己的工具拿到了，取证层没搜到——与 C08 的 c42 同类，在取证层（search_knowledge），本次没改。
- 说明回合：每条 mcp 1 次（兑现），agno / langfuse 7 次（兑现 + 过程六轴）。轴 reason 能写出程序结论来由，例：langfuse-D16 工具执行"程序算出结论为 not_evaluable……因为四次外层工具调用在 trace 记录中缺失入参与输出"。
- 退回 35 次（agno 14、langfuse 21、mcp 0）：大多是过程轴引文不在所引记录里（引文现在每行都核），其次是兑现 implicit_correct 在没核事实时带了 claim_refs。必须独立查证判没达到的退回这批没出现。
- 被测系统自身问题：多条回答带"让我整理回答"一类旁白、英文草稿，过程轴模型能力据此判没达到，有依据。

## 成本

| 场景 | 条数 | 平均调用 | 平均评测耗时 s | 最长 s |
|---|---|---|---|---|
| mcp | 11 | 29.6 | 531 | 1010 |
| agno | 11 | 33.2 | 723 | 1322 |
| langfuse | 11 | 24.5 | 697 | 1253 |

token：结果里的 usage 只记了调用次数（llm_attempts），没有 token 数，本次报不了。
改前没有同批存档可比（8036 原 33 条结果在重新加载用例池时已被覆盖），所以调用、耗时没有前后对照。

## 逐条

| case | 主结论 | 调用 | 评测 s | 说法 / 有矛盾 / 查不到 | 说明 / 退回 |
|---|---|---|---|---|---|
| mcp-fuyunping-policies | 做成了 | 26 | 419 | 8 / 0 / 0 | 1 / 0 |
| mcp-bizno | 没做成 | 23 | 341 | 1 / 1 / 0 | 1 / 0 |
| mcp-smoke-policy-detail-renyanlin | 做成了 | 15 | 371 | 20 / 0 / 0 | 1 / 0 |
| mcp-smoke-neg-unknown-policy | 做不了 | 19 | 200 | 1 / 0 / 0 | 1 / 0 |
| mcp-main-A02-yuxinya-status | 做成了 | 23 | 539 | 21 / 0 / 3 | 1 / 0 |
| mcp-main-B02-policy-plus-waiting | 没做成 | 55 | 997 | 11 / 1 / 2 | 1 / 0 |
| mcp-main-C08-two-customers-parallel | 做成了 | 28 | 621 | 38 / 0 / 0 | 1 / 0 |
| mcp-main-D16-near-name-split | 做成了 | 22 | 350 | 18 / 0 / 0 | 1 / 0 |
| mcp-main-E01-ref-product-knowledge | 没做成 | 48 | 664 | 2 / 0 / 2 | 1 / 0 |
| mcp-main-F01-name-correction | 做不了 | 44 | 1010 | 28 / 0 / 6 | 1 / 0 |
| mcp-main-G01-short-answer | 没做成 | 23 | 325 | 2 / 1 / 0 | 1 / 0 |
| agno-fuyunping-policies | 做成了 | 26 | 467 | 0 / 0 / 0 | 7 / 2 |
| agno-bizno | 做成了 | 26 | 550 | 0 / 0 / 0 | 7 / 1 |
| agno-smoke-policy-detail-renyanlin | 做成了 | 25 | 523 | 0 / 0 / 0 | 7 / 0 |
| agno-smoke-neg-unknown-policy | 没做成 | 33 | 486 | 0 / 0 / 0 | 7 / 4 |
| agno-main-A02-yuxinya-status | 做成了 | 27 | 615 | 0 / 0 / 0 | 7 / 2 |
| agno-main-B02-policy-plus-waiting | 没做成 | 46 | 966 | 0 / 0 / 0 | 7 / 0 |
| agno-main-C08-two-customers-parallel | 做成了 | 36 | 802 | 0 / 0 / 0 | 7 / 1 |
| agno-main-D16-near-name-split | 做成了 | 25 | 644 | 0 / 0 / 0 | 7 / 0 |
| agno-main-E01-ref-product-knowledge | 没做成 | 52 | 1164 | 0 / 0 / 0 | 7 / 2 |
| agno-main-F01-name-correction | 没做成 | 48 | 1322 | 0 / 0 / 0 | 7 / 1 |
| agno-main-G01-short-answer | 做成了 | 21 | 417 | 0 / 0 / 0 | 7 / 1 |
| langfuse-fuyunping-policies | 做成了 | 23 | 542 | 0 / 0 / 0 | 7 / 1 |
| langfuse-bizno | 做成了 | 29 | 621 | 0 / 0 / 0 | 7 / 3 |
| langfuse-smoke-policy-detail-renyanlin | 做成了 | 15 | 446 | 0 / 0 / 0 | 7 / 0 |
| langfuse-smoke-neg-unknown-policy | 没做成 | 14 | 378 | 0 / 0 / 0 | 7 / 6 |
| langfuse-main-A02-yuxinya-status | 做成了 | 16 | 524 | 0 / 0 / 0 | 7 / 1 |
| langfuse-main-B02-policy-plus-waiting | 没做成 | 22 | 754 | 0 / 0 / 0 | 7 / 1 |
| langfuse-main-C08-two-customers-parallel | 做成了 | 20 | 664 | 0 / 0 / 0 | 7 / 1 |
| langfuse-main-D16-near-name-split | 不确定 | 30 | 812 | 0 / 0 / 0 | 7 / 2 |
| langfuse-main-E01-ref-product-knowledge | 没做成 | 40 | 1108 | 0 / 0 / 0 | 7 / 3 |
| langfuse-main-F01-name-correction | 没做成 | 44 | 1253 | 0 / 0 / 0 | 7 / 1 |
| langfuse-main-G01-short-answer | 做成了 | 16 | 568 | 0 / 0 / 0 | 7 / 2 |
