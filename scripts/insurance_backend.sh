#!/usr/bin/env bash
# 启动 insurance-qa-agent 评测工作树（eval/current，dev 环境配置，工具层已是 real-only），
# 供 llm_probe 的 insurance-agno-e2e 场景评测。
#
# 代码取评测工作树而不是同事主仓库：评测分支带 X-Eval-Case-Id / X-Eval-Execution-Id 透传
# （IQA_EVAL_HEADER_PASSTHROUGH），llmtracing 才能按请求精确归属模型调用。
# 启动交给 llmtracing 的 start_insurance_qa_local.py：它负责把 import 固定到评测工作树
# （主仓库 .feval_venv 的 editable finder 会把 app 指回主仓库），并写 server-<port>.meta.json。
# 这里关掉它的 upstream align（会 fetch/重放上游），评测代码只在显式 sync 时变化。
#
#   scripts/insurance_backend.sh start|stop|status|log
#
# 端口、Agno SQLite 路径与 impl/data/llm_probe/capability_map.json 里 insurance-agno-e2e 的
# service.url / business_trace.config 保持一致；改这里要同步改那边。
#
# business_trace 的过程轴依赖 Agno 的 LLM/TOOL span，上游 dev 配置默认 tracing_enabled: false，
# 评测分支的 local(eval) 提交已把 app/conf/harness/harness_dev_args.yaml 改为 true（sync 后要检查这一行）。
# 启动前校验，关着就拒绝起，免得跑一批评测才发现模型调用记录全空。
#
# 模型出口同样启动前校验：app 的 base_url 指向本机 litellm 网关，网关没起时每轮都是
# ModelProviderError → 业务返回「模型服务繁忙」降级文案，评测侧只能判 not_evaluable，
# 现象跟「模型能力不行」一模一样，跑完一批才发现。
#
# /health 是 agno 内置的 liveness：恒定返回 {"status":"ok","instantiated_at":...}，
# 只证明端口绑上了，不反映工具后端/agent 注册表的真实状态。所以就绪判据用一条真查询：
# require_business_ready。start 每次都重启（旧实例按端口停掉），新实例必须过这个探针。
#
# NO_PROXY 必须带上：macOS 开了系统代理时，httpx(trust_env) 会经 urllib.getproxies() 读到它，
# app 打 127.0.0.1 网关的请求被塞进代理 → 502，而网关本身是好的（直连 200）。
set -euo pipefail

AGENT_DIR="/Users/xiaozijian/WorkSpace/package/insurance_qa_agent/insurance-qa-agent-eval"
# 评测工作树没有自己的 venv，复用主仓库的；import 路径由 STARTER 固定到 AGENT_DIR。
PY="/Users/xiaozijian/WorkSpace/package/insurance_qa_agent/insurance-qa-agent/.feval_venv/bin/python"
STARTER="/Users/xiaozijian/WorkSpace/package/llmtracing/scripts/start_insurance_qa_local.py"
# 18063 是 llmtracing eval_harness 独占实例；verifier 必须留在自己的实例上。
PORT=18062
STATE_DIR="$HOME/.insurance-qa-agent-real"
DB_FILE="$STATE_DIR/runtime-real.db"
HARNESS_CFG="$AGENT_DIR/app/conf/harness/harness_dev_args.yaml"
MODEL_CFG="$AGENT_DIR/app/conf/models/models_dev_args.yaml"
# 本机模型网关必须直连，绕过系统代理；外部已有 NO_PROXY 时以外部为准。
NO_PROXY="${NO_PROXY:-127.0.0.1,localhost,::1}"
no_proxy="${no_proxy:-$NO_PROXY}"
export NO_PROXY no_proxy
GATEWAY_DIR="/Users/xiaozijian/WorkSpace/package/llmtracing/llm_gateway"
# verifier 独占网关（insurance_4002 留给 llmtracing :18063）；通过 INSURANCE_QA_MODEL_BASE_URL 覆盖 yaml 里的 base_url。
GATEWAY_PROFILE="insurance_verifier_4202"
MODEL_BASE_URL="http://127.0.0.1:4202/v1"
# STARTER 按端口写 pid/meta，退出时自行清理。
PID_FILE="$STATE_DIR/server-$PORT.pid"
META_FILE="$STATE_DIR/server-$PORT.meta.json"
LOG_FILE="$STATE_DIR/server.log"

mkdir -p "$STATE_DIR"

require_tracing() {
  grep -q '^tracing_enabled: true$' "$HARNESS_CFG" && return 0
  echo "$HARNESS_CFG 里 tracing_enabled 不是 true，评测拿不到模型调用 span；改成 true 再启。"
  return 1
}

require_model_gateway() {
  local url host port
  url="$MODEL_BASE_URL"
  if [[ -z "$url" ]]; then
    echo "$MODEL_CFG 里没读到 base_url，无法校验模型网关。"; return 1
  fi
  host="$(sed -E 's#^[A-Za-z0-9+.~-]+://##; s#[:/].*$##' <<<"$url")"
  port="$(sed -nE 's#^[A-Za-z0-9+.~-]+://[^:/]+:([0-9]+).*#\1#p' <<<"$url")"
  [[ -n "$port" ]] || port=80
  if ! nc -z -w 3 "$host" "$port" >/dev/null 2>&1; then
    echo "模型网关不可达：$host:$port（MODEL_BASE_URL=$url）。"
    echo "先起保险专用网关：cd $GATEWAY_DIR && ./start_insurance_litellm.sh --profile $GATEWAY_PROFILE"
    return 1
  fi
  echo "model gateway ok: $host:$port"
}

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

# STARTER 的 meta 记录实际跑的代码根与透传开关；不是评测工作树或透传没开就拒绝，
# 否则 llmtracing 拿不到请求级归属，模型调用会退到 lane 或未归属。
require_passthrough() {
  "$PY" - "$META_FILE" "$AGENT_DIR" <<'PYEOF' && return 0
import json, sys
meta = json.load(open(sys.argv[1]))
sys.exit(0 if meta.get("root") == sys.argv[2] and meta.get("eval_header_passthrough") is True else 1)
PYEOF
  echo "$META_FILE 显示实例不是评测工作树或未开启评测头透传；拒绝使用。"
  return 1
}

# 就绪探针：一条真实业务查询。工具层 timeout_s=75 且带重试，预算按长任务下限给到 300s。
# 探针主体必须跟 mock_cases.json 同一批数据（当前 0922），否则整批用例跑出来全是空结果。
# 用客户号提问、断言人名：各批次客户姓名完全相同（5000 名一模一样），只有 clientno/polno
# 带批次前缀（C922…/P260922…），按姓名探会被上一批的同名者误判为就绪。
# 客户号取自 mock_cases.json 的 smoke-customer-bizno 用例（何承琪 C92200000884）。
PROBE_QUERY="客户号C92200000884对应的客户是谁？"
PROBE_EXPECT="何承琪"
PROBE_TIMEOUT=300
# 上游是逐请求抖动的（同一句查询好/坏交替），单次探针等于抛硬币，连过 3 次才算就绪。
PROBE_PASSES=3
# 降级文案：意味着上游工具/模型/数据没真正干活，不是业务真实答复。取自 context_store 里的实际频次：
# 本次工具调用失败 ×363 / 未检索到符合条件的保单 ×142 / 暂不支持自动检索 ×141 / 查询服务暂时异常 ×51。
PROBE_DEGRADED=("本次工具调用失败" "未检索到符合条件的保单" "暂不支持自动检索" "查询服务暂时异常" "未命中任何保单记录" "Step agent failed but skipped" "服务繁忙")

require_business_ready() {
  local i
  for ((i = 1; i <= PROBE_PASSES; i++)); do
    echo "readiness 探针 $i/${PROBE_PASSES} …"
    probe_once || return 1
  done
  echo "business ready: 连续 ${PROBE_PASSES} 次探针查询都拿到正常答复"
}

# 探针请求前记下 trace 水位，用来判断这次请求到底有没有落 span。
trace_watermark() {
  sqlite3 "$DB_FILE" 'SELECT IFNULL(MAX(rowid),0) FROM agno_traces;' 2>/dev/null || echo 0
}

# 请求返回后新落的 span 数（span 是异步写的，轮询给 20s 窗口）。
new_span_count() {
  sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM agno_spans WHERE trace_id IN (SELECT trace_id FROM agno_traces WHERE rowid > $1);" 2>/dev/null || echo 0
}

probe_once() {
  local raw code resp bad before n i
  before="$(trace_watermark)"
  raw="$(curl -s -m "${PROBE_TIMEOUT}" -w $'\n%{http_code}' \
    -X POST "http://127.0.0.1:$PORT/v1/chat" -H 'Content-Type: application/json' \
    -d "{\"session_id\":\"readiness-probe-$(date +%s)\",\"user_id\":\"1050900009\",\"empno\":\"1050900009\",\"agentno\":\"1050900009\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"${PROBE_QUERY}\"}]}")" \
    || { echo "readiness 探针请求失败（服务不可达或超时 ${PROBE_TIMEOUT}s）"; return 1; }
  code="${raw##*$'\n'}"; resp="${raw%$'\n'*}"
  if [[ "$code" != 200 ]]; then
    echo "readiness 探针 HTTP $code"; head -c 400 <<<"$resp"; echo; return 1
  fi
  for bad in "${PROBE_DEGRADED[@]}"; do
    if grep -q "$bad" <<<"$resp"; then
      echo "readiness 探针拿到降级答复（命中「$bad」）——上游工具/模型不可用："
      head -c 400 <<<"$resp"; echo
      return 1
    fi
  done
  # 业务 trace 必须真的落库：过程轴读的是 Agno span，而数据类答复的响应体里不带 trace 引用
  # （fact_refs 为空、trace_id 为 null 是正常现象），所以直接查库，别拿响应体当凭据。
  n=0
  for ((i = 0; i < 10; i++)); do
    n="$(new_span_count "$before")"; [[ "$n" -ge 1 ]] && break; sleep 2
  done
  if [[ "$n" -lt 1 ]]; then
    echo "readiness 探针答复正常，但本次请求没有往 $DB_FILE 写任何 span——过程轴会拿不到证据。"
    return 1
  fi
  grep -q "${PROBE_EXPECT}" <<<"$resp" || {
    echo "readiness 探针没查到 fixture 所需的数据（期望答复里出现「${PROBE_EXPECT}」）——"
    echo "  说明线上加载的不是 ${PROBE_QUERY} 所属批次；此时跑用例只会得到全空结果。"
    head -c 400 <<<"$resp"; echo; return 1
  }
}

# 端口上的监听进程不一定是本脚本起的（旧版本脚本或手工启动的实例），只认 PID_FILE 会漏停；漏停时新进程绑不上端口，/health 却打到旧进程上，误报启动成功。
port_pids() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true
}

# 每次 start 都重启：先确认 tracing 与模型网关可用，不可用时不动正在跑的服务。
start() {
  require_tracing
  require_model_gateway
  if is_running || [[ -n "$(port_pids)" ]]; then
    echo "restarting: 停掉 :$PORT 上的旧实例"
    stop || return 1
  fi
  # 双重 fork + 新会话：脱离调用方的进程组，调用方 shell 退出后服务继续活着。
  (
    ENV_TYPE=dev NO_PROXY="$NO_PROXY" no_proxy="$no_proxy" \
    INSURANCE_QA_ROOT="$AGENT_DIR" INSURANCE_QA_PORT="$PORT" INSURANCE_QA_DB="$DB_FILE" \
    INSURANCE_QA_MODEL_BASE_URL="$MODEL_BASE_URL" \
    INSURANCE_UPSTREAM_ALIGN=0 IQA_EVAL_HEADER_PASSTHROUGH=1 \
    nohup "$PY" -c "
import os, runpy
os.setsid()  # 自成会话/进程组，调用方清理其进程组时不受影响
runpy.run_path('$STARTER', run_name='__main__')
" </dev/null >"$LOG_FILE" 2>&1 &
    disown
  )
  sleep 1
  for _ in $(seq 1 40); do
    if curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      require_passthrough || return 1
      echo "started pid $(cat "$PID_FILE") on :$PORT"
      echo "db: $DB_FILE"
      curl -s "http://127.0.0.1:$PORT/config" | head -c 1500; echo
      require_business_ready || { echo "端口通了但业务探针不过；tail of log:"; tail -40 "$LOG_FILE"; return 1; }
      return 0
    fi
    sleep 1
  done
  echo "failed to become healthy; tail of log:"; tail -40 "$LOG_FILE"; return 1
}

stop() {
  local pids
  pids="$(port_pids)"
  if is_running; then pids="$(cat "$PID_FILE") $pids"; fi
  rm -f "$PID_FILE"
  if [[ -z "${pids// /}" ]]; then echo "not running"; return 0; fi
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 30); do
    [[ -z "$(port_pids)" ]] && { echo "stopped"; return 0; }
    sleep 1
  done
  echo ":$PORT 上的进程 30s 内未退出：$(port_pids | tr '\n' ' ')"
  return 1
}

status() {
  if is_running; then
    echo "running pid $(cat "$PID_FILE")"
    curl -s -m 3 "http://127.0.0.1:$PORT/health"; echo
  else
    echo "not running"
  fi
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) start ;;
  status) status ;;
  log) tail -n "${2:-80}" "$LOG_FILE" ;;
  *) echo "usage: $0 start|stop|restart|status|log [n]"; exit 2 ;;
esac
