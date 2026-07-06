#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/mock_cases' -H 'Content-Type: application/json' --data-raw '{"project": "QA"}' --write-out '
__HTTP_STATUS__:%{http_code}'
