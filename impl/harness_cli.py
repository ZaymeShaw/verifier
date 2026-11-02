"""harness 侧 Session 工具 CLI（spec/mock/protocol.md 5.1）。

外部 agent 进程用它消费评测系统的 Session：只依赖标准库 + 服务地址，所有状态在服务端。

    python -m impl.harness_cli session open <project> [--mode text|protocol-fuzz] [--max-turns N] [--pool NAME] [--run-id ID] [--scenario S]
    python -m impl.harness_cli session send <session_id> --text "..." | --action NAME [--param k=v ...] | --request '<json>'
    python -m impl.harness_cli session intent <session_id> --user-intent "..." [--source seeded|adopted_from_inference|drifted] [--context '<json>']
    python -m impl.harness_cli session close <session_id> --reason goal_satisfied|user_abandons|perceived_no_progress
    python -m impl.harness_cli session list <project> [--run-id ID]
    python -m impl.harness_cli session get <project> <session_id>
    python -m impl.harness_cli judge <project> <session_id>
    python -m impl.harness_cli ledger add <project> --signature S --harness-verdict fulfilled|not_fulfilled [...]
    python -m impl.harness_cli ledger query <project> [--category C] [--run-id ID]
    python -m impl.harness_cli exploration get|list|report ...   # 探索方向领取 / 批次列表 / 交探索报告

输出一律是 JSON（一次调用一个对象），便于 agent 解析。非 0 退出码表示协议错误或服务端错误。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


def _default_server() -> str:
    from impl.core.config import get_runtime_config

    server = get_runtime_config().server
    return f"http://{server.host}:{server.port}"


def _post(server: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{server.rstrip('/')}{path}", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            return {"error": json.loads(detail).get("error") or detail, "status": exc.code}
        except Exception:
            return {"error": detail, "status": exc.code}
    except urllib.error.URLError as exc:
        return {"error": f"cannot reach verifier server at {server}: {exc.reason}"}


def _emit(result: Dict[str, Any]) -> int:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("error") else 0


def _json_arg(value: Optional[str]) -> Any:
    if not value:
        return None
    return json.loads(value)


def _params(items: Optional[list[str]]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for item in items or []:
        key, sep, raw = item.partition("=")
        if not sep:
            raise SystemExit(f"--param expects k=v, got {item!r}")
        try:
            params[key] = json.loads(raw)
        except json.JSONDecodeError:
            params[key] = raw
    return params


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default=None, help="verifier 服务地址；默认读 impl/config.yaml 的 server.host/port")
    sub = parser.add_subparsers(dest="cmd", required=True)

    session = sub.add_parser("session").add_subparsers(dest="action", required=True)

    p = session.add_parser("open")
    p.add_argument("project")
    p.add_argument("--mode", default="text", choices=("text", "protocol-fuzz"))
    p.add_argument("--max-turns", type=int, default=None)
    p.add_argument("--turn-wait-timeout-ms", type=int, default=None)
    p.add_argument("--session-timeout-ms", type=int, default=None)
    p.add_argument("--token-limit", type=int, default=None)
    p.add_argument("--seed-prefix", default=None, help="transcript 前缀 JSON（数组）")
    p.add_argument("--seed-mode", default=None, choices=("replay", "context"))
    p.add_argument("--pool", default="", help="导出 seed 的用例池名；默认 harness-<run-id> 或 harness")
    p.add_argument("--run-id", default="")
    p.add_argument("--scenario", default="")

    p = session.add_parser("send")
    p.add_argument("session_id")
    kind = p.add_mutually_exclusive_group(required=True)
    kind.add_argument("--text")
    kind.add_argument("--action", dest="action_name", metavar="NAME")
    kind.add_argument("--request", help="仅 protocol-fuzz 模式：REQUEST_SCHEMA JSON")
    p.add_argument("--param", action="append", help="action 参数 k=v，可重复")
    p.add_argument("--tokens", type=int, default=0, help="用户方自报本轮消耗 token")

    p = session.add_parser("intent")
    p.add_argument("session_id")
    p.add_argument("--user-intent", required=True)
    p.add_argument("--source", default="seeded", choices=("seeded", "adopted_from_inference", "drifted"))
    p.add_argument("--context", default=None, help="user_context JSON")

    p = session.add_parser("close")
    p.add_argument("session_id")
    p.add_argument("--reason", required=True, choices=("goal_satisfied", "user_abandons", "perceived_no_progress"))

    p = session.add_parser("list")
    p.add_argument("project")
    p.add_argument("--run-id", default="")

    p = session.add_parser("get")
    p.add_argument("project")
    p.add_argument("session_id")

    p = sub.add_parser("judge")
    p.add_argument("project")
    p.add_argument("session_id")

    ledger = sub.add_parser("ledger").add_subparsers(dest="action", required=True)
    p = ledger.add_parser("add")
    p.add_argument("project")
    p.add_argument("--signature", required=True)
    p.add_argument("--session-id", default="")
    p.add_argument("--trigger-summary", default="")
    p.add_argument("--realism", default="medium", choices=("high", "medium", "low"))
    p.add_argument("--harness-verdict", required=True, choices=("fulfilled", "not_fulfilled"))
    p.add_argument("--judge-verdict", default=None, choices=("fulfilled", "not_fulfilled", "not_evaluable"))
    p.add_argument("--protocol-fuzz", action="store_true")
    p.add_argument("--run-id", default="")
    p.add_argument("--notes", default="")
    p = ledger.add_parser("query")
    p.add_argument("project")
    p.add_argument("--category", default=None, choices=("live_defect", "judge_calibration", "protocol_fuzz"))
    p.add_argument("--signature", default=None)
    p.add_argument("--session-id", default=None)
    p.add_argument("--run-id", default=None)

    exploration = sub.add_parser("exploration").add_subparsers(dest="action", required=True)
    p = exploration.add_parser("get", help="领取探索方向 + 该批次已有会话与台账")
    p.add_argument("project")
    p.add_argument("run_id")
    p = exploration.add_parser("list")
    p.add_argument("project")
    p = exploration.add_parser("report", help="探索结束时交报告（5.1 形状的 JSON）")
    p.add_argument("project")
    p.add_argument("run_id")
    p.add_argument("--report", required=True, help="JSON：{sessions, findings, coverage, budget_usage, notes}")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    server = args.server or _default_server()

    if args.cmd == "session" and args.action == "open":
        budget = {
            key: value
            for key, value in {
                "max_turns": args.max_turns,
                "turn_wait_timeout_ms": args.turn_wait_timeout_ms,
                "session_timeout_ms": args.session_timeout_ms,
                "token_limit": args.token_limit,
            }.items()
            if value is not None
        }
        return _emit(_post(server, "/api/session/open", {
            "project": args.project,
            "mode": args.mode,
            "budget": budget,
            "seed_prefix": _json_arg(args.seed_prefix) or [],
            "seed_mode": args.seed_mode,
            "pool": args.pool,
            "run_id": args.run_id,
            "scenario": args.scenario,
        }))
    if args.cmd == "session" and args.action == "send":
        if args.text is not None:
            message = {"type": "text", "text": args.text}
        elif args.action_name is not None:
            message = {"type": "action", "name": args.action_name, "params": _params(args.param)}
        else:
            message = {"type": "request", "payload": _json_arg(args.request) or {}}
        return _emit(_post(server, "/api/session/send", {"session_id": args.session_id, "message": message, "tokens": args.tokens}))
    if args.cmd == "session" and args.action == "intent":
        return _emit(_post(server, "/api/session/intent", {
            "session_id": args.session_id,
            "user_intent": args.user_intent,
            "user_context": _json_arg(args.context) or {},
            "source": args.source,
        }))
    if args.cmd == "session" and args.action == "close":
        return _emit(_post(server, "/api/session/close", {"session_id": args.session_id, "stop_reason": args.reason}))
    if args.cmd == "session" and args.action == "list":
        return _emit(_post(server, "/api/session/list", {"project": args.project, "run_id": args.run_id}))
    if args.cmd == "session" and args.action == "get":
        return _emit(_post(server, "/api/session/get", {"project": args.project, "session_id": args.session_id}))
    if args.cmd == "judge":
        return _emit(_post(server, "/api/session/judge", {"project": args.project, "session_id": args.session_id}))
    if args.cmd == "ledger" and args.action == "add":
        return _emit(_post(server, "/api/ledger/add", {
            "project": args.project,
            "signature": args.signature,
            "session_id": args.session_id,
            "trigger_summary": args.trigger_summary,
            "realism": args.realism,
            "harness_verdict": args.harness_verdict,
            "judge_verdict": args.judge_verdict,
            "protocol_fuzz": args.protocol_fuzz,
            "run_id": args.run_id,
            "notes": args.notes,
        }))
    if args.cmd == "exploration" and args.action == "get":
        return _emit(_post(server, "/api/exploration/get", {"project": args.project, "run_id": args.run_id}))
    if args.cmd == "exploration" and args.action == "list":
        return _emit(_post(server, "/api/exploration/list", {"project": args.project}))
    if args.cmd == "exploration" and args.action == "report":
        return _emit(_post(server, "/api/exploration/report", {
            "project": args.project, "run_id": args.run_id, "report": _json_arg(args.report) or {},
        }))
    if args.cmd == "ledger" and args.action == "query":
        return _emit(_post(server, "/api/ledger/query", {
            "project": args.project,
            "category": args.category,
            "signature": args.signature,
            "session_id": args.session_id,
            "run_id": args.run_id,
        }))
    build_parser().print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
