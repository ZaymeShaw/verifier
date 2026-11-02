"""现行臂：用 HEAD 的六轴实现，在重建出来的同一份上游输入上重跑六轴。

上游全部复用本批已记录的结果：案卷（doc_rebuild 从 trace_analysis 子循环还原）、
需求轴的期望 E、消费投影（projection_of）。只重跑六轴本身。

模型调用与生产等价（见 CORRECTION-1.md）：输出结构注入 + 解析 + `enforce_output` 强校验，
不合规抛 ValueError 由六轴自己的纠错轮重问；请求层失败返回 error payload 由
`raise_for_error_payload` 转成轴失败。

每次运行（含整案重跑）都从冻结输入重建 AxisRuntime，不共享可变对象。
落盘：runs/<arm>/<passDir>/<tag>/<axis>.json（程序 prompt、真实应答模型/用量/结束原因、
轴的完整输出）。整案重跑放 <passDir>b/，两份都留。

用法：
  python current_arm.py [--arm current] --pass 1 [--tag X] [--tags a,b] [--force]
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

import doc_rebuild  # noqa: E402
import replay  # noqa: E402
from llm_transport import Transport  # noqa: E402
from impl.projects.llm_probe.eval_axes.adapters import process_common  # noqa: E402

MODEL = "gemini-3.8-flash-medium"  # 任务书 §0.5：primary 可用就用它，两臂同一个模型
PROVIDER = "primary"
AXIS_DEADLINE_SECONDS = 2700

_lane = threading.local()


def _dispatch_axis_llm(*args, **kwargs):
    """轴调用的模型客户端永远是本线程注册的 sink；没注册就报错，绝不回落到真实 LlmClient。"""
    sink = getattr(_lane, "sink", None)
    if sink is None:
        raise RuntimeError("axis_llm 在未注册 sink 的线程里被调用：拒绝构造真实模型客户端")
    return sink


def install_model_patch():
    """只在主线程装一次；各轴在自己的线程里注册 sink，避免线程间互相抢全局函数。"""
    from impl.projects.llm_probe.eval_axes import llm
    from impl.projects.llm_probe.eval_axes.adapters import process_common

    process_common.axis_llm = _dispatch_axis_llm
    llm.axis_llm = _dispatch_axis_llm


class Spec:
    project_id = "llm_probe"


class PromptSink:
    """记录每次调用给了模型什么（原始 system/user）；system 的输出结构约束由 transport 追加。"""

    def __init__(self, transport: Transport):
        self.transport = transport
        self.prompts: list[dict] = []

    def complete_json(self, system, user, trace_id=None, reasoning_effort=None, output_spec=None, stage="", **kw):
        self.prompts.append({"stage": stage, "system": system, "user": user,
                             "system_sha256": io.digest(system), "user_sha256": io.digest(user)})
        return self.transport.complete_json(system, user, trace_id=trace_id, reasoning_effort=reasoning_effort,
                                            output_spec=output_spec, stage=stage, **kw)

    def usage(self):
        return self.transport.usage()


def build_runtime(frozen: dict):
    """每次调用都新建：分析轴输出、消费投影、过程问题集合都是可变对象，不能在运行间复用。"""
    from impl.projects.llm_probe.eval_axes.types import AxisRuntime

    analysis = doc_rebuild.analysis_output(frozen, doc_rebuild.build(frozen))
    runtime = AxisRuntime(spec=Spec(), run_id=frozen["run_id"], trace_id=frozen["run_id"] + ":" + frozen["tag"],
                          scenario_id=frozen.get("scenario_id") or "", case_id=frozen["tag"],
                          enabled_axes=tuple(io.AXES))
    runtime.analysis = analysis
    runtime.expectation_projection.update(replay.projection_of(frozen))
    return runtime


def call_axis(frozen: dict, axis: str, runtime, spec_map: dict, directory: str):
    transport = Transport(PROVIDER, MODEL, arm=ARM, tag=f"{directory}/{frozen['tag']}")
    sink = PromptSink(transport)
    runtime.deadline = time.monotonic() + AXIS_DEADLINE_SECONDS
    _lane.sink = sink
    started = time.monotonic()
    try:
        outcome = process_common.run_process_axis(
            axis, {"trace_analysis": runtime.analysis, "expectations": replay.expectations_output(frozen)},
            None, runtime, spec_map[axis])
        return {"outcome": outcome, "transport": transport, "sink": sink,
                "elapsed_seconds": round(time.monotonic() - started, 3)}, None
    except Exception as exc:  # noqa: BLE001
        return {"transport": transport, "sink": sink, "elapsed_seconds": round(time.monotonic() - started, 3)}, \
            {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()[-4000:]}
    finally:
        _lane.sink = None


def axis_record(frozen: dict, axis: str, got: dict, error) -> dict:
    outcome = got.get("outcome")
    output = dict(outcome.output) if outcome is not None else {}
    attempts = []
    for attempt in got["transport"].attempts:
        attempts.append({k: v for k, v in attempt.items()
                         if k not in {"arm", "started_at", "system_sha256"}})
    return {"arm": ARM, "tag": frozen["tag"], "axis": axis,
            "model_requested": MODEL, "provider": PROVIDER,
            "elapsed_seconds": got.get("elapsed_seconds"),
            "failed": bool(outcome.failed) if outcome is not None else True,
            "failure_reason": outcome.failure_reason if outcome is not None else None,
            "error": error,
            "assessment": output.get("assessment"), "issues": output.get("issues"),
            "results": output.get("results"), "evidence_refs": output.get("evidence_refs"),
            "coverage": output.get("coverage"), "selection": output.get("selection"), "view": output.get("view"),
            "prompts": got["sink"].prompts,
            "bookkeeping_ok": sum(1 for attempt in attempts if attempt.get("ok")) == len(got["sink"].prompts),
            "http_attempts": attempts}


def round_labels(pass_no: int) -> list:
    """整案重跑最多 4 轮：pass1 / pass1b / pass1c / pass1d。每轮的落盘目录不同，坏记录不会被覆盖。"""
    return [f"pass{pass_no}" if suffix == "" else f"pass{pass_no}{suffix}" for suffix in ("", "b", "c", "d")]


def valid_record(tag: str, axis: str, labels) -> str:
    """返回已有合格记录所在的轮次目录（没有就返回空串）。"""
    for label in labels:
        path = io.HERE / "runs" / ARM / label / tag / f"{axis}.json"
        if not path.exists():
            continue
        record = io.load_json(path)
        if not record.get("failed") and io.bookkeeping_ok(record):
            return label
    return ""


def run_case(tag: str, directory: str, spec_map: dict, force: bool = False, labels=None) -> dict:
    base = io.HERE / "runs" / ARM / directory / tag
    frozen = io.load_json(io.HERE / "frozen" / f"case_{tag}.json")
    runtime = build_runtime(frozen)
    summary = {"tag": tag, "dir": directory, "axes": {}}
    for axis in io.AXES:
        target = base / f"{axis}.json"
        if not force and labels and valid_record(tag, axis, labels):
            summary["axes"][axis] = {"skipped": True, "valid_in": valid_record(tag, axis, labels)}
            continue
        if target.exists() and not force:
            summary["axes"][axis] = {"skipped": True}
            continue
        got, error = call_axis(frozen, axis, runtime, spec_map, directory)
        record = axis_record(frozen, axis, got, error)
        io.save_json(target, record, exclusive=False)
        summary["axes"][axis] = {"verdict": (record.get("assessment") or {}).get("verdict"),
                                 "failed": record["failed"], "calls": len(record["prompts"]),
                                 "bookkeeping_ok": record["bookkeeping_ok"],
                                 "error": (error or {}).get("type"),
                                 "error_message": ((error or {}).get("message") or "")[:300],
                                 "models": sorted({m for a in record["http_attempts"] for m in (a.get("response_models") or [])})}
        print(f"{ARM} {directory} {tag} {axis}: verdict={summary['axes'][axis]['verdict']} "
              f"failed={record['failed']} calls={len(record['prompts'])} "
              f"models={summary['axes'][axis]['models']}", flush=True)
    return summary


def next_round(tag: str, labels, force: bool = False) -> str:
    """选一个还没写过东西的轮次目录；坏记录不会被覆盖。"""
    if force:
        return labels[0]
    for label in labels:
        directory = io.HERE / "runs" / ARM / label / tag
        if not directory.exists() or not any(directory.glob("*.json")):
            return label
    return ""


def do_case(tag: str, pass_no: int, spec_map: dict, force: bool = False) -> dict:
    """整案跑一轮；还有轴没拿到合格记录，就整案再跑一轮（每轮新 runtime、新目录）。"""
    labels = round_labels(pass_no)
    result = {"tag": tag, "axes": {}, "rounds": []}
    while True:
        directory = next_round(tag, labels, force)
        if not directory:
            print(f"{ARM} {tag}: 轮次用完（{'/'.join(labels)}），仍有轴没拿到合格记录", flush=True)
            break
        round_summary = run_case(tag, directory, spec_map, force, labels)
        result["rounds"].append({"dir": directory, "axes": round_summary["axes"]})
        result["axes"] = round_summary["axes"]
        broken = [axis for axis, row in round_summary["axes"].items() if row.get("failed")]
        if not broken:
            break
        print(f"{ARM} {tag}: {directory} 有 {len(broken)} 个轴失败，整案重跑"
              f"（{'、'.join(broken)}）", flush=True)
    return result


ARM = "current"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", default="current")
    parser.add_argument("--pass", dest="pass_no", type=int, default=1)
    parser.add_argument("--tag", default=None)
    parser.add_argument("--tags", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    global ARM
    ARM = args.arm
    io.init_secret_guard()
    io.verify_prereg()
    tags = [args.tag] if args.tag else ([t for t in args.tags.split(",") if t] if args.tags else list(io.CASES))
    spec_map = replay.specs()
    install_model_patch()
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda t: do_case(t, args.pass_no, spec_map, args.force), tags))
    io.save_json(io.HERE / "runs" / ARM / f"pass{args.pass_no}" / "manifest.json",
                 {"arm": ARM, "pass": args.pass_no, "model": MODEL, "provider": PROVIDER,
                  "elapsed_seconds": round(time.monotonic() - started, 3), "cases": results}, exclusive=False)
    failed = sum(1 for c in results for a in c["axes"].values() if a.get("failed"))
    labels_all = round_labels(args.pass_no)
    missing = [f"{c['tag']}/{axis}" for c in results for axis in io.AXES
               if not valid_record(c["tag"], axis, labels_all)]
    if missing:
        print(f"{ARM} pass{args.pass_no}: 仍无合格记录的轴 {len(missing)} 个：{'、'.join(missing)}", flush=True)
    print(f"{ARM} pass{args.pass_no}: cases={len(results)} failed_axes={failed} "
          f"elapsed={round(time.monotonic() - started, 1)}s")


if __name__ == "__main__":
    main()
