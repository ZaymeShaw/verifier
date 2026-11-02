"""在同一上游输入上重跑现行六轴：用真实仓库代码路径复现程序上下文与 prompt。

上游（案卷、structure、selections、前置材料投影）没有落在导出 trace 里，靠
`doc_rebuild.build` 从 trace_analysis 子循环的目录/取回正文/定稿 payload 还原。
还原是否充分由一件事判定：真实代码生成的 prompt 与导出 trace 里记录的 prompt 逐字相同。

用法：
  python replay.py --check                # 只做 prompt 一致性核对（不调模型）
  python replay.py --check --tag X
  python replay.py --run [--tag X]        # 用真实模型重跑六轴（写 runs/<arm>/<tag>/）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

import doc_rebuild  # noqa: E402


def specs():
    from impl.projects.llm_probe.eval_axes.adapters import process_common
    from impl.projects.llm_probe.eval_axes import registry
    registry.AXIS_TYPES  # 触发适配器导入，PROCESS_SPECS 随之填充
    from impl.projects.llm_probe.eval_axes.adapters import (
        context_memory, intent_understanding, planning_routing, tool_execution, knowledge_data, model_capability)
    return process_common.PROCESS_SPECS


def expectations_output(frozen: dict) -> dict:
    payload = {"expectations": frozen["expectations"], "sources": frozen["expectation_sources"]}
    digest = io.digest(json.dumps(frozen["expectations"], ensure_ascii=False, sort_keys=True))
    return {"verdict": "complete", **payload, "material_sha256": digest, "sha256": digest}


def projection_of(frozen: dict) -> dict:
    """消费投影：记录的 data_needs + 程序在模型回答后补上的 E 摘要。"""
    projection = dict(frozen.get("projection") or {})
    projection["expectations_sha256"] = io.digest(json.dumps(frozen["expectations"], ensure_ascii=False, sort_keys=True))
    return projection


def record_gateway():
    """把六个 LLM 中转站的地址与密钥读进 process env（密钥只进环境，不落盘、不打印）。"""
    import os
    from dotenv import dotenv_values
    for key in ("VERIFIER_INSTANCE_ID", "VERIFIER_PORT", "VERIFIER_TRACING_ENABLED"):
        os.environ.pop(key, None)
    gateways = {}
    for suffix, endpoint in (("", "primary"), ("_FALLBACK_1", "fallback1"), ("_FALLBACK_2", "fallback2")):
        values = dotenv_values(io.INSTANCE / "tracing" / (".env.verifier_" + endpoint))
        base = "http://127.0.0.1:" + values["LITELLM_PORT"] + "/v1"
        os.environ["LLM" + suffix + "_BASE_URL"] = base
        os.environ["DEEPSEEK_API_KEY" if not suffix else "LLM" + suffix + "_API_KEY"] = values["LITELLM_MASTER_KEY"]
        gateways[endpoint] = base
    os.environ["EVAL_AXES_MODEL_POLICY"] = "same_model"
    return gateways


def projection_of(frozen: dict) -> dict:
    """消费投影：记录的 data_needs，候选办法换成程序解析过的设计块引用（与导出 prompt 里的 actions 一致）。"""
    projection = json.loads(json.dumps(frozen.get("projection") or {}))
    resolved = {}
    for batches in (frozen.get("axes") or {}).values():
        for batch in batches:
            for need in ((batch.get("body") or {}).get("actions") or {}).values():
                resolved[need.get("expectation_id")] = need
    for item in projection.get("data_needs") or []:
        hit = resolved.get(item.get("expectation_id"))
        if hit and len(hit.get("methods") or []) == len(item.get("methods") or []):
            item["methods"] = json.loads(json.dumps(hit["methods"]))
    projection["expectations_sha256"] = io.digest(json.dumps(frozen["expectations"], ensure_ascii=False, sort_keys=True))
    projection.pop("design_sha256", None)
    return projection


class DryClient:
    """按记录内容作答的假客户端：只用来核对程序侧 prompt 与验收链路。"""

    JOIN_STAGE = "llm_probe_expectations_process_projection"

    def __init__(self, recorded: list[dict], join: dict | None = None):
        self.recorded = recorded
        self.join = join
        self.n = 0
        self.join_calls = 0
        self.prompts = []
        self.join_prompts = []

    def complete_json(self, system, user, trace_id=None, reasoning_effort=None, output_spec=None, stage="", **kw):
        if stage == self.JOIN_STAGE:
            self.join_calls += 1
            self.join_prompts.append({"stage": stage, "user": user, "system": system})
            if self.join is None:
                raise RuntimeError("记录里没有消费投影的回答")
            return self.join
        self.n += 1
        self.prompts.append({"stage": stage, "user": user, "system": system})
        entry = self.recorded[self.n - 1] if self.n - 1 < len(self.recorded) else None
        if entry is None:
            raise RuntimeError("记录的回答不足：还要求第 %d 次调用" % self.n)
        return json.loads(entry["recorded"]["content"])

    def usage(self):
        return {"llm_calls": self.n + self.join_calls, "llm_model": "recorded", "llm_endpoint": "recorded",
                "llm_attempts": self.n, "llm_failed_attempts": 0, "model_policy": "recorded"}


def axis_batches(frozen: dict, axis: str) -> list[dict]:
    """该轴的记录批次（每个批次取首轮，纠正轮另记）。"""
    out = {}
    for entry in frozen["axes"].get(axis) or []:
        out.setdefault(entry["batch"], entry)
    return [out[k] for k in sorted(out)]


def analysis_of(frozen: dict) -> dict:
    dossier = doc_rebuild.build(frozen)
    return doc_rebuild.analysis_output(frozen, dossier)


def run_one(frozen: dict, axis: str, client, spec_map: dict, project_id: str, scenario_id: str,
            runtime=None) -> dict:
    from impl.projects.llm_probe.eval_axes.adapters import process_common
    from impl.projects.llm_probe.eval_axes.types import AxisRuntime

    if runtime is None:
        analysis = analysis_of(frozen)
        runtime = AxisRuntime(spec=type("Spec", (), {"project_id": project_id})(), run_id=frozen["run_id"],
                              trace_id=frozen["run_id"] + ":" + frozen["tag"], scenario_id=scenario_id,
                              case_id=frozen["tag"], enabled_axes=tuple(io.AXES))
        runtime.analysis = analysis
        runtime.expectation_projection.update(projection_of(frozen))
    analysis = runtime.analysis
    saved = process_common.axis_llm
    process_common.axis_llm = lambda *a, **kw: client
    try:
        inputs = {"trace_analysis": analysis, "expectations": expectations_output(frozen)}
        outcome = process_common.run_process_axis(axis, inputs, None, runtime, spec_map[axis])
    finally:
        process_common.axis_llm = saved
    return {"outcome": outcome, "analysis": analysis, "runtime": runtime}


def check(tag: str, verbose: bool = True) -> dict:
    frozen = io.load_json(io.HERE / "frozen" / f"case_{tag}.json")
    spec_map = specs()
    report = {"tag": tag, "axes": {}}
    runtime = None
    for axis in io.AXES:
        entries = frozen["axes"].get(axis) or []
        client = DryClient(entries, frozen.get("projection"))
        record = {"calls_recorded": len(entries),
                  "batches_recorded": len({e["batch"] for e in entries})}
        try:
            got = run_one(frozen, axis, client, spec_map, "llm_probe", frozen.get("scenario_id") or "", runtime)
            runtime = got["runtime"]
            record["outcome"] = got["outcome"].output.get("assessment", {}).get("verdict")
            record["failed"] = bool(got["outcome"].failed)
            record["failure_reason"] = got["outcome"].failure_reason
        except Exception as exc:  # noqa: BLE001
            import traceback
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["traceback"] = traceback.format_exc()[-2000:]
        prompts = client.prompts
        record["calls"] = len(prompts)
        record["join_calls"] = client.join_calls
        diffs = []
        for index, entry in enumerate(entries):
            if index >= len(prompts):
                diffs.append({"batch": entry["batch"], "issue": "missing_prompt"})
                continue
            got_user = prompts[index]["user"]
            if got_user != entry["user"]:
                diffs.append({"batch": entry["batch"], "issue": "user_diff",
                              "recorded_chars": len(entry["user"]), "rebuilt_chars": len(got_user),
                              "head": _first_diff(entry["user"], got_user)})
            if not entry["system"].startswith(prompts[index]["system"]):
                diffs.append({"batch": entry["batch"], "issue": "system_prefix"})
            if entry["kind"] != "first":
                diffs.append({"batch": entry["batch"], "issue": "recorded_kind=" + entry["kind"]})
        record["prompt_diffs"] = diffs
        report["axes"][axis] = record
        if verbose:
            print(f"{tag} {axis}: calls={record['calls']}/{len(entries)} diffs={len(diffs)} "
                  f"verdict={record.get('outcome')} err={(record.get('error') or record.get('failure_reason') or '')[:120]}")
            for d in diffs[:3]:
                print("    ", json.dumps(d, ensure_ascii=False)[:600])
    return report


def _first_diff(a: str, b: str) -> dict:
    limit = min(len(a), len(b))
    index = next((i for i in range(limit) if a[i] != b[i]), limit)
    return {"at": index, "recorded": a[max(0, index - 120):index + 160], "rebuilt": b[max(0, index - 120):index + 160]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    io.init_secret_guard()
    record_gateway()
    tags = [args.tag] if args.tag else list(io.CASES)
    total = {}
    for tag in tags:
        if args.check:
            total[tag] = check(tag)
    io.save_json(io.HERE / "rebuild" / "prompt_check.json", total, exclusive=False)
    bad = sum(len(a["prompt_diffs"]) for c in total.values() for a in c["axes"].values())
    errs = sum(1 for c in total.values() for a in c["axes"].values() if a.get("error") or a.get("failed"))
    print(f"合计 prompt 差异 {bad}，验收失败 {errs}")


if __name__ == "__main__":
    main()
