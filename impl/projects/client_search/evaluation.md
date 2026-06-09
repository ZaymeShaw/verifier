# Evaluation

Judge the current client_search API output by reconstructing expected-vs-actual from the current query, current response, and the current project prompt/config references from `projects/client_search`.

Project-owned source references:

- `projects/client_search/readme.md`: project-level judging instruction. 当前 source 明确：标准答案的答案结果由于数据库字段已经过时、跟 API 返回结果不一致，所以标准答案只能作为参考；judge 需要根据最新 `config.md` / `prompt.md` 要求进行实时标注，API 返回字段格式通常视为正确，重点关注值是否正确、引用字段是否合理，并从语义上判断是否能搜索出正确客户。
- `projects/client_search/config.md`: authoritative pointers to client_search config files, especially field definitions and enum definitions.
- `projects/client_search/prompt.md`: current prompt rules for condition generation, operators, age handling, unit conversion, AND/OR, and output format.

Quality requirements:

- Do not inherit previous cases, page state, clusters, or attribution conclusions.
- Re-understand the user's underlying intent before comparing conditions.
- Use the project judge boundary standard as the final verdict standard. For client_search, upstream ES database field/enum limitations are treated as system capability boundaries, while model, config, prompt, project code, field mapping, and post-processing errors remain evaluable system issues.
- Use `impl/projects/client_search/judge.md` as the project judge construction standard. It explains how the boundary protocol constrains expected-vs-actual judgment for client_search.
- Use current project prompt/config/business rules when available; the runtime judge request includes latest `projects/client_search/readme.md`, `config.md`, `prompt.md`, the project judge boundary content, and the project judge standard through project document references.
- Treat the API response shape as already normalized by the adapter unless the trace explicitly shows malformed data; the main judging target is whether returned values are semantically correct.
- Check whether selected fields, operators, enum values, unit conversions, boundary handling, and `query_logic` match the current user intent.
- Check whether the output covers the core user intent and can retrieve the intended customer set.
- Separate missing, wrong, and extra conditions.
- If response fields are structurally valid but semantically wrong, mark incorrect and explain why.
- If `structured_output` is empty while the user query is non-empty, treat this as an empty-recognition result, not a successful structured parse. The judge should evaluate whether the query should have produced conditions under current prompt/config rules and mark incorrect when the query intent is recognizable.
- Empty-result classification must use the best available source query from the API response (`rewritten_query`, original `query`, or equivalent request echo). Missing `rewritten_query` alone must not turn a non-empty request into `empty_query`; it should be `service_returned_no_conditions` when the service handled a non-empty query but returned no conditions.

Client_search-specific judging guidance from the current prompt:

- Only fields defined by the project configuration are valid.
- Enum fields must use configured enum values.
- Numeric/date fields use GTE/LTE/GT/LT/RANGE according to wording.
- `clientAge` has special boundary handling:
  - “50岁以上/及以上” => `GTE 50`.
  - “大于/超过50岁” => `GTE 51`.
  - exact age => `RANGE {min:x,max:x}`.
- Chinese units must be converted where explicit: `万=10000`, `千=1000`.
- Multiple different filters normally use `AND`; `OR` is only for explicit “或者/任一” semantics over independent conditions.
- The expected output shape is `query_logic` plus a list of `{field, operator, value}` conditions.

The adapter stores client_search response details in `project_fields`; judge may inspect them because this is the project evaluation spec, but generic core must not require those field names.
