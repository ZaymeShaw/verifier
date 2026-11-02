"""正式实现核对：用 impl 里的 run_expected_axis（正式 LlmClient、正式材料批次）跑冻结 case，与实验 new4 对照。

usage: python impl_check.py --tags a,b [--pass N]    结果写 runs/impl/pass<N>/<tag>/<axis>.json
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from types import SimpleNamespace

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

import new_arm as N  # noqa: E402
from impl.core.project_loader import load_project  # noqa: E402
from impl.projects.llm_probe.eval_axes import registry  # noqa: E402,F401  —— 注册六轴，填充 PROCESS_SPECS
from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS  # noqa: E402
from impl.projects.llm_probe.eval_axes.adapters.process_expected import run_expected_axis  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tags", required=True)
    parser.add_argument("--pass", dest="pass_no", default="1")
    parser.add_argument("--axes", default=",".join(io.AXES))
    args = parser.parse_args()
    io.init_secret_guard()
    project = load_project("llm_probe")
    for tag in [t for t in args.tags.split(",") if t]:
        frozen, dossier, analysis = N.build_case(tag)
        expectations = {"expectations": frozen["expectations"], "sources": frozen["expectation_sources"]}
        for axis in [a for a in args.axes.split(",") if a]:
            target = io.HERE / "runs" / "impl" / f"pass{args.pass_no}" / tag / f"{axis}.json"
            if target.exists():
                continue
            runtime = SimpleNamespace(spec=project, scenario_id=None, trace_id=f"impl-check:{tag}:{axis}:{time.time():.0f}",
                                      ensure_time_left=lambda *_: None)
            started = time.monotonic()
            out = run_expected_axis(axis, {"trace_analysis": analysis, "expectations": expectations},
                                    None, runtime, PROCESS_SPECS[axis])
            record = {"tag": tag, "axis": axis, "elapsed_seconds": round(time.monotonic() - started, 1),
                      **dataclasses.asdict(out)}
            io.save_json(target, record, exclusive=False)
            a = out.output["assessment"]
            print(f"{tag} {axis}: verdict={a['verdict']} problems={len(out.output['issues'])} "
                  f"failed={out.failed} usage={out.usage.get('llm_calls')}calls {record['elapsed_seconds']}s "
                  f"{out.failure_reason[:200]}", flush=True)


if __name__ == "__main__":
    main()
