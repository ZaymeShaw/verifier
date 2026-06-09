# 20260609 summary lastChain stale judge alignment check 报告

## 审查范围

- `review.md` 第 16 条：`45岁女性保费10万以上` 在 live judge 正确，但归因总结页仍可能显示旧的 `empty_query` judge。
- `impl/frontend/summary.html`
- `impl/protocols/frontend_protocol.md`
- client_search live / summary single-chain / batch 链路

## 问题定位

后端 live、`/api/run_chain`、`/api/batch_run` 对当前输入 `45岁女性保费10万以上` 都能返回一致的三条结构化条件：

```json
[
  {"field":"clientAge","operator":"RANGE","value":{"min":45,"max":45}},
  {"field":"clientSex","operator":"MATCH","value":"女"},
  {"field":"annPremSegNum","operator":"GTE","value":100000}
]
```

上一轮已处理用例池 row 的 stale `trace/judge/attribute`，但归因总结页还有单链路 `lastChain:<project>` 会从 `sessionStorage` 加载最近结果。用户当前输入已经是 `45岁女性保费10万以上` 时，旧 `lastChain` 仍可能保存历史 `empty_query` 结果，并在“加载最近结果”或其它渲染路径中展示，造成 live 与归因总结页 judge 看起来不一致。

因此本轮补齐的是 summary 单链路缓存结果的输入一致性保护，而不是再改 client_search 后端解析或 judge agent 逻辑。

## 已执行修复

- `impl/frontend/summary.html`
  - `loadLastChain()` 加入输入匹配检查：只有 `lastChain.trace.input` 与当前输入一致时才允许渲染，比较时忽略 batch 注入的 `case_id`。
  - `loadLastChain()` 对 `client_search` 非空 query 却带 `empty_result_reason === 'empty_query'` 的旧结果直接清理，并提示重新运行单链路。
  - `renderChain(data)` 自身也加入同样的防线，避免其它调用路径绕过 `loadLastChain()` 后展示 stale judge。
  - `hasNonEmptyQuery()` 兼容 raw input 和 `{input: ...}` 两种调用形态，避免 stale empty_query 保护漏判。

- `impl/protocols/frontend_protocol.md`
  - 补充规则：加载保存的 single-chain result 也必须按输入匹配规则校验后才能渲染 `RunTrace` / `JudgeResult` / `AttributeResult`；不匹配时要清理或阻止展示。

## Checklist

- [x] live、summary single-chain、summary batch 都通过当前输入重新运行。
- [x] summary case-pool row 不复用输入不匹配的历史结果。
- [x] summary single-chain `lastChain` 不复用输入不匹配的历史结果。
- [x] summary single-chain `lastChain` 不展示非空 client_search query 的旧 `empty_query` 结果。
- [x] 前端协议补齐 saved single-chain stale result 规则。
- [x] 未新增 client_search 专用后端分支；修复点仍在通用前端状态卫生和展示保护。

## 验证结果

- `python -m compileall impl`：通过。
- `check.scan_protocol_alignment(impl)`：无问题。
- `check.scan_core_boundary(impl, client_search markers)`：无问题。
- `check.scan_core_boundary(impl, QA scenario markers)`：无问题。
- summary 前端静态审核：
  - `loadLastChain` input guard：通过。
  - `renderChain` input guard：通过。
  - `renderChain` stale `empty_query` guard：通过。
  - case-pool stale guard：通过。
- Python pipeline UAT（当前输入 `45岁女性保费10万以上`）：
  - live trace conditions = `clientAge` + `clientSex` + `annPremSegNum`。
  - summary single trace conditions = `clientAge` + `clientSex` + `annPremSegNum`。
  - summary single judge actual conditions = `clientAge` + `clientSex` + `annPremSegNum`。
  - summary batch trace conditions = `clientAge` + `clientSex` + `annPremSegNum`。
  - summary batch judge actual conditions = `clientAge` + `clientSex` + `annPremSegNum`。
  - 全部 `matches_expected == True`，无 `empty_query`。
- 8020 API UAT：
  - `/api/run_chain` trace 与 judge_actual 均返回三条条件。
  - `/api/batch_run` trace 与 judge_actual 均返回三条条件。
- 8020 smoke：
  - `/health` HTTP 200
  - `/projects` HTTP 200
  - `/frontend/live.html` HTTP 200
  - `/frontend/summary.html` HTTP 200

## 结论

本轮最终补齐了归因总结页单链路 `lastChain` 的 stale 数据保护。现在 `45岁女性保费10万以上` 在 live、summary 单链路、summary batch 中都会基于当前输入得到一致的三条结构化条件；归因总结页不会再把历史 `empty_query` judge 展示到当前输入旁边。

如果浏览器仍显示旧结果，需要硬刷新以加载最新 `summary.html`，新代码加载后会自动阻止或清理旧 sessionStorage 结果。
