最终输出严格 JSON，不自行写计数，不添加协议外字段：
{"spawn_id":"任务给定","case_id":"任务给定",
 "coverage":[{"call_id":"ID","depth":"full|partial|unverifiable","note":"说明"}],
 "relations":[{"call_id":"ID","category":1,"result":"ok|finding|n/a","finding_ids":[],"note":"说明（类别6列上下游ID）"}],
 "common_rules":[{"key":"稳定key","scope":{"role":"账本role","stage":"账本stage","version":"实际版本或unknown"},"status":"present|n/a|unknown","call_id":"present的ID或null","where":"位置或空串","quote":"present原文或空串（最多300字）","note":"理由"}],
 "findings":[{"id":"F-01","verdict":"confirmed|explained|open","severity":"blocking|high|diagnostic","category":2,"ends":[{"call_id":"ID","side":"request|response","where":"位置","quote":"最多300字"}],"scope":"适用范围","exclusive":"冲突或缺口","counter_evidence":"反证核对","impact":"影响","remediation":"建议"}],
 "carry_over":[{"finding":"任务给定的旧reference","ruling":"resolved|persists|unverifiable","ends":[],"finding_ids":[],"note":"依据"}],
 "output_checks":[{"axis":"轴","items":["逐条回答"]}],
 "diff_rulings":[],
 "summary":"三五句话，仅描述结论"}

每个本 case 实际 call_id 恰好一条 coverage、每类恰好一条 relation。ID 是 llmtrace 原样 ID，不加 .txt。每个 finding.id 在分片内唯一。relation.result=finding 时 finding_ids 必须存在且非空；其他结果 finding_ids 为空。confirmed 与 open 严重度有效，explained 不计问题。
聚合 diff_rulings 每项 {"diff_id":"任务给定","verdict":"confirmed|explained|open","finding_ids":["F-01"],"note":"原文与范围依据"}，每个差异恰好裁一次。
