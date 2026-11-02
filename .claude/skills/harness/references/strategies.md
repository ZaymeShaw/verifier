# Harness 策略卡

每张卡：什么时候用、怎么起手、逐轮怎么决策、何时 close、声明什么 intent、签名怎么起。所有策略共用 SKILL.md 第 0 节约束。

## persona

**何时**：`focus` 是"真实用户会不会被服务好"，或 `coverage_targets` 里的场景需要自然对话触达。

**起手**：先写一个人，不是一个测试项——
```
45 岁女性代理人，带 30 多个老客户，习惯说口语数字（"五十万""半年内"），
一句话只说一个条件，被追问才补；隐含约束：只看还在有效期内的保单。
```
把"隐含约束"故意不说出口——真实用户默认对方懂。

**逐轮**：按这个人的习惯回答 live 的追问；live 问得对就配合，问得不对就像真人一样困惑地重述而不是纠正它；live 给了结果就检查是否符合**包括隐含约束**的目标。

**close**：拿到符合目标的结果 → `goal_satisfied`；被追问三次以上同一件事 → `perceived_no_progress`；结果明显错但真人会去别的渠道 → `user_abandons`。

**intent**：开场 `seeded`，一句用户视角：「找我名下 50 万以上还在保的保单」。`--context` 放 persona 描述。

**签名**：`<scenario>:<丢的是什么>`，如 `clarification_reply:implicit_active_filter_ignored`。

## scripted

**何时**：复现台账里已有但想确认修复的签名；覆盖 `coverage_targets` 里必须到位的场景；或者用户给了具体剧本。

**起手**：预写 3–5 句，每句标注"预期 live 反应"。剧本是路线图不是圣旨。

**逐轮**：live 反应与预期一致 → 下一句；不一致但更好 → 照真人反应即兴接一句再决定；不一致且更差 → 这就是发现，问一句确认后 close。

**close**：剧本走完且目标达成 → `goal_satisfied`；中途发现失败 → 依真人心态选 `user_abandons` / `perceived_no_progress`。

**intent**：`seeded`。

**签名**：复现类沿用台账里已有的签名（返回 `new: false` 是正常的，说明还没修）。

## adaptive-replay

**何时**：已有导出的 transcript seed（`impl/data/<project>/sessions/` 或 `mock_cases-*.json`，别人的会话录音），想知道 live 改版后同样的用户还会不会被服务好；或 `strategy_hints` 含 `adaptive-replay`。

**起手**：
```bash
$CLI session get <project> <old_session_id>       # 看 seed_case.seed.turns 与 intent_history
```
先从 turns 推断录制用户的真实目标（有 `intent_history` 就直接用）。开新会话，`declare_intent --source adopted_from_inference`——这是你据以行动的推断，不是真值。

**逐轮**：照录制的用户第 1 句说；live 回复与录制一致 → 继续照抄；不一致 → 以推断目标为准改台词（真人会怎么接这句新回答）。记下第一处不一致的轮次，写进 `--notes`（评测系统的确定性重放会标 `diverged_at_turn`，你的这条是人视角的对照）。

**close**：同 persona。

**签名**：如果是原录音就有的失败，沿用旧签名；新失败按 `<scenario>:<维度>`。

## boundary

**何时**：`focus` 提到边界、解析、数值、单位；或 live 的核心是把口语变结构化查询。

**起手**：列这个业务的值域边缘：
- 数字表达：`50万` / `五十万` / `50w` / `0.5亿` / `500000` / `50万块钱`
- 区间与比较：`以上` / `不低于` / `超过` / `50到100万之间` / `不到 50 万`
- 否定与排除：`不要已退保的` / `除了重疾险`
- 时间：`上个月` / `近半年` / `2025 年以前`（注意相对时间取决于 `currentTime`）
- 组合：两个字段一句话；两个字段两轮给
- 脏输入：空串、纯标点、错字（`保额` → `报额`）、超长

每场只押 **一个**边界，剩下的开新会话。

**逐轮**：第一句给边界表达；看 live 是澄清、正确解析、还是**越界执行**（返回了一个看似成功但条件不完整/错误的结果——这是最值钱的发现）；第二句用真人方式补齐或确认。

**close**：解析对了 → `goal_satisfied`；澄清合理但两轮后仍不对 → `perceived_no_progress`；直接给了错结果 → 真人通常会 `user_abandons`。

**intent**：`seeded`，写清目标值：「保额不低于 50 万的保单」。

**签名**：`<scenario>:<维度>`，维度用失败机制不用输入值：`boundary:unit_wan_misparsed`、`boundary:partial_filter_executed_without_threshold`。

**realism**：正常口语 → high；`50w` 这种 → medium；纯符号/超长 → low。

## drift

**何时**：`focus` 提到上下文、改主意、多轮状态；或 persona 场里发现 live 把历史条件粘在一起。

**起手**：前 1–2 轮认真追一个目标 A（`seeded`）。

**转折**：第 3 轮明确改主意——换字段（"算了不看保额，看缴费期"）、换阈值（"50 万太多了，30 万以上就行"）、撤回条件（"不限有效期了"）。当轮 **再声明一次** `--source drifted`，写新目标 B。

**逐轮**：看 live 是把 B 当新查询、把 A+B 叠加、还是仍按 A 回答；用真人方式追问一句确认。

**close**：按 B 拿到结果 → `goal_satisfied`；A 残留 → `perceived_no_progress`。

**签名**：`drift:stale_condition_retained`、`drift:threshold_update_ignored`。

## protocol-fuzz（默认关闭）

只在用户明确要求"探协议边界"时用：`session open --mode protocol-fuzz`，`send --request '<json>'` 发畸形/越权请求体。这类会话与发现自动打 `protocol_fuzz`，和业务缺陷分开统计。不要用它替代 text 探索。
