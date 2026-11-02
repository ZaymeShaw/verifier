# 标注规范：四套 harness × 120 题，过程六轴 + 最终回答

你是标注员。对分给你的每道题、每个 harness（claude / pi / insurance_old / insurance_harness），读过程摘要，写一条结构化判定。只读文件，不改任何文件，只写你自己的输出文件。

## 材料

- 题目期望：`expect/<题号>.md`。有"预期协同"（该调什么工具）、"检查点"（不能犯的错）、"数据前置"。**注意**：题集原文里的客户名和条件已被替换，以文末"本批实际问句"为准；"数据前置"里的张数对应原题，**不能**直接拿来对账。
- 过程摘要：`digest_m/<题号>/<harness>.md`（工具结果截断到 1200 字符）。如果需要看完整工具结果核对数值，再看 `digest/<题号>/<harness>.md`（截断到 2500 字符）。
  - `### USER[n]`：用户第 n 轮。`#k say/CALL`：第 k 次模型调用的说明文字和工具调用。`<- 工具名 len=..`：模型实际收到的工具结果。
  - `FINAL(model)`：模型最后一次输出。`## DELIVERED turnN: = FINAL(model)` 表示用户收到的就是模型输出；`(DIFFERS from model final)` 后面是用户实际收到的文本。
- 各 harness 收到的关键规则（只拿该 harness 收到的规则判它）：
  - 四家都收到的工具说明：金额/字段按原值，不补币种时点；`agg_paid_prem` 等是险种行口径，**不跨险种汇总**；AMBIGUOUS 表示未执行查询、要展示候选让用户选；PARTIAL 的检索正文未经版本定位，不能当作该产品条款；EMPTY 不等于没有。
  - insurance_old、insurance_harness：系统提示有"七条红线"（不编造、**不心算**、不承诺收益、不诱导退保换购、多实体分开陈述等）；"本轮已取得可用事实后不得再发起澄清（ask_user / ask_clarify），应先回答已确认部分"。insurance_harness 额外要求"计算必须调用 calculate"。
  - claude、pi：评测附加了一句"请从mcp工具中获取我的id信息……除了mcp工具外，不要访问本地数据"。这是**评测配置问题**；模型因此产生的困惑，记在 notes 里写"评测配置"，不计入六轴。
- 已知的工具层事实（四家共用后端）：客户搜索解析不了"姓X + 生日月份"这类组合条件；产品条款检索经常返回别的产品的正文；MCP（claude/pi）和 insurance_old 的搜索每页 5 条，insurance_harness 每页 100 条。

## 六轴怎么判（依据 demand/process_axes.md）

每个轴看对应部件"在它实际拿到的输入下，本应产出什么，实际产出了什么"。每轴取值：

- `ok`：这一环检查过，没问题
- `problem`：这一环本身有问题（必须在 issues 里写出来）
- `unlocated`：结果不对，但分不清是这一环还是另一环。最典型的是检索返回了别的产品的正文：工具召回错了还是知识库里没有？此时 tool 和 knowledge 两轴都标 `unlocated`
- `upstream`：这一环没机会正确执行，因为它的输入已经被上游弄坏了（例如工具返回 0 条，模型如实转述"没找到"）。不算本轴问题
- `na`：本题用不到这项能力（例如纯知识题不涉及客户数据源也不算 na，知识轴仍然适用；没有多轮也照常判 context）

| 轴 | 查什么 | 典型 problem |
|---|---|---|
| intent 意图理解 | 用户原文、被指代的历史 → 系统内部要做的事 | 把要查的字段、对象理解错；多轮里"不看 X 了"没有替换掉 X；子问题漏了 |
| planning 规划路由 | 该调的调了没有，顺序、重试、收尾对不对 | 该查详情没查；同一失败反复换说法重试很多次（≥5 次）；已有答案还澄清；没必要的大量调用；AMBIGUOUS 后不展示候选、直接猜 |
| tool 工具执行 | 已发出的调用参数 → 返回是否正确 | 条件解析失败；上游 ERROR；分页只给 5 条且无法翻页导致列表不全；返回了与参数不符的对象 |
| knowledge 知识数据 | 正确执行的查询 → 数据源里是否有对应、匹配的数据 | 字段在源数据里确实为空（这通常是"如实披露"即可，不算 harness 问题，标 ok 并在 notes 说明）；检索返回别的产品 → 与 tool 一起 unlocated |
| model 模型能力 | 一次调用的实际输入 → 该次输出 | 编造；数值读错；把名字相近的两款产品当成同一款；心算求和（insurance_*）；违反收到的规则；**最终输出只有思考、没写给用户的答案**；结论与工具结果矛盾 |
| context 上下文管理 | 一处产出 → 下一处输入（工具结果送给模型、历史、交付） | 工具结果被截断后读不回；交付文本和模型答案不一致（被改写、拼接了中间过程叙述、服务端拼出字段清单）；下一轮历史带的是错的内容 |

归属原则：上游坏了导致下游出错，记上游，下游标 `upstream`。同一事件可以属于多个轴（各记一次），同一轴里同一问题只记一条。

## 最终回答怎么判

看用户实际收到的文本（DELIVERED；如果是 `= FINAL(model)` 就看 FINAL(model)）。

- `answer`：
  - `correct`：所有子问题都答了，内容和工具结果一致；查不到的部分如实说明了。因为工具限制没能取全、但明确说明了"可能不全"，也算 correct
  - `partial`：有子问题漏答，或者有次要错误（不影响主结论）
  - `wrong`：主结论错误（数值错、对象错、把未购说成已购、编造），或者违反题目检查点
  - `no_answer`：用户收到的文本里没有面向用户的答案（只有思考、过程叙述，或停在"让我给出回答"）
  - 合理的澄清（工具返回 AMBIGUOUS 或确实缺关键信息，展示了候选、问得清楚）算 `correct`；不必要的澄清算 `partial`
- `clean`：`true` 表示用户收到的文本可以直接给业务人员看。`false` 表示里面有成段的内部思考（"让我…""Let me…""I should…""</think>"、英文推理段落）、过程叙述拼接，或字段堆砌。只有一句开场白（如"我已查到，整理如下"）算 true
- `privacy`：交付文本里出现了用户没要求的身份证号、手机号明文，就填 true

## 校准样例（主判已人工判定，按这个尺度来）

- A01：四家金额都对（1320 / 6300）。insurance_old 交付的是过程叙述拼接 → correct，clean=false，context=problem。
- A04：真实答案是 6 张年缴保单（含 P260922000005372 盈添悦，P…5369 已终止）。claude 和 insurance_old 每页 5 条漏了 5372，但说明了"可能未取全" → correct，tool=problem。pi 断定第 6 张是季缴的 5370 → wrong，model=problem。insurance_harness 列全 → correct。
- B02：客户持有 1813"安佑福（惠享版）定期重疾"，用户问的是 1836"安佑福重大疾病保险"，是两款产品。回答"已购买" → wrong，model=problem。insurance_harness 还心算了合计 → 同一条 model 问题里一并写。insurance_old 最终输出全是思考 → no_answer。条款检索返回别的产品 → tool、knowledge 都 unlocated。
- B11：claude 和 insurance_harness 的 FINAL 停在"让我给出完整回答" → no_answer，model=problem。pi 给出完整答复 → correct。
- D01：客户搜索解析失败 → 四家 tool=problem。claude 换说法试了 11 次 → planning=problem，并告诉用户"没有姓平的客户" → wrong（模型据工具返回 EMPTY 转述，model 标 upstream）。pi 向用户索要"你的客户号" → wrong，intent=problem（评测配置诱发，在 notes 注明）。insurance_harness 试 4 次后给出放宽条件的选项 → correct。
- F04：claude、pi 没查 P…5854 详情，说累计已交保费为 0（实际 675）→ wrong，planning=problem 且 model=problem。insurance_harness 把 216.7 + 41.7 心算成合计 258.4 → wrong（违反"不跨险种汇总"和"不心算"），model=problem。insurance_old 金额正确、没求和，交付是过程拼接 → correct，clean=false。

## 输出

写到 `annot/out/<你的批次名>.jsonl`，每题每个 harness 一行，共 4 × 题数 行。字段：

```json
{"case":"A04","harness":"pi","answer":"wrong","clean":false,"privacy":false,
 "axes":{"intent":"ok","planning":"ok","tool":"problem","knowledge":"ok","model":"problem","context":"ok"},
 "issues":[{"axis":"tool","desc":"policy_search 每页 5 条，报告 6 条只返回 5 条，无翻页","evidence":"#2"},
           {"axis":"model","desc":"断定未返回的第 6 张是季缴的 P…5370，实际漏的是年缴的 P…5372","evidence":"#7"}],
 "answer_reason":"漏列年缴保单 P…5372，并给出错误推断","notes":""}
```

- `evidence` 写调用序号（`#k`），多轮题写 `t2#k`。
- `desc` 写成"哪一步、什么现象、本应如何"，一句话，用中文，不写程序术语堆砌。
- 每个 problem / unlocated 至少对应一条 issue。
- 拿不准时，在 notes 写明"不确定：原因"，不要硬判。

写完后，在最终回复里只报告：批次名、写了多少行、你最拿不准的 3 条判定是什么（题号、harness、原因）。
