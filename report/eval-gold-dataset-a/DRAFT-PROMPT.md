# 起草员任务（案例 ID 由调用方给出，记为 <ID>）

你在为一个评测集独立起草标准答案（gold）。除下面明确允许的那个输出文件外，不要修改仓库里任何文件。

任务：判断这个保险业务对话的「主轴三态」：fulfilled（用户要的结果给到了且核心事实正确）/ not_fulfilled（没给到、给错、如实说没查到）/ not_evaluable（核心断言无法核实）。

材料：
1. 判定口径：读 /Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/alg/fulfilled.md（全文）和 /Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/eval-gold-dataset-a/RULES.md（用户已定的标注口径，共 8 条，优先于你自己的理解）。多轮对话按用户全部诉求整体判，任一轮核心诉求没兑现即 not_fulfilled。
2. 材料文件：/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/eval-gold-dataset-a/cases/<ID>.md ——含对话、冻结的业务回答，以及业务当时实际调用后端的 trace（入参和返回；手机号、姓名等被脱敏成 [REDACTED]；trace 只覆盖第 1 轮）。trace 只是参考业务当时拿到了什么，不能当作真值：核心事实仍要你自己独立查数据源核对。
3. 独立取证：用只读工具查数据源，命令：
   cd /Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/eval-gold-dataset-a && /Users/xiaozijian/miniconda3/envs/agno/bin/python q.py <tool> '<json参数>'
   tool 可用：customer_search / policy_search / policy_detail / customer_detail / product_knowledge / benefit_info / general_qa。policy_detail 参数 {"policy_no":"完整保单号","compact":false}；customer_detail 参数 {"customer_id":"customer_search 返回的 customer_id","compact":false}；其余见 query 自足问句。policy_search 传 customer_id 有时不过滤（可能返回全库）、每页只返回 5 条，要核对返回是否确属该客户，必要时改用 query 带客户名并用 policy_detail 逐张补查。账号固定，测试库。累计已交保费、保额、缴费方式、学历等明细用 policy_detail / customer_detail 查。回答里每个核心事实都要用查到的数据逐条核对。
禁止：不要去看任何评测器/verifier 的判定结果、不要读 .runtime 目录、report/eval-main-axis、report/eval-gold-dataset-a/pilot5、drafts、gold.json、gold-sample42-draft.json（别的案例的结论不能影响你）；不要凭印象判。查不到时如实记为查不到。

输出：
- 把下面这个 JSON 对象写入 /Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/eval-gold-dataset-a/drafts/<ID>.json（这是唯一允许写的文件），并在最后回复里只输出同一个 JSON（不要多余文字）：
{"id":"<ID>","gold":"fulfilled|not_fulfilled|not_evaluable","accept":[gold 以外也算对的结论，通常为空],"why":"一两句话，写清核对了哪些事实、哪里一致/不一致","basis":"引 fulfilled.md 或 RULES.md 的条款","ask":true|false,"ask_reason":"ask 为 true 时说明为什么拿不准、需要人定什么","queries":["你实际执行的查询（tool+参数）"]}
拿不准（口径有歧义、证据不足以判）就把 ask 设 true，不要硬判。
