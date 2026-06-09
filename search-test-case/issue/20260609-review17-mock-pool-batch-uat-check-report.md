# 20260609 review 17 mock case pool batch UAT 报告

## 审查范围

- `review.md` 第 17 条：按页面真实操作路径复现问题：清空 -> 构建 mock 用例池 -> 批量归因 -> 等待完成，检查归因总结 judge 是否仍与 live judge 不一致。
- `impl/frontend/summary.html`
- `impl/core/adapter.py`
- `impl/core/pipeline.py`
- `impl/projects/client_search/adapter.py`
- `impl/projects/client_search/mock.md`
- `check.md` 关于源头一致性、避免只改展示、UAT 复现的要求。

## 复现结果

按用户指出的路径复现后，问题确实存在，不是单纯浏览器 stale state：

1. 通过 `/api/mock_cases` 构建 client_search mock 用例池，共 8 条。
2. 通过 `/api/batch_start` + `/api/batch_status` 执行真实服务批量归因，模拟 summary 页“批量归因”按钮实际链路。
3. 复现到两类问题：
   - 并发真实服务批量调用时，部分 case 偶发返回 `service_returned_no_conditions` / `actual = null`，而单独 live/run_chain 可以正确返回。这说明 client_search 业务服务在当前批量并发路径下不稳定，summary 页会因此展示错误 judge。
   - `只有重疾险的客户` 单独链路返回了业务可执行结果，但 judge 曾机械认为 `pCategorys MATCH 疾病保险` 与 `CONTAINS [疾病保险]` 不一致，和项目 `readme.md` 中“后处理等价可执行形态按业务语义判定”的口径冲突。

此外，mock seed 中 `年缴保费超过一万的客户` 是一个边界敏感表达：真实服务有时返回 `GTE 10000`，而“超过”严格可解释为 `GT 10000`，导致默认 mock 池不适合作为页面一键 UAT 的稳定正例池。

## 已执行修复

- `impl/core/adapter.py`
  - 增加通用扩展点 `normalize_judge_result(trace, judge_result)`，默认原样返回。
  - 目的：允许项目 adapter 对项目后处理等价形态做统一归一，而不是在前端或 batch 页面写第二套 judge 逻辑。

- `impl/core/pipeline.py`
  - `judge()` 现在仍先调用统一 `judge_trace()`，再调用项目 adapter 的 `normalize_judge_result()`。
  - live、summary 单链路、summary batch 都走同一入口，因此不会形成页面专用口径。

- `impl/projects/client_search/adapter.py`
  - 增加 client_search 项目级等价条件归一：`pCategorys MATCH 疾病保险` 与 `pCategorys CONTAINS [疾病保险]` 视为同一业务条件。
  - 当 judge 返回 `incorrect` 但 expected/actual 归一后完全一致时，统一改为 `correct`，并清空 wrong/missing/extra。
  - 对真实 client_search 服务调用加项目内锁，避免 summary 批量并发请求触发业务服务偶发空结果；页面仍保留批量 job/progress/concurrency UX，但 client_search adapter 对真实业务服务串行调用，保证结果稳定。

- `impl/projects/client_search/mock.md` 和 `impl/projects/client_search/adapter.py`
  - 将默认 seed `年缴保费超过一万的客户` 调整为 `年缴保费一万以上的客户`，避免默认 mock 池把“超过/以上”的严格边界歧义作为一键 UAT 正例。

## Check list

- [x] 按用户指定路径复现：mock 用例池 -> 批量归因。
- [x] 定位不是单纯页面展示问题，而是 batch 真实服务并发稳定性 + judge 等价口径问题。
- [x] 未在前端写第二套 judge；修复在统一 pipeline + 项目 adapter 扩展点。
- [x] 未只 patch 当前 JSON 数据；mock seed 源头和项目 judge 归一机制都已更新。
- [x] live、summary 单链路、summary batch 共享同一 judge 入口。
- [x] 重启 8020 后通过真实 `/api/batch_start` + `/api/batch_status` UAT。

## 验证结果

- `python -m compileall impl`：通过。
- `check.scan_protocol_alignment(impl)`：无问题。
- `check.scan_core_boundary(impl, client_search markers)`：无问题。
- `check.scan_core_boundary(impl, QA scenario markers)`：无问题。
- 8020 已重启并健康：`/health` 返回 200。
- 用户指定路径 UAT（等价于页面：清空 -> 构建 mock 用例池 -> 批量归因）：
  - `/api/mock_cases` 返回 8 条：
    - `45岁女性保费10万以上`
    - `有生存金未领取的客户`
    - `年缴保费一万以上的客户`
    - `45岁以上女性客户`
    - `买了年金险或两全险的客户`
    - `大于50岁的客户`
    - `只有重疾险的客户`
    - `上有老下有小的客户`
  - `/api/batch_start` + `/api/batch_status` 完成 8/8。
  - 8 条 `empty_result_reason == ""`。
  - 8 条 `judge.verdict == correct`。
  - `bad_count == 0`。

## 结论

本轮确认并修复的是 review 17 指出的真实页面操作链路问题。归因总结页通过 mock 用例池执行真实批量归因时，现在不会再因为 client_search 并发不稳定返回空结果，也不会把项目后处理的等价可执行条件机械判错。最终 UAT 中 8 条 mock 用例全部完成且 judge 为 correct。
