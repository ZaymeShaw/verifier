"""把盲测分类结果折算成两臂的指标（召回 / 误报 / 归因 / 一致性 / 成本）。

输入：
- gold.json（冻结：22 hard + 7 soft）
- problems/pass<N>.json（dump_problems.py）+ problems/blind_key.jsonl（盲测 id → 来源）
- classification.json（classify_blind.py 的独立归类：盲测 id → {verdict, code, gold_id, note}）
  折算：真问题+gold_id → hit；真问题+none → out_of_list_real；误报 F2 → overclaim；F4 → contradicted；
  F5 → split；其余误报 → other_false_positive；无法判断 → unclear（口径见 triage_rules.md）。
- score/refs_index.json（程序核验引用 id 是否在案卷里）

输出：score/pass<N>.json + 控制台 markdown 片段。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

FP_KINDS = {"split", "overclaim", "contradicted", "other_false_positive"}


def variants(payload):
    """新方案臂按程序条目口径分三种报（CORRECTION-3）：v1 原样 / 只有模型条目 / 模型条目 + 程序 v2。"""
    model_only = [row for row in payload.get("new") or [] if row.get("verified_by") != "程序"]
    return {"current": payload["current"],
            "new": payload["new"],
            "new_model_only": model_only,
            "new_model_v2": model_only + (payload.get("new_program_v2") or []),
            "new2": payload.get("new2") or [], "new3": payload.get("new3") or [], "new4": payload.get("new4") or [],
            "impl": payload.get("impl") or []}
INTERNAL_REF_PREFIX = ("程序-", "unexp-", "item_", "exp_", "exp-")


def kind_of(judged: dict) -> str:
    """把 triage_rules.md 的判定折算成评分用的粗类（与 classify_blind.kind_of 一致）。"""
    if judged.get("kind"):
        return judged["kind"]
    verdict, code, gold_id = judged.get("verdict"), judged.get("code") or "", judged.get("gold_id") or ""
    if verdict == "真问题":
        return "hit" if gold_id and gold_id != "none" else "out_of_list_real"
    if verdict == "无法判断":
        return "unclear"
    return {"F2": "overclaim", "F4": "contradicted", "F5": "split"}.get(code, "other_false_positive")


def load(pass_no: int):
    gold = io.load_json(io.HERE / "gold.json")["items"]
    problems = io.load_json(io.HERE / f"problems/pass{pass_no}.json")
    path = io.HERE / "classification.json"
    cls = io.load_json(path) if path.exists() else {}
    key_path = io.HERE / "problems/blind_key.jsonl"
    keymap = {}
    if key_path.exists():
        for line in key_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                keymap[(row["arm"], row["pass"], row["blind_id"])] = row["id"]
    refs_path = io.HERE / "score/refs_index.json"
    refs = io.load_json(refs_path) if refs_path.exists() else {}
    return gold, problems, cls, keymap, refs


def label(blind_id: str, cls: dict):
    row = cls.get(blind_id)
    if not row or row.get("kind") == "pending":
        return None
    return row


def refs_audit(rows, refs_index):
    """程序核验：引用的 id 能不能在该 case 案卷里解析（triage_rules.md §6 / F1）。"""
    audit = {"refs": 0, "resolvable": 0, "internal_ids": 0, "unresolvable_paths": [],
             "rows_with_resolvable_ref": 0, "rows_without_resolvable_ref": 0}
    for row in rows:
        known = set(refs_index.get(row["case"]) or [])
        if not known:
            known = {"turn1.delivered_output"}
        resolvable = 0
        for ref in row.get("refs") or []:
            audit["refs"] += 1
            if ref in known:
                audit["resolvable"] += 1
                resolvable += 1
            elif ref.startswith(INTERNAL_REF_PREFIX):
                audit["internal_ids"] += 1
            else:
                audit["unresolvable_paths"].append({"case": row["case"], "blind_id": row.get("blind_id"), "ref": ref})
        if resolvable:
            audit["rows_with_resolvable_ref"] += 1
        else:
            audit["rows_without_resolvable_ref"] += 1
    audit["resolvable_rate"] = round(audit["resolvable"] / audit["refs"], 3) if audit["refs"] else None
    return audit


def arm_metrics(rows, cls, grade_by_id, arm, pass_no=1, keymap=None, refs_index=None):
    keymap = keymap or {}
    stats = Counter()
    hits = set()
    per_axis = defaultdict(lambda: Counter())
    unclassified = 0
    for row in rows:
        union_id = keymap.get((arm, pass_no, row["blind_id"]), row["blind_id"])
        judged = label(union_id, cls)
        if judged is None:
            unclassified += 1
            continue
        kind = kind_of(judged)
        stats[kind] += 1
        if kind == "hit":
            gold_ids = judged.get("gold_ids") or [judged.get("gold_id")]
            gold_ids = [g for g in gold_ids if g and g != "none"]
            hits |= set(gold_ids)
            axes = row.get("axes") or [row.get("axis")]
            for gold_id in gold_ids:
                primary = (grade_by_id.get(gold_id) or {}).get("primary_axis")
                if primary:
                    per_axis[primary]["total"] += 1
                    per_axis[primary]["attributed"] += 1 if primary in axes else 0
    fp = sum(stats[k] for k in FP_KINDS)
    classified = sum(stats[k] for k in stats if k != "total")
    specific = sum(1 for row in rows if row.get("refs"))
    described = sum(1 for row in rows if (row.get("observed") or "").strip())
    return {"total": len(rows), "classified": classified, "unclassified": unclassified,
            "hit": stats["hit"], "out_of_list_real": stats["out_of_list_real"],
            "split": stats["split"], "overclaim": stats["overclaim"],
            "contradicted": stats["contradicted"], "other_false_positive": stats["other_false_positive"],
            "unclear": stats["unclear"],
            "false_positive": fp,
            "false_positive_rate": round(fp / classified, 3) if classified else None,
            "with_refs_rate": round(specific / len(rows), 3) if rows else None,
            "with_observed_rate": round(described / len(rows), 3) if rows else None,
            "refs_audit": refs_audit(rows, refs_index or {}) if refs_index is not None else None,
            "hits": sorted(hits), "per_axis": {k: dict(v) for k, v in per_axis.items()}}


def overlap_consistency(a_rows, b_rows):
    """两遍之间的问题文本/证据是否稳定：按 (case, axis) 分组，refs 交集≥较小集合一半算同一条。"""
    def grouped(rows):
        out = defaultdict(list)
        for row in rows:
            out[(row["case"], row.get("axis") or "|".join(row.get("axes") or []))].append(set(row["refs"]))
        return out

    left, right = grouped(a_rows), grouped(b_rows)
    matched = comparable = 0
    for key, refs_list in left.items():
        candidates = right.get(key)
        if not candidates:
            continue
        for refs in refs_list:
            comparable += 1
            best = max((len(refs & other) / max(1, min(len(refs), len(other))) for other in candidates), default=0.0)
            matched += 1 if best >= 0.5 else 0
    return {"comparable": comparable, "matched": matched,
            "overlap": round(matched / comparable, 3) if comparable else None}


def verdict_agreement(arm: str, first: int, second: int):
    def load_verdicts(pass_no):
        root = io.HERE / "runs" / arm / f"pass{pass_no}"
        out = {}
        for path in sorted(root.glob("*/*.json")):
            record = io.load_json(path)
            out[(path.parent.name, path.name)] = ((record.get("assessment") or {}).get("verdict")
                                                  if arm == "current" else record.get("verdict"))
        return out

    left, right = load_verdicts(first), load_verdicts(second)
    shared = sorted(set(left) & set(right))
    agree = sum(1 for key in shared if left[key] == right[key])
    return {"shared_axes": len(shared), "agree": agree,
            "agreement": round(agree / len(shared), 3) if shared else None,
            "disagreements": [{"case": k[0], "axis": k[1].replace(".json", ""),
                               "pass1": left[k], "pass2": right[k]}
                              for k in shared if left[k] != right[k]]}


def cost(arm: str, pass_no: int):
    root = io.HERE / "runs" / arm / f"pass{pass_no}"
    calls = prompt = completion = 0
    for path in sorted(root.glob("*/*.json")):
        record = io.load_json(path)
        attempts = record.get("http_attempts") or []
        if arm in ("new", "new2", "new3", "new4"):
            attempts = [a for batch in record.get("batches") or [] for a in batch.get("http_attempts") or []]
        calls += len(attempts)
        prompt += sum(a.get("prompt_tokens") or 0 for a in attempts)
        completion += sum(a.get("completion_tokens") or 0 for a in attempts)
    manifest = root / "manifest.json"
    if manifest.exists():
        elapsed = io.load_json(manifest).get("elapsed_seconds")
    else:  # 运行被外部原因中断时没有 manifest，用各轴自己的耗时求和
        elapsed = round(sum(io.load_json(path).get("elapsed_seconds") or 0
                            for path in sorted(root.glob("*/*.json"))), 1)
    return {"calls": calls, "prompt_tokens": prompt, "completion_tokens": completion,
            "elapsed_seconds": elapsed}


def main():
    pass_no = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    gold, problems, cls, keymap, refs_index = load(pass_no)
    grade_by_id = {item["id"]: item for item in gold}
    hard = {item["id"] for item in gold if item["grade"] == "hard"}
    soft = {item["id"] for item in gold if item["grade"] == "soft"}
    report = {"pass": pass_no, "gold": {"hard": len(hard), "soft": len(soft)}, "arms": {}}
    for name, rows in variants(problems).items():
        arm = {"current": "current", "new2": "new2", "new3": "new3", "new4": "new4", "impl": "impl"}.get(name, "new")
        metrics = arm_metrics(rows, cls, grade_by_id, arm, pass_no, keymap, refs_index)
        metrics["recall_hard"] = round(len(set(metrics["hits"]) & hard) / len(hard), 3)
        metrics["recall_soft"] = round(len(set(metrics["hits"]) & soft) / len(soft), 3)
        missed = sorted(hard - set(metrics["hits"]))
        metrics["missed_hard"] = missed
        metrics["missed_hard_primary_axis"] = Counter(grade_by_id[i]["primary_axis"] for i in missed)
        metrics["missed_hard_primary_axis"] = dict(metrics["missed_hard_primary_axis"])
        metrics["cost"] = cost(arm, pass_no)
        report["arms"][name] = metrics
    second_path = io.HERE / "problems" / f"pass{2}.json"
    if pass_no != 2 and second_path.exists():
        second = variants(io.load_json(second_path))
        for name, rows in variants(problems).items():
            if name in ("new2", "new3", "new4", "impl"):
                continue
            arm = "current" if name == "current" else "new"
            report["arms"][name]["overlap_pass1_pass2"] = overlap_consistency(rows, second[name])
            report["arms"][name]["verdict_agreement"] = verdict_agreement(arm, pass_no, 2)
    io.save_json(io.HERE / "score" / f"pass{pass_no}.json", report, exclusive=False)
    for arm, metrics in report["arms"].items():
        print(f"== {arm}: total={metrics['total']} hit={metrics['hit']} "
              f"recall_hard={metrics['recall_hard']} recall_soft={metrics['recall_soft']} "
              f"out_of_list_real={metrics['out_of_list_real']} fp={metrics['false_positive']} "
              f"fpr={metrics['false_positive_rate']} calls={metrics['cost']['calls']} "
              f"elapsed={metrics['cost']['elapsed_seconds']}")
        print(f"   missed_hard={metrics['missed_hard']}")
        print(f"   per_axis={metrics['per_axis']} with_refs={metrics['with_refs_rate']} "
              f"with_observed={metrics['with_observed_rate']}")
        if metrics.get("unclassified"):
            print(f"   !! 未分类 {metrics['unclassified']} 条，召回/误报数仅覆盖已分类部分")
        if metrics.get("refs_audit"):
            audit = metrics["refs_audit"]
            print(f"   引用核验: {audit['resolvable']}/{audit['refs']} 可解析（{audit['resolvable_rate']}），"
                  f"内部定位符 {audit['internal_ids']}，无法解析 {len(audit['unresolvable_paths'])}，"
                  f"条目有可解析引用 {audit['rows_with_resolvable_ref']}/{metrics['total']}")
        if "overlap_pass1_pass2" in metrics:
            print(f"   overlap={metrics['overlap_pass1_pass2']} verdict_agreement={metrics['verdict_agreement']['agreement']}")


if __name__ == "__main__":
    main()
