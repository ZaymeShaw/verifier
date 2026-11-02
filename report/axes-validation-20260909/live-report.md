# 真实 live 扩展轴实测（进行中）

所有样本复用既有脚本和真实预设，输出隔离在 `live/`；未修改业务代码、配置或 ES。条款 QA 被测模型请求 qwen-turbo，client_search 使用现有服务。每例按 `live_run → production judge → eval_axes_report` 执行。判定的独立依据是本次只读导出的 clause_kb 全 13 条原文（`es-field-probes.json`），不以模型自述作为正确性证明。

注意全局主模型配置 gpt-5.6-luna 不代表实际轴模型：首例两扩展轴均为 qwen3.8-flash / fallback1。模型变化、现场生成回答变化与代码效果不可混为单一因果。

执行入口：`live/execute.py`。完整逐例 JSON 在 `live/clause/` 和 `live/client/`；日志 `live/clause.log`、`live/client.log` 保留运行耗时和打印出的 token usage。逐轴完整 usage 含 llm_calls / llm_attempts / llm_failed_attempts / llm_model / llm_endpoint / tool_calls / elapsed_ms。生产 judge JSON 合同本身不含模型 usage，不能从轴模型反推其实际模型；客户端脚本原本不保存 judge 对象，只保存其总体裁决。

## 已完成

- 康宁犹豫期：实际回答“康宁终身险的犹豫期是二十天。”；生产 fulfilled，真实性 1 verified，扩展 fulfilled。引用 kn_hesitation#clause_text 的二十日正确，reason 特别区分另一产品十五日。总 180.6 秒；真实性 2 LLM calls / 3 tools，fulfillment 1 call / 0 tools；两轴均 succeeded。

## 独立核查重点

- 各 claim 必须能在实际回答逐字定位；知识源中的产品、事项、数值与条件要同时吻合。
- 安心 100% 给付原文含“以社会医疗保险身份投保并经社会医疗保险结算”两个前提；不能只比数值。
- 全库没有现金价值条款。康宁责任含重疾给付和身故给付，但不自动支持现金价值公式或具体比例。鑫享第 5 年 20% 属年金给付，也不能移用到康宁现金价值。
- 用户所给旧表中的现金价值 1 verified + 5 unverifiable、观点 3 unverifiable 仅作为参考，不要求新回答有相同断言数。
