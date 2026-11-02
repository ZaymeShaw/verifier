对象查实不存在时，"它有某个值"判 refuted（demand/claims.md §3.3、§3.4）。

- `knowledge_loop/loop.py` 取证规则第 10 条：按对象查过、返回明确表明对象不存在，这个返回就是相关原文，交 found 并引用。
- `truthfulness.py`：对象本身不存在 → 关于它的取值说法 refuted；对象在、只是没有这一项仍 unverifiable。
- 另含第二块代码（承载性 sample.request_body、MCP 引用核验、main_verdict 合成），对未开承载性的场景无影响。
- 只跑开发集。v1 开发集 41/43，判错：langfuse D16（取证漏查客户详情）、unit-policy-absent。
