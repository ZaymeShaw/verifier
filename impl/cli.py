from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.pipeline import run_chain
from .core.project_loader import list_projects
from .core.schema import AttributeResult, JudgeResult, RunTrace, to_dict
from .core import pipeline


def load_json_arg(value: str):
    if value.lstrip().startswith(("{", "[")):
        return json.loads(value)
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def emit(value):
    print(json.dumps(to_dict(value), ensure_ascii=False, indent=2))


def trace_from_json(data) -> RunTrace:
    return RunTrace(**data)


def judge_from_json(data) -> JudgeResult:
    return JudgeResult(**data)


def attribute_from_json(data) -> AttributeResult:
    return AttributeResult(**data)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generic evaluation protocol v1")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("projects")

    p = sub.add_parser("analysis")
    p.add_argument("--project", required=True)

    p = sub.add_parser("live-run")
    p.add_argument("--project", required=True)
    p.add_argument("--input", required=True)

    p = sub.add_parser("mock-cases")
    p.add_argument("--project", required=True)

    p = sub.add_parser("mock-datasets")
    p.add_argument("--project", required=True)

    p = sub.add_parser("mock-check")
    p.add_argument("--project", default="")
    p.add_argument("--path", default="", help="mock 数据 JSON 文件或目录；为空时扫描 data/ 与 impl/data")
    p.add_argument("--cases", default="", help="一次性批量 case 数据（JSON 字符串或文件路径）")
    p.add_argument("--verbose", action="store_true", help="输出逐 case details")

    p = sub.add_parser("judge")
    p.add_argument("--project", required=True)
    p.add_argument("--trace", required=True)
    p.add_argument("--expected-intent")

    p = sub.add_parser("attribute")
    p.add_argument("--project", required=True)
    p.add_argument("--trace", required=True)
    p.add_argument("--judge", required=True)

    p = sub.add_parser("cluster")
    p.add_argument("--project", required=True)
    p.add_argument("--attributes", required=True)

    p = sub.add_parser("check")
    p.add_argument("--project", required=True)
    p.add_argument("--trace")
    p.add_argument("--judge")
    p.add_argument("--attribute")

    p = sub.add_parser("run-chain")
    p.add_argument("--project", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--expected-intent")

    p = sub.add_parser("batch-run")
    p.add_argument("--project", required=True)
    p.add_argument("--inputs", required=True)
    p.add_argument("--expected-intent")
    p.add_argument("--concurrency", type=int, default=4)

    args = parser.parse_args(argv)
    if args.cmd == "projects":
        emit({"projects": list_projects()})
    elif args.cmd == "analysis":
        emit(pipeline.analysis(args.project))
    elif args.cmd == "live-run":
        _cli_check_request(args.project, load_json_arg(args.input))
        emit(pipeline.live_run(args.project, load_json_arg(args.input)))
    elif args.cmd == "mock-cases":
        emit({"project_id": args.project, "cases": pipeline.mock_cases(args.project)})
    elif args.cmd == "mock-datasets":
        emit({"project_id": args.project, "datasets": pipeline.mock_datasets(args.project)})
    elif args.cmd == "mock-check":
        cases = load_json_arg(args.cases) if args.cases else None
        if args.project:
            result = pipeline.check_mock_data(project_id=args.project, data_path=args.path, cases=cases)
        else:
            per_project = []
            ok = True
            for project_id in list_projects():
                project_result = pipeline.check_mock_data(project_id=project_id, data_path=args.path, cases=cases)
                per_project.append(project_result)
                ok = ok and project_result.get("ok")
            result = {"project_id": "", "data_path": args.path or "", "ok": ok, "items": per_project}
        if not args.verbose:
            for item in result.get("items") or []:
                item.pop("details", None)
        emit(result)
        if not result.get("ok"):
            raise SystemExit(1)
    elif args.cmd == "judge":
        emit(pipeline.judge(args.project, trace_from_json(load_json_arg(args.trace)), args.expected_intent))
    elif args.cmd == "attribute":
        emit(pipeline.attribute(args.project, trace_from_json(load_json_arg(args.trace)), judge_from_json(load_json_arg(args.judge))))
    elif args.cmd == "cluster":
        attrs = [attribute_from_json(item) for item in load_json_arg(args.attributes)]
        emit(pipeline.cluster(args.project, attrs))
    elif args.cmd == "check":
        emit(
            pipeline.check(
                args.project,
                trace_from_json(load_json_arg(args.trace)) if args.trace else None,
                judge_from_json(load_json_arg(args.judge)) if args.judge else None,
                attribute_from_json(load_json_arg(args.attribute)) if args.attribute else None,
            )
        )
    elif args.cmd == "run-chain":
        _cli_check_request(args.project, load_json_arg(args.input))
        emit(run_chain(args.project, load_json_arg(args.input), expected_intent=args.expected_intent))
    elif args.cmd == "batch-run":
        inputs = load_json_arg(args.inputs)
        if isinstance(inputs, list):
            for item in inputs:
                _cli_check_request(args.project, item)
        emit(pipeline.batch_run(args.project, inputs, expected_intent=args.expected_intent, concurrency=args.concurrency))


def _cli_check_request(project_id: str, input_data: Any) -> None:
    """CLI 手动输入校验：输入是否符合 REQUEST_SCHEMA。校验不阻断，不一致时打印警告。"""
    import importlib
    import sys
    try:
        ls = importlib.import_module(f"impl.projects.{project_id}.live_schema")
    except ModuleNotFoundError:
        print(f"[live_schema] INFO: project {project_id} has no live_schema module, skipping CLI input check", file=sys.stderr)
        return
    if not hasattr(ls, "check"):
        print(f"[live_schema] INFO: project {project_id} live_schema has no check, skipping CLI input check", file=sys.stderr)
        return
    if not isinstance(input_data, dict):
        return
    try:
        if not ls.check.request(input_data):
            print(f"[live_schema] WARNING: CLI input does not match REQUEST_SCHEMA for {project_id}", file=sys.stderr)
    except Exception as e:
        print(f"[live_schema] WARNING: request check raised for {project_id}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
