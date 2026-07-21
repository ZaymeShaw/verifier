#!/usr/bin/env bash
set -euo pipefail

: "${DEERFLOW_REPO:?DEERFLOW_REPO must be registered in project.yaml and provided via .env or process environment}"

exec bash "${DEERFLOW_REPO}/report/deploy.sh"
