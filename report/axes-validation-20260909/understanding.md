# 扩展轴实测：目标与执行入口

日期：2026-09-09。只读调查当前未提交实现及既有样本；本阶段未调用付费模型，也未连接 ES。Cursor 会话范围由主代理确认。

## 用户意图

验证刚完成的扩展轴在真实运行中是否给出可信、可定位的判断，特别是 ES 知识适配后的真实性效果，而不只证明单测或 JSON 能返回。

成功标准：
- truthfulness 对知识支持、知识矛盾、知识缺失、无事实断言区分正确；claims 原文可在回答中逐字定位。
- verified/refuted 引用能真实回读，且来源实体、事项和条件足以支持裁决；仅引用文本存在并不等于语义核验正确。
- ES search 的多词 OR、keyword-only 命中、matched 和零命中在实际 mapping 上符合提供给模型的说明，避免错误的“库中没有”。
- 启用 truthfulness 时 fulfillment 消费其结果：被 refuted 的相关期望 not_fulfilled；unverifiable 不自动造成失败。真实性 failed 不应把残缺断言当作完整可靠结果。
- client_search 中 fulfillment/carryability 的正常、缺失、能力外、多条件路径仍能实跑，摘要逐格可读。
- 与先前同一回答的回放相比，错误率/工具调用/耗时有可追溯变化；必须区分模型切换和代码效果。

失败模式：ES 零命中漏检；混用相近产品条款；将工具错误作知识缺失；truth claims 漏掉关键事实；无知识时耗尽预算；引用存在但不支持判定；真实轴失败而报告展示成通过；回退模型变化造成无法归因的“改善”。

## 系统理解与可执行入口

统一解释器入口 `bash run.sh python ...`，会经 config resolver 选择 agno 环境。不要直接输出 `.env` 或原始 auth/headers。

1. `tmp/eval_axes_live/clause_qa.py`：真实 `live_run → production judge → eval_axes_report → truthfulness → fulfillment`；场景 `policy-clause-qa`，ES 引用 `es://clause_kb`。可传 case ID 仅运行指定样本。被测 live 请求固定使用 qwen-turbo，评估模型来自运行时配置且可能回退。原脚本写 `tmp/eval_axes_live/clause_qa/`，应通过 importlib 导入并重设模块 OUT 指向本次 report 目录，以免覆盖旧证据。
2. `tmp/eval_axes_live/run.py`：client_search 的 3 个真实请求，以及内存覆盖预设的 3 个固定回答 truth case（`es://v5_e2e_kb`）。可导入后改 OUT，按 `run_live(case_id)` / `run_truth(item)` 调用。run_truth 会全局 monkeypatch capability loader，建议独立进程以免污染之后场景。
3. 固定回答回放：从既有 JSON 的 trace 复原 RunTrace，或构造 RunTrace（capability_ref=policy-clause-qa，body 带 question，extracted_output.output_text 带回答），直接 `build_report(load_project('llm_probe'), trace, run_id=...)`。对比代码效果应优先固定旧回答；另一批真实 live 检查端到端有效性。
4. 无模型 ES 探针：`EsTools(catalog=[{'source':'es','uri':'es://clause_kb'}], recorder=[])` 的 outline/search/read/verify_quote；引用具体 index，调用是只读，需记录返回 locators、matched、完整回读以及实际查询 body（避免输出凭据）。
5. `scripts/_probe_aliyun_axes_tmp.py` 是 MaaS 协议兼容探针，需 PROBE_BASE_URL / PROBE_MODEL / PROBE_API_KEY。它会跑多轮 raw/client/axes 并写临时 dotenv，范围比本次需求大；不宜作为默认业务验证入口。其 axes 阶段只构造回答，未运行真实业务 live。
6. 离线回归：`bash run.sh python -m pytest tests/test_llm_probe_eval_axes.py -q -p no:cacheprovider`。用于补充协议覆盖，不应替代实测。

## 推荐 case 矩阵

| ID / 类别 | 输入与来源 | 预期与验收 |
| --- | --- | --- |
| clause-verified-kn-hesitation | 既有 clause_qa.py：康宁犹豫期二十日 | verified，回读产品/事项一致；fulfillment fulfilled |
| clause-refuted-xx-hesitation-stale | 既有 clause_qa.py：鑫享至尊旧条款二十日，库中十五日 | refuted，引用十五日；生产 fulfilled 与扩展 not_fulfilled 差异可解释 |
| clause-unverifiable-kn-cashvalue | 既有问题 + 固定旧回答回放：现金价值具体比例 | 库无对应条款的断言 unverifiable；不凭常识 verified/refuted；不失败，不无限搜索 |
| clause-multi-ax | 既有：安心等待期30日/免赔额1万/社保100%和未社保60% | 每个关键条件覆盖且 verified，尤其两个报销比例不能混掉 |
| clause-noclaim-opinion | 既有年轻人适合性建议 | 必须依真实回答判断：纯观点 claims=[]；夹带保障事实则这些事实可为 unverifiable。不能强断言所有回答无claims |
| strict-no-claim | 固定回答“我暂时无法回答这个问题。” | claims=[]、succeeded，零知识工具 |
| mixed-supported-contradicted | 康宁犹豫期20日 + 安心等待期90日 | 同一输出同时 verified/refuted，fulfillment仅对应错误不兑现 |
| keyword-only | 产品名只在keyword字段，查询完整产品名及名称子串 | 命中保留且有正文locator，matched应含产品名 |
| OR/absent | `康宁终身险 现金价值`、`现金价值`、唯一不存在词 | 前者产品命中不能冒充现金价值存在；后者确认真实无命中，与全库回读对照 |
| field-selection | 搜已知存在内容，对 text/keyword 显式字段及多字段分别搜 | 结果和工具“子串”说明一致；现有代码显式keyword走phrase而非wildcard，需重点实测 |
| client-search-name | 既有 mock_cases ID llm-probe-client_search-name | fulfillment 正确；无需承载的轴2状态符合trigger |
| client-search-unsupported | llm-probe-client_search-unsupported | 能力外要求识别并正确carryability归位 |
| client-search-multi | llm-probe-client_search-multi | 多期望拆分；缺项与已兑现项独立 |

## 既有证据及比较陷阱

- `clause_qa_round1/summary.json`：deepseek-v4-flash-0731，现金价值 truth failed（5 extracted / 188 tools），观点 failed（48 tools）。
- `clause_qa_round2/summary.json`：同模型，现金价值 succeeded（5 extracted / 62 tools），观点 failed（3 extracted / 113 tools）。
- `clause_qa/summary.json`：目前只含 refuted 和 opinion 两例，模型 gpt-5.6-luna，分别4和7 tools，均succeeded；refuted使fulfillment not_fulfilled，opinion不使其失败。此文件不足以支持现金价值最新结果，需要找独立文件或会话证据。
- `run.py` 真实性 answer 是人工固定，属于真实 LLM+ES 的判定回放，不能称为业务 live 生成。
- 不同轮模型、live回答、抽取断言数量都变化，不可直接把工具数下降全归于 ES 修复。

## 可用服务与风险

已找到声明入口，在线性尚未由本阶段验证：client_search 本地 127.0.0.1:8000，条款QA 阿里云 DashScope，ES 来自 eval_axes.es runtime 配置。需要主代理核验实际连通、索引mapping/doc数量。不要新建/写入索引；对完整 corpus 的少量只读导出可用于 oracle，结果只留本地报告。

用户已授权实测，本阶段仅按分工不跑收费模型。实际评估应将真实live样本限制在代表集，记录评估model/endpoint/fallback和usage。若回退，结果应明确实际使用模型；不要为了隔离改用户持久配置。现有调用可能写 trace/report 等本地运行产物。

## 参考 checklist

- `spec/adapter/axe-v5.md` §§1–3：ES引用/回读、可选依赖、真实性和fulfillment证据合同；开头“未实现”是过期标题，应结合当前代码/实施记录。
- `impl/projects/llm_probe/eval_axes/adapters/truthfulness.py`：当前两轮逐断言核验、extract格式修复一次、outline预供、16工具/会话、900秒轴预算。
- `impl/projects/llm_probe/eval_axes/sources/es_tools.py`：当前已偏离v5初版multi_match默认，采用空白拆词+phrase+keyword wildcard。
- `impl/projects/llm_probe/eval_axes/runner.py` / `adapters/fulfillment.py`：轴依赖、失败状态、truth注入检查。
- `impl/data/llm_probe/capability_map.json`：场景真实预设与endpoint，只读访问避免输出认证字段。
- `tmp/eval_axes_live/*/summary.json`、case JSON：先前结果和完整trace可供回放，保留原证据。
