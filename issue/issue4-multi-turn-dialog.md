---
id: 4
title: "不支持多轮对话，如何能够支持？"
created_at: 2026-06-25
author: 此般浅薄
labels: []
status: open
---

# 不支持多轮对话，如何能够支持？

---

### 💬 此般浅薄 · 2026-06-26 16:00

> **标记**：`提出者` · `验证者`

现在我们的场景其实不支持多轮对话，如何能够支持？

---

### @xiaozijian (Product Owner, 补充自己的想法) - 2026-06-25

多轮的话，实现上需要有扩展到机制，比如一个trace，在多轮场景下，inpu
  t那里mock的只是一个意图，然后output那里应该是mock和live系统进行多轮交互，mock
  agent根据用户意图和当前上下文产出合适的系统输入给live系统，然后应该是一个多轮交互的过程，output列这里体现多
  轮，input列的话就只体现用户意图就好，然后无论live页还是summary页的表格都应该支持这个东西。你将这个东西放在is
  sue4里面



目前我的想法和verifier/demand/multi_turn_interaction.md比较接近