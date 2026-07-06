#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/analysis' -H 'Content-Type: application/json' --data-raw '{"project": "client_search"}' --write-out '
__HTTP_STATUS__:%{http_code}'
