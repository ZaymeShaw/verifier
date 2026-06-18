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
        emit(pipeline.live_run(args.project, load_json_arg(args.input)))
    elif args.cmd == "mock-cases":
        emit({"project_id": args.project, "cases": pipeline.mock_cases(args.project)})
    elif args.cmd == "mock-datasets":
        emit({"project_id": args.project, "datasets": pipeline.mock_datasets(args.project)})
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
        emit(run_chain(args.project, load_json_arg(args.input), expected_intent=args.expected_intent))
    elif args.cmd == "batch-run":
        emit(pipeline.batch_run(args.project, load_json_arg(args.inputs), expected_intent=args.expected_intent, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
