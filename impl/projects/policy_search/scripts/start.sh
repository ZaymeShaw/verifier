#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
verifier_root="$(cd -- "${script_dir}/../../../.." && pwd)"
verifier_env="${verifier_root}/.env"

if [[ -f "${verifier_env}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${verifier_env}"
  set +a
fi

: "${POLICY_SEARCH_REPO:?POLICY_SEARCH_REPO must be configured in ${verifier_env} or the process environment}"
if [[ -z "${BAILIAN_API_KEY:-}" ]]; then
  echo "BAILIAN_API_KEY must be configured in ${verifier_env}" >&2
  exit 1
fi

export DASHSCOPE_API_KEY="${BAILIAN_API_KEY}"

exec "${POLICY_SEARCH_REPO}/.venv/bin/uvicorn" main:main_app \
  --app-dir "${POLICY_SEARCH_REPO}" \
  --host 127.0.0.1 \
  --port 8050
