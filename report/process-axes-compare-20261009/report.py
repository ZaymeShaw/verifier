"""把 score/pass<N>.json 折算成 RESULT.md 用的数字表（只出数字，不做解释）。"""
from __future__ import annotations

import json
import sys

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

ARMS = {"current": "现行六轴", "new": "本应清单/实际清单"}


def load_arm_stats(arm: str, pass_no=1):
    root = io.HERE / "runs" / arm / f"pass{pass_no}"
    axes = failed = invalid = leaked = 0
    models, calls = set(), []
    for path in sorted(root.glob("*/*.json")):
        record = io.load_json(path)
        axes += 1
        if record.get("failed"):
            failed += 1
            continue
        if record.get("bookkeeping_ok") is False:
            invalid += 1
        attempts = record.get("http_attempts") or []
        if arm == "new":
            attempts = [a for batch in record.get("batches") or [] for a in batch.get("http_attempts") or []]
            leaked += sum(b.get("leak_check", {}).get("real_leak", 0) for b in record.get("batches") or [])
        calls.append(len(attempts))
        models |= {m for a in attempts for m in (a.get("response_models") or [])}
    return {"axes": axes, "failed_axes": failed, "invalid_axes": invalid,
            "calls": sum(calls), "calls_per_axis": round(sum(calls) / len(calls), 2) if calls else None,
            "response_models": sorted(models), "real_leak": leaked}


def main():
    pass_no = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    report = io.load_json(io.HERE / "score" / f"pass{pass_no}.json")
    lines = [f"# 指标（pass{pass_no}）", ""]
    for arm, metrics in report["arms"].items():
        stats = load_arm_stats(arm, pass_no)
        lines += [f"## {ARMS[arm]}（{arm}）", "",
                  f"- 轴数 {stats['axes']}，管道失败 {stats['failed_axes']}，书账不符 {stats['invalid_axes']}，"
                  f"泄漏 {stats['real_leak']}",
                  f"- 实际应答模型：{', '.join(stats['response_models'])}；请求数 {stats['calls']}"
                  f"（每轴 {stats['calls_per_axis']}）",
                  f"- 问题条目 {metrics['total']}（已分类 {metrics['classified']}）",
                  f"- 命中已知项 {metrics['hit']}：hard {len(set(metrics['hits']) & HARD)}/{len(HARD)}"
                  f"（召回 {metrics['recall_hard']}）、soft {len(set(metrics['hits']) & SOFT)}/{len(SOFT)}"
                  f"（召回 {metrics['recall_soft']}）",
                  f"- 清单外真问题 {metrics['out_of_list_real']}；误报 {metrics['false_positive']}"
                  f"（拆分 {metrics['split']}、过度断言 {metrics['overclaim']}、被反驳 {metrics['contradicted']}）"
                  f"；误报率 {metrics['false_positive_rate']}",
                  f"- 无法判断 {metrics['unclear']}；带引用 {metrics['with_refs_rate']}，"
                  f"带现象描述 {metrics['with_observed_rate']}",
                  f"- 引用核验（triage_rules §6/F1）：可解析 {metrics['refs_audit']['resolvable']}/{metrics['refs_audit']['refs']}"
                  f"（{metrics['refs_audit']['resolvable_rate']}），内部定位符 {metrics['refs_audit']['internal_ids']}，"
                  f"无法解析 {len(metrics['refs_audit']['unresolvable_paths'])}，"
                  f"条目有可解析引用 {metrics['refs_audit']['rows_with_resolvable_ref']}/{metrics['total']}",
                  f"- 未召回 hard：{', '.join(metrics['missed_hard'])}",
                  f"- 归因（按已知项主轴）：`{json.dumps(metrics['per_axis'], ensure_ascii=False)}`",
                  f"- 成本：{json.dumps(metrics['cost'], ensure_ascii=False)}", ""]
        if "overlap_pass1_pass2" in metrics:
            lines += [f"- 未分类条目：{metrics['unclassified']}"] if metrics.get("unclassified") else []
            lines += [f"- 两遍一致：{json.dumps(metrics['overlap_pass1_pass2'], ensure_ascii=False)}",
                      f"- 轴结论一致：{json.dumps(metrics['verdict_agreement'], ensure_ascii=False)}", ""]
    io.save_text(io.HERE / "score" / f"pass{pass_no}.md", "\n".join(lines), exclusive=False)
    print("\n".join(lines))


if __name__ == "__main__":
    gold = io.load_json(io.HERE / "gold.json")["items"]
    HARD = {i["id"] for i in gold if i["grade"] == "hard"}
    SOFT = {i["id"] for i in gold if i["grade"] == "soft"}
    main()
