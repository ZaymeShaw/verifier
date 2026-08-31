#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFIER_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
ENV_FILE="${VERIFIER_ROOT}/.env"
RUNTIME_DIR="${VERIFIER_ROOT}/tmp/client_search-runtime"
PID_FILE="${RUNTIME_DIR}/service.pid"
LOG_FILE="${RUNTIME_DIR}/service.log"
RUNNER_FILE="${RUNTIME_DIR}/service-runner.sh"
LAUNCHD_LABEL="${CLIENT_SEARCH_LAUNCHD_LABEL:-com.verifier.client-search.8000}"
LAUNCHD_DOMAIN="gui/$(id -u)"
PORT="${CLIENT_SEARCH_PORT:-8000}"
BASE_URL="${CLIENT_SEARCH_BASE_URL:-http://127.0.0.1:${PORT}}"
STARTUP_TIMEOUT_SECONDS="${CLIENT_SEARCH_STARTUP_TIMEOUT_SECONDS:-240}"
REQUEST_TIMEOUT_SECONDS="${CLIENT_SEARCH_REQUEST_TIMEOUT_SECONDS:-120}"
REINDEX_TIMEOUT_SECONDS="${CLIENT_SEARCH_REINDEX_TIMEOUT_SECONDS:-360}"

usage() {
  cat <<USAGE
Usage: $0 {start|stop|restart|status|logs}

Environment overrides:
  CLIENT_SEARCH_REPO                    Business repository (normally loaded from verifier/.env)
  PYTHON_EXECUTABLE                     Python used to start the business service
  CLIENT_SEARCH_PORT                    Service port (default: 8000)
  CLIENT_SEARCH_BASE_URL                Service URL (default: http://127.0.0.1:<port>)
  CLIENT_SEARCH_STARTUP_TIMEOUT_SECONDS Startup/liveness wait timeout (default: 240)
  CLIENT_SEARCH_REINDEX_TIMEOUT_SECONDS Force field reindex wait timeout (default: 360)
  CLIENT_SEARCH_REQUEST_TIMEOUT_SECONDS Parse request timeout (default: 120)
  CLIENT_SEARCH_LAUNCHD_LABEL             macOS launchd label
USAGE
}

load_environment() {
  if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
  fi

  : "${CLIENT_SEARCH_REPO:?CLIENT_SEARCH_REPO must be configured in ${ENV_FILE} or the process environment}"
  CLIENT_SEARCH_REPO="$(cd "${CLIENT_SEARCH_REPO}" && pwd)"
  APP_DIR="${CLIENT_SEARCH_REPO}/src/main/python"
  MAIN_FILE="${APP_DIR}/main.py"
  ROUTE_FILE="${APP_DIR}/api/client_search_query_parse_post.py"
  PYTHON_BIN="${PYTHON_EXECUTABLE:-}"

  if [[ -z "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(python -c 'from impl.core.config import get_python_config; print(get_python_config().executable)' 2>/dev/null || true)"
  fi
  if [[ -z "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
  fi

  [[ -d "${CLIENT_SEARCH_REPO}/.git" ]] || {
    echo "client_search repository is missing or is not a Git checkout: ${CLIENT_SEARCH_REPO}" >&2
    exit 1
  }
  [[ -f "${MAIN_FILE}" && -f "${ROUTE_FILE}" ]] || {
    echo "client_search service entrypoint is missing under: ${APP_DIR}" >&2
    exit 1
  }
  [[ -n "${PYTHON_BIN}" && -x "${PYTHON_BIN}" ]] || {
    echo "Python executable is unavailable: ${PYTHON_BIN:-<empty>}" >&2
    exit 1
  }

  mkdir -p "${RUNTIME_DIR}"

  STARTUP_TIMEOUT_SECONDS="${CLIENT_SEARCH_STARTUP_TIMEOUT_SECONDS:-240}"
  REQUEST_TIMEOUT_SECONDS="${CLIENT_SEARCH_REQUEST_TIMEOUT_SECONDS:-120}"
  REINDEX_TIMEOUT_SECONDS="${CLIENT_SEARCH_REINDEX_TIMEOUT_SECONDS:-360}"
}

listener_pids() {
  lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true
}

launchd_available() {
  [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1
}

launchd_service_loaded() {
  launchd_available && launchctl print "${LAUNCHD_DOMAIN}/${LAUNCHD_LABEL}" >/dev/null 2>&1
}

launchd_job_pid() {
  launchctl print "${LAUNCHD_DOMAIN}/${LAUNCHD_LABEL}" 2>/dev/null |
    awk '/^[[:space:]]*pid = / { print $3; exit }'
}

remove_launchd_service() {
  if launchd_service_loaded; then
    launchctl remove "${LAUNCHD_LABEL}" >/dev/null 2>&1 || true
  fi
}

write_service_runner() {
  {
    printf '#!/usr/bin/env bash\n'
    printf 'cd %q\n' "${APP_DIR}"
    printf 'exec env PYTHONUNBUFFERED=1 API_PORT=%q %q main.py\n' "${PORT}" "${PYTHON_BIN}"
  } > "${RUNNER_FILE}"
  chmod 700 "${RUNNER_FILE}"
}

pid_cwd() {
  local pid="$1"
  lsof -a -p "${pid}" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1
}

is_client_search_process() {
  local pid="$1"
  local cwd
  cwd="$(pid_cwd "${pid}")"
  [[ -n "${cwd}" ]] || return 1
  [[ -f "${cwd}/src/main/python/api/client_search_query_parse_post.py" ]] || \
    [[ -f "${cwd}/api/client_search_query_parse_post.py" ]]
}

wait_for_process_exit() {
  local pid="$1"
  local attempts=30
  while kill -0 "${pid}" 2>/dev/null && (( attempts > 0 )); do
    sleep 1
    attempts=$((attempts - 1))
  done
  if kill -0 "${pid}" 2>/dev/null; then
    echo "process ${pid} did not stop after 30 seconds" >&2
    return 1
  fi
}

stop_managed_service() {
  if launchd_service_loaded; then
    echo "stopping launchd service ${LAUNCHD_LABEL}"
    remove_launchd_service
  fi

  local pids=""
  if [[ -f "${PID_FILE}" ]]; then
    pids="$(cat "${PID_FILE}" 2>/dev/null || true)"
  fi
  if [[ -z "${pids}" ]] || ! kill -0 "${pids}" 2>/dev/null; then
    pids="$(listener_pids)"
  fi

  if [[ -z "${pids}" ]]; then
    rm -f "${PID_FILE}"
    echo "client_search service is not running"
    return 0
  fi

  local pid
  for pid in ${pids}; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      continue
    fi
    if [[ -f "${PID_FILE}" ]] || is_client_search_process "${pid}"; then
      echo "stopping client_search pid=${pid} cwd=$(pid_cwd "${pid}")"
      kill "${pid}"
      wait_for_process_exit "${pid}"
    else
      echo "refusing to stop unknown process pid=${pid} on port ${PORT}; cwd=$(pid_cwd "${pid}")" >&2
      exit 1
    fi
  done
  rm -f "${PID_FILE}"
}

require_elasticsearch() {
  local es_url="${ES_HOST:-http://127.0.0.1:9200}"
  if ! curl -fsS --max-time 5 "${es_url}" >/dev/null; then
    echo "Elasticsearch is unavailable at ${es_url}; start.md requires it before client_search startup" >&2
    exit 1
  fi
  echo "Elasticsearch ready: ${es_url}"
}

service_exited() {
  if [[ -f "${PID_FILE}" ]]; then
    local pid
    pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && ! kill -0 "${pid}" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

fail_with_logs() {
  echo "$1" >&2
  echo "--- reload/reindex log ---" >&2
  grep -E "Deleted old index|Indexed .* intents|force_reindex_fields|配置热更新|Query router background" "${LOG_FILE}" 2>/dev/null | tail -n 30 >&2 || true
  echo "--- last log lines ---" >&2
  tail -n 20 "${LOG_FILE}" >&2 || true
  return 1
}

clear_stale_reload_marker() {
  local marker_dir="${APP_DIR}/config/client_search_query_parse"
  local marker="${marker_dir}/.client_search_runtime_reload.json"
  if [[ -f "${marker}" ]]; then
    echo "removing stale runtime reload marker: ${marker}"
    rm -f "${marker}"
  fi
  rm -f "${marker_dir}"/.client_search_runtime_reload.*.tmp
}

inspect_reload_health() {
  local mode="$1"
  local body="$2"
  printf '%s' "${body}" | "${PYTHON_BIN}" -c '
import json, sys

mode = sys.argv[1]
try:
    body = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)

def looks_like_reload_status(payload):
    return isinstance(payload, dict) and (
        "reload_running" in payload or "last_reload_result" in payload
    )

readiness = None
if looks_like_reload_status(body.get("readiness")):
    readiness = body["readiness"]
else:
    detail = body.get("detail")
    if looks_like_reload_status(detail.get("readiness") if isinstance(detail, dict) else None):
        readiness = detail["readiness"]
    elif looks_like_reload_status(detail):
        readiness = detail
if not isinstance(readiness, dict):
    raise SystemExit(1)

running = bool(readiness.get("reload_running"))
error = readiness.get("last_reload_error")
result = readiness.get("last_reload_result")
if not isinstance(result, dict):
    result = {}
force = result.get("force_reindex_fields") is True

if running:
    raise SystemExit(2)
if mode == "force_done":
    if error:
        print(error)
        raise SystemExit(4)
    if not force:
        raise SystemExit(3)
print(json.dumps({
    "reload_running": running,
    "force_reindex_fields": force,
    "field_intent_total": result.get("field_intent_total"),
}, ensure_ascii=False))
' "${mode}"
}

fetch_health_body() {
  curl -sS --max-time 10 "${BASE_URL}/health" 2>/dev/null || true
}

wait_for_reload_health() {
  local mode="$1"
  local deadline="$2"
  local message="$3"
  echo "${message}"
  while (( SECONDS < deadline )); do
    if service_exited; then
      fail_with_logs "client_search exited while waiting for field reindex"
      return 1
    fi
    local body status=0
    body="$(fetch_health_body)"
    if [[ -n "${body}" ]]; then
      local output=""
      output="$(inspect_reload_health "${mode}" "${body}")" && {
        echo "${output}"
        return 0
      } || status=$?
      if [[ "${status}" -eq 4 ]]; then
        fail_with_logs "field reindex failed: ${output:-unknown error}"
        return 1
      fi
    fi
    sleep 2
  done
  fail_with_logs "timed out waiting for field reindex (${mode}); last log lines:"
  return 1
}

submit_field_reindex() {
  local response
  response="$(curl -sS --fail --max-time 30 -X POST \
    -H 'Content-Type: application/json' \
    --data '{"force_reindex_fields":true}' \
    "${BASE_URL}/api/v1/fields/reindex")" || return 1
  printf '%s' "${response}" | "${PYTHON_BIN}" -c '
import json, sys
body = json.load(sys.stdin)
if body.get("success") is not True:
    raise SystemExit("field reindex rejected: %s" % body)
if body.get("started") is True:
    print("field reindex started")
    raise SystemExit(0)
print("field reindex reused existing reload; waiting to retry")
raise SystemExit(2)
'
}

wait_for_liveness() {
  local url="$1"
  local deadline=$((SECONDS + STARTUP_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 10 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    if [[ -f "${PID_FILE}" ]]; then
      local pid
      pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
      if [[ -n "${pid}" ]] && ! kill -0 "${pid}" 2>/dev/null; then
        echo "client_search exited before becoming ready; last log lines:" >&2
        tail -n 100 "${LOG_FILE}" >&2 || true
        return 1
      fi
    fi
    sleep 2
  done
  echo "timed out waiting for ${url}; last log lines:" >&2
  tail -n 100 "${LOG_FILE}" >&2 || true
  return 1
}

reindex_fields() {
  local deadline=$((SECONDS + REINDEX_TIMEOUT_SECONDS))
  echo "submitting field reindex (timeout=${REINDEX_TIMEOUT_SECONDS}s)"

  while (( SECONDS < deadline )); do
    if service_exited; then
      fail_with_logs "client_search exited before field reindex was submitted"
      return 1
    fi

    local submit_rc=0
    submit_field_reindex || submit_rc=$?
    if [[ "${submit_rc}" -eq 0 ]]; then
      wait_for_reload_health "force_done" "${deadline}" "waiting for force field reindex to finish" || return 1
      echo "field reindex completed"
      return 0
    fi
    if [[ "${submit_rc}" -ne 2 ]]; then
      fail_with_logs "field reindex request failed"
      return 1
    fi
    wait_for_reload_health "idle" "${deadline}" "waiting for in-flight reload to finish before retrying reindex" || return 1
  done

  fail_with_logs "timed out submitting force field reindex; last log lines:"
  return 1
}

verify_parse_endpoint() {
  local trace_id="start-check-$(date +%s)"
  local payload
  payload="$(printf '{"source":"verifier-start","user_text":"大于50岁的客户","session_id":"verifier-start","trace_id":"%s","user_id":"verifier","user_action":"write","action_scenario":"customerSearch","extra_input_params":{}}' "${trace_id}")"
  local deadline=$((SECONDS + STARTUP_TIMEOUT_SECONDS))

  echo "waiting for client_search parse endpoint"
  while (( SECONDS < deadline )); do
    local response
    response="$(curl -sS --max-time "${REQUEST_TIMEOUT_SECONDS}" \
      -H 'Content-Type: application/json' \
      --data "${payload}" \
      "${BASE_URL}/api/v1/client_search_query_parse_no_encipher" 2>/dev/null || true)"
    if [[ -n "${response}" ]] && printf '%s' "${response}" | "${PYTHON_BIN}" -c '
import json, sys
try:
    body = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
if body.get("code") != 0 or not isinstance(body.get("data"), dict):
    raise SystemExit(1)
extra = body["data"].get("extra_output_params") or {}
print("parse endpoint ready:", json.dumps({
    "query_logic": extra.get("query_logic"),
    "conditions": extra.get("conditions"),
    "matched_level": extra.get("matched_level"),
}, ensure_ascii=False))
'; then
      return 0
    fi

    if [[ -f "${PID_FILE}" ]]; then
      local pid
      pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
      if [[ -n "${pid}" ]] && ! kill -0 "${pid}" 2>/dev/null; then
        echo "client_search exited before the parse endpoint became ready; last log lines:" >&2
        tail -n 100 "${LOG_FILE}" >&2 || true
        return 1
      fi
    fi
    sleep 2
  done

  echo "timed out waiting for the client_search parse endpoint; last log lines:" >&2
  tail -n 100 "${LOG_FILE}" >&2 || true
  return 1
}

start_service() {
  require_elasticsearch

  local existing
  existing="$(listener_pids)"
  if [[ -n "${existing}" ]]; then
    echo "port ${PORT} is occupied; replacing the existing client_search service"
    stop_managed_service
  fi

  : > "${LOG_FILE}"
  echo "starting client_search"
  echo "  repository: ${CLIENT_SEARCH_REPO}"
  echo "  python:     ${PYTHON_BIN}"
  echo "  url:        ${BASE_URL}"
  echo "  log:        ${LOG_FILE}"

  clear_stale_reload_marker
  rm -f "${PID_FILE}"
  local pid=""
  if launchd_available; then
    remove_launchd_service
    write_service_runner
    launchctl submit -l "${LAUNCHD_LABEL}" -o "${LOG_FILE}" -e "${LOG_FILE}" -- "${RUNNER_FILE}"
    local attempts=20
    while [[ -z "${pid}" && ${attempts} -gt 0 ]]; do
      pid="$(launchd_job_pid || true)"
      [[ -n "${pid}" ]] || sleep 0.25
      attempts=$((attempts - 1))
    done
    [[ -n "${pid}" ]] && echo "${pid}" > "${PID_FILE}"
  else
    (
      cd "${APP_DIR}"
      nohup env PYTHONUNBUFFERED=1 API_PORT="${PORT}" "${PYTHON_BIN}" main.py \
        </dev/null >>"${LOG_FILE}" 2>&1 &
      echo "$!" > "${PID_FILE}"
    )
    pid="$(cat "${PID_FILE}")"
  fi

  wait_for_liveness "${BASE_URL}/"
  echo "client_search liveness check passed"
  reindex_fields
  verify_parse_endpoint
  pid="$(listener_pids | head -1)"
  [[ -n "${pid}" ]] && echo "${pid}" > "${PID_FILE}"
  echo "client_search startup completed (pid=${pid:-unknown})"
}

show_status() {
  local pids
  pids="$(listener_pids)"
  if [[ -z "${pids}" ]]; then
    echo "client_search is stopped (port ${PORT} is not listening)"
    return 1
  fi
  echo "client_search listener pid(s): ${pids}"
  local pid
  for pid in ${pids}; do
    echo "  pid=${pid} cwd=$(pid_cwd "${pid}")"
  done

  # /health 的自探测路径按线上网关前缀写死，本地部署恒为 503；
  # 这里改从 body 里提取 reload 状态，另用解析接口判断实际可用性。
  local health_body
  health_body="$(fetch_health_body)"
  if [[ -n "${health_body}" ]]; then
    local reload_summary
    if reload_summary="$(inspect_reload_health "idle" "${health_body}")"; then
      echo "runtime reload status: ${reload_summary}"
    else
      echo "runtime reload status: reload in progress or unavailable"
    fi
  else
    echo "health endpoint unreachable"
  fi

  local probe_response
  probe_response="$(curl -sS --max-time 30 \
    -H 'Content-Type: application/json' \
    --data '{"source":"verifier-status","user_text":"大于50岁的客户","session_id":"verifier-status","trace_id":"verifier-status","user_id":"verifier","user_action":"write","action_scenario":"customerSearch","extra_input_params":{}}' \
    "${BASE_URL}/api/v1/client_search_query_parse_no_encipher" 2>/dev/null || true)"
  if [[ -n "${probe_response}" ]] && printf '%s' "${probe_response}" | "${PYTHON_BIN}" -c '
import json, sys
try:
    body = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if body.get("code") == 0 else 1)
'; then
    echo "parse endpoint: OK"
  else
    echo "parse endpoint: NOT responding correctly"
    return 1
  fi
}

show_logs() {
  [[ -f "${LOG_FILE}" ]] || {
    echo "log file does not exist: ${LOG_FILE}" >&2
    exit 1
  }
  tail -n 200 -f "${LOG_FILE}"
}

main() {
  local command="${1:-start}"
  load_environment
  case "${command}" in
    start) start_service ;;
    stop) stop_managed_service ;;
    restart) stop_managed_service; start_service ;;
    status) show_status ;;
    logs) show_logs ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
  esac
}

main "$@"
