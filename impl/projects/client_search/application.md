# Application

This project connects to an existing client search service described by the user-owned `projects/client_search/start.md`.

Startup checklist:

1. Start the business API service on port 8000.
2. Ensure ES is available and reindex fields when needed:

```bash
curl --location --request POST 'http://localhost:8000/api/v1/fields/reindex' \
--header 'Content-Type: application/json' \
--data-raw '{"force_reindex_fields": true}'
```

3. Verify the real request endpoint `/api/v1/client_search_query_parse_no_encipher`.
4. Run judge agent and attribute agent on the latest live request result.
5. Use check agent review to confirm service, protocol, and project docs stay aligned.

This startup flow is project-specific and must not be hardcoded in generic core code.
