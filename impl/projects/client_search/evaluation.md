# Evaluation

Judge the current client_search API output by reconstructing expected-vs-actual from the current query, current response, current downstream-search evidence when available, and the current project prompt/config references from `projects/client_search`.

Project-owned source references:

- `projects/client_search/readme.md`: project-level judging instruction. 当前 source 明确：标准答案的答案结果由于数据库字段已经过时、跟 API 返回结果不一致，所以标准答案只能作为参考；judge 需要根据最新项目资料和当前运行证据进行实时标注，重点关注值是否正确、引用字段是否合理，并从语义上判断是否能搜索出正确客户。
- `projects/client_search/config.md`: pointers to original client_search field definitions, enum definitions, value mappings, and enhanced rules. These original business configuration files are boundary evidence for ES/search capability; the static summary document itself is only an auxiliary pointer, not an absolute verdict standard.
- `projects/client_search/prompt.md`: current prompt rules for condition generation, operators, age handling, unit conversion, AND/OR, and output format. It helps interpret parser expectations, but equivalent ES/search results may still be acceptable.
- `RunTrace.project_fields.downstream_search`: project-scoped downstream customer-search probe result built from parser `conditions` and `query_logic`.

Quality requirements:

- Do not inherit previous cases, page state, clusters, or attribution conclusions.
- Re-understand the user's underlying intent before comparing conditions.
- Use the project judge boundary standard as the final verdict standard. For client_search, the core goal is whether the parser can retrieve the intended customer set from the dependent ES/customer-search capability.
- Upstream ES database field/enum/data limitations are treated as system capability boundaries, while model, config, prompt, project code, field mapping, and post-processing errors remain evaluable system issues.
- Use `impl/projects/client_search/judge.md` as the project judge construction standard. It explains how the boundary protocol constrains expected-vs-actual and expected-vs-result-set judgment for client_search.
- Use current ES/downstream-search semantics and original business field/enum/value-mapping/rule files as capability-boundary evidence. Prompt, generated config summaries, project code, post-processing, and pipeline behavior are internal implementation evidence: they help explain actual behavior, but they are not absolute standards and may themselves be the source of an evaluable error.
- Treat the API response shape as already normalized by the adapter unless the trace explicitly shows malformed data; the main judging target is whether returned values are semantically correct and executable.
- Check whether selected fields, operators, enum values, unit conversions, boundary handling, and `query_logic` match the current user intent.
- Check whether the output covers the core user intent and can retrieve the intended customer set.
- If `downstream_search.status == "ok"`, use the downstream payload/result as evidence for result-set verification and mark whether it supports the verdict.
- If downstream search is unavailable, not configured, or skipped, judge must mark that ES actual result-set verification was not performed, but must still judge ES query semantic equivalence from parser conditions, field/operator semantics, enum capability, and business intent when possible; only return `uncertain` when semantic equivalence cannot be determined from available evidence.
- Separate missing, wrong, and extra conditions.
- If response fields are structurally valid but semantically wrong, mark incorrect and explain why.
- If `structured_output` is empty while the user query is non-empty, treat this as an empty-recognition result, not a successful structured parse. The judge should evaluate whether the query should have produced conditions under current prompt/config/search-capability rules and mark incorrect when the query intent is recognizable.
- Empty-result classification must use the best available source query from the API response (`rewritten_query`, original `query`, or equivalent request echo). Missing `rewritten_query` alone must not turn a non-empty request into `empty_query`; it should be `service_returned_no_conditions` when the service handled a non-empty query but returned no conditions.

Client_search-specific judging guidance from the current prompt/search capability:

- Only fields available to the project search capability are valid.
- Enum fields must use values supported by the current ES/search capability; prompt/config enum lists are references when actual ES evidence is absent.
- Numeric/date fields use GTE/LTE/GT/LT/RANGE according to wording and executable query semantics.
- `clientAge` has special boundary handling:
  - “50岁以上/及以上” => `GTE 50`.
  - “大于/超过50岁” => `GTE 51`.
  - exact age => `RANGE {min:x,max:x}`.
- Chinese units must be converted where explicit: `万=10000`, `千=1000`.
- Multiple different filters normally use `AND`; `OR` is only for explicit “或者/任一” semantics over independent conditions.
- The expected output shape is `query_logic` plus a list of `{field, operator, value}` conditions; equivalent executable downstream-search payloads may be accepted when they retrieve the same intended customer set.

The adapter stores client_search response details in `project_fields`; judge may inspect them because this is the project evaluation spec, but generic core must not require those field names or downstream ports.
