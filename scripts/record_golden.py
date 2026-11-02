from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from impl.core import context_store, pipeline
from impl.core.active_artifacts import DEFAULT_ACTIVE_ARTIFACT_REGISTRY
from impl.core.mock import mock_case_to_single_turn, parse_mock_case
from impl.core.project_loader import load_project
from impl.core.schema import RunTrace, to_dict
from scripts.trace_canonicalize import canonical_json
from tests.support import cassette


def execute_case(
    project_id: str,
    case: dict[str, Any],
    *,
    live_base_url_override: str | None = None,
    replay: bool = False,
) -> RunTrace:
    spec = load_project(project_id)
    environment = {}
    if live_base_url_override is not None:
        variables = [
            variable.name
            for variable in spec.environment.variables.values()
            if variable.bind == "runtime.services.primary.base_url"
        ]
        if len(variables) != 1:
            raise ValueError(
                f"Expected one primary base URL binding for {project_id}"
            )
        environment[variables[0]] = live_base_url_override
    runtime_case = mock_case_to_single_turn(
        parse_mock_case(case, project_id=project_id)
    )
    if spec.session_max_turns <= 1:
        raise ValueError(f"{project_id} is not a multi-turn project")
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, environment))
        if replay or live_base_url_override is not None:
            stack.enter_context(
                patch("impl.core.local_service.ensure_project_service")
            )
        return pipeline.live_run(project_id, runtime_case)


def select_case(path: Path, case_id: str) -> dict[str, Any]:
    source = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(source, dict):
        cases = source["cases"] if "cases" in source else [source]
    else:
        cases = source
    matches = [case for case in cases if str(case.get("id", "")) == case_id]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one case {case_id!r} in {path}")
    return matches[0]


def record_case(
    project_id: str,
    case: dict[str, Any],
    out: Path,
    live_base_url_override: str | None = None,
) -> RunTrace:
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise FileExistsError(f"Golden output directory must be empty: {out}")
    (out / "case.json").write_text(
        json.dumps(case, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "execution.json").write_text(
        json.dumps(
            {"live_base_url_override": live_base_url_override}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    with ExitStack() as stack:
        temporary = stack.enter_context(
            TemporaryDirectory(prefix="golden-context-")
        )
        artifact_context = DEFAULT_ACTIVE_ARTIFACT_REGISTRY.context(
            Path(temporary)
        )
        stack.enter_context(
            patch.object(
                context_store,
                "_ACTIVE_ARTIFACT_CONTEXT",
                artifact_context,
            )
        )
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "VERIFIER_CASSETTE": "record",
                    "VERIFIER_CASSETTE_DIR": str(out),
                },
            )
        )
        cassette.install()
        try:
            trace = execute_case(
                project_id,
                case,
                live_base_url_override=live_base_url_override,
            )
        finally:
            cassette.uninstall()
    (out / "trace.raw.json").write_text(
        json.dumps(
            to_dict(trace), ensure_ascii=False, sort_keys=True, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "trace.canonical.json").write_text(
        canonical_json(trace, project_id),
        encoding="utf-8",
    )
    return trace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--case-file", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--live-base-url-override")
    args = parser.parse_args()
    trace = record_case(
        args.project,
        select_case(args.case_file, args.case_id),
        args.out,
        args.live_base_url_override,
    )
    print(
        json.dumps(
            {
                "project": args.project,
                "case_id": trace.case_id,
                "stop_reason": trace.stop_reason,
                "completion_status": trace.completion_status,
                "turn_count": len(trace.turn_records),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
