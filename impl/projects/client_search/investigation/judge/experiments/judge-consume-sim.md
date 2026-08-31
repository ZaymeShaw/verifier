# Draft Judge Key-Index 消费策略仿真（冻结 30 条）

生成时间：2026-08-13 12:34:22 CST

仿真性质：在 production Current 核心上叠加真实 Catalog Search→Load；不改 fulfillment 核心、不 promote、不改 judge.py。

## 1. 策略对照 desired（只有 Load 证明的 mapping/字段事实才允许改 Current）

| policy | match | false F | false NF | false NE | 128 | 088 | 093 | 008 | 048 | 073 | 113 | 133 |
|---|---:|---:|---:|---:|---|---|---|---|---|---|---|---|
| P0_core_only | 30/30 | 0 | 0 | 0 | NF | F | F | F | F | NE | NE | F |
| P1_searchhit_pollutes | 27/30 | 2 | 1 | 0 | F | NF | F | F | F | NE | NE | F |
| P2_load_only_silent_miss | 30/30 | 0 | 0 | 0 | NF | F | F | F | F | NE | NE | F |
| P3_enrich_gate_current | 25/30 | 0 | 5 | 0 | NF | NF | NF | F | F | NF | NF | NF |
| P4_rewrite_as_synonym | 30/30 | 0 | 0 | 0 | NF | F | F | F | F | NE | NE | F |
| Draft_actual | 20/30 | 1 | 8 | 1 | F | NF | NE | NF | NF | NF | NF | NF |

## 2. 相对 production Current 的位移

| policy | 仍等于 Current | 改动条数 | 改动 case |
|---|---:|---:|---|
| P0_core_only | 30/30 | 0 | — |
| P1_searchhit_pollutes | 27/30 | 3 | 023, 088, 128 |
| P2_load_only_silent_miss | 30/30 | 0 | — |
| P3_enrich_gate_current | 25/30 | 5 | 073, 088, 093, 113, 133 |
| P4_rewrite_as_synonym | 30/30 | 0 | — |

## 3. 八条对照

| case | query | live 形态 | Current | Draft | desired | P1 | P2 | P3 | P4 |
|---|---|---|---|---|---|---|---|---|---|
| 008 | 孤儿单 | conditions | F | NF | F | F | F | F | F |
| 048 | 158****5078 | conditions | F | NF | F | F | F | F | F |
| 073 | 2025年6月份投保的新客户名单， | conditions+notice | NE | NF | NE | NE | NE | NF | NE |
| 088 | 7月盘客 | empty+notice | F | NF | F | NF | F | NF | F |
| 093 | 贵C826N1 | empty+notice | F | NE | F | F | F | NF | F |
| 113 | 东莞何叶玩具制品有限公司 | empty | NE | NF | NE | NE | NE | NF | NE |
| 128 | 合家福客户 | conditions+nearmiss | NF | F | NF | F | NF | NF | NF |
| 133 | 中银保信 | empty | F | NF | F | F | F | NF | F |

### 八条要点

- **128** `合家福客户` Current=NF Draft=F desired=NF hits=0 strong_load=0 notice_load=0；P2=silent_miss_no_strong_load；P3=e1_no_empty_no_unsupported
- **088** `7月盘客` Current=F Draft=NF desired=F hits=1 strong_load=1 notice_load=0；P2=unsupported_honest_refusal:customerReview；P3=e1_unsupported_field_nf:customerReview
- **093** `贵C826N1` Current=F Draft=NE desired=F hits=0 strong_load=0 notice_load=1；P2=silent_miss_no_strong_load；P3=e1_unsupported_field_nf:licensePlateNo
- **008** `孤儿单` Current=F Draft=NF desired=F hits=3 strong_load=2 notice_load=0；P2=mapping_live_matches:孤儿单->纯存续单客户；P3=e1_no_empty_no_unsupported
- **048** `158****5078` Current=F Draft=NF desired=F hits=0 strong_load=0 notice_load=0；P2=silent_miss_no_strong_load；P3=e1_no_empty_no_unsupported
- **073** `2025年6月份投保的新客户名单，` Current=NE Draft=NF desired=NE hits=8 strong_load=0 notice_load=2；P2=silent_miss_no_strong_load；P3=e1_unsupported_field_nf:policies_insure_date
- **113** `东莞何叶玩具制品有限公司` Current=NE Draft=NF desired=NE hits=0 strong_load=0 notice_load=0；P2=silent_miss_no_strong_load；P3=e1_empty_blocking_nf
- **133** `中银保信` Current=F Draft=NF desired=F hits=0 strong_load=0 notice_load=0；P2=silent_miss_no_strong_load；P3=e1_empty_blocking_nf

## 4. 本轮 Catalog 实证（非臆造 hit list）

- 强 Load 仅 4/30：003 在职单 mapping→在职有效客户；008 孤儿单 mapping→纯存续单客户；023 少儿万能险 identity mapping（live 未用该 canonical）；088 customerReview is_supported=false。
- **128 合家福客户：hits=0**。合家欢 只在 query=合家欢 时 exact 命中 abbr/field。Catalog 没有把 合家福 召回成 合家欢。Draft F 是 Judge 把 live 近邻当同义，不是 SearchHit 污染。
- **093 贵C826N1：query hits=0**（静默）。通知标签「车牌号」才能 Load licensePlateNo unsupported。P2 按 query 静默保持 Current F；P3/E1 用标签 Load 后把诚实拒绝打成 NF。
- **073** query 无强 Load；通知标签 Load 到 policies_insure_date unsupported + 周年日字段。live 非空（残留客户类型）→ P2 不改 NE；P3 见 unsupported 就 NF。
- 其余 26 条无 query 强 Load：048/113/133/083/098… 全部 silent miss。

## 5. Anti-hack / 泛化

- SearchHit-as-F on 128：catalog hits=0。P1=F（字面 1 编辑距离当同义，且 023 万能险~万能型 也会被 P1 错打成 F）。P2=NF 静默 NF。P4=NF（rewrite 未打到合家欢）。
- 全量 dump：wildcard load=0；单 case 最大 Load=2（仅 Search 命中的 key，从未 key=* / 遍历 mappings）。
- P2 业务词表：clean=True found=[]。P2 决策只用 Load content + live 形态（empty+notice vs conditions），无业务词 if。
- Holdout：金凤 hits=1 strong=1；关爱客户 hits=0 strong=0；天气怎么样 hits=0 strong=0；客户平时有什么兴趣爱好 hits=0 strong=0；盘客 hits=1 strong=0；去盘客 hits=2 strong=1；A hits=0 strong=0；O2O hits=6 strong=6；合家福 hits=0 strong=0；合家欢 hits=2 strong=2；车牌号 hits=2 strong=1；投保日期 hits=8 strong=2
- 金凤 exact abbr；天气/爱好/关爱客户 hits=0（无需 reject lexicon）。两字「盘客」无强 Load，7月盘客/去盘客 才 exact 到 customerReview。O2O 是 mapping spoken 精确成员，不是 dump。
- 契约按 Collection 泛型 Search→Load，无 client_search ifs。Holdout 释义检索同样走 Search→Load，没有为 paraphrases 单开项目路由。

## 6. 推荐与最终消费契约

**推荐：P2_load_only_silent_miss**（match desired 30/30；相对 Current 位移 0；能在 003/008/023/088 用 Load 确认 Current，并挡住 Draft 在 128/088/093/008/048/133 的回归。）

P0 分数相同但是「不消费材料」：若未来 Current 在 mapping 上错了，P0 无法纠正。P4 本轮碰巧 30/30，只因 rewrite 没有打到近邻名；它不是安全契约。P1/P3 会引入 false F/NF。

- Key-Index 只定位/补载可 Load 材料，不得改写 F/NF 核心；无强命中 Load 时静默走原路径（= production Current）。
- SearchHit 不是 Evidence。rewrite / embedding 近邻不得当同义证明；未 Load 不得改 overall。
- 仅当 Load 到 value_mapping / abbr 且 spoken 出现在 query：live 用了 canonical → F；live 用了别的值 → NF。
- 仅当 Load 到字段定义 is_supported=false（显式）且 live 为空 + 透明「暂不支持」通知 → F（边界处理成功，不是把 parser 打成 NF）。
- 仅当 Load 到字段 is_supported=true 且 live 为空 → NF（能力内漏检）。
- Authority 关闭时，不得仅因存在能力边界就判 NE；诚实拒绝是 F，不是 NF/NE。
- 禁止业务词表 / COMMON_TOKENS / query-shape 路由；契约跨项目泛型为 Search→Load supplement。
- 禁止全量 dump（key=* 或遍历 mappings）；每次只 Load Search 返回的有限候选（limit=8）。

## 7. Catalog 运行备注

- embedding: BailianEmbeddingProvider（text collections 附加通道；abbr/mappings embedding rejected；分数上限 ~100 < STRONG_HIT_FLOOR 150，故 embedding 永不单独改 status）
- indexes: client-search.abbrname-enums, client-search.enhanced-rules, client-search.field-definitions, client-search.value-mappings
- strong Load 覆盖: 4/30 ；silent miss: 26/30

