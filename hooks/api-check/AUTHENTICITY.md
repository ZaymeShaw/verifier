# API Check Authenticity Requirements

API check reports are audit artifacts. They must record what actually happened, not a convenient reconstruction.

## Hard requirements

1. **Real schema**
   - Request and response payloads must use the current public API schema accepted by `impl/server/models.py` and normalized by the API service.
   - If a fixture exposes fields that the public API does not accept, that mismatch is a real finding to fix or report; do not hide it in the report.

2. **Real mock/fixture data**
   - Request bodies must be built from the same fixture/project/mock data that is passed to the API call.
   - Do not replace report payloads with smaller examples unless the row is explicitly marked as an example, not a test result.

3. **Real API calls**
   - Every report row must execute the API route for that row.
   - Do not use cached/reused responses as row results.
   - `source` must make the execution origin explicit.

4. **Real curl**
   - The `curl` column must represent the same method, URL, headers, and JSON request body used for that row's API call.
   - Do not encode the body into opaque base64 just to make copying easier.
   - Do not invent a different replay command from the actual request.
   - If a curl is too large for Excel, leave the limitation visible and point to the exact `request_body` cell as the real body source.

5. **Real response**
   - `response_body`, `http_status`, `schema_check`, and `schema_error` must come from the actual API invocation for that row.
   - A non-200 response or schema failure is useful signal and should remain visible in the report.

## Practical rule

Prefer truthful, visual, debuggable records over cosmetically passing reports. If a copied curl exposes an API/schema bug, fix the bug or report the failing row; do not transform the curl/report to avoid the failure.
