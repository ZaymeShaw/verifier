#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8021/api/mock_datasets' -H 'Content-Type: application/json' --data-raw '{"project": "marketting-planning"}' --write-out '
__HTTP_STATUS__:%{http_code}'
