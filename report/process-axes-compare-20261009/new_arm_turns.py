"""新方案 v4 臂（new4）：在 new3（逐字引文 + 通用职责）上只改发送方式——多轮追加，让前缀命中缓存。

  第一次：[system, user1]                                   user1 = 本应清单任务 + 输入端材料
  第二次：[system, user1, assistant(冻结的本应清单), user2]  user2 = 实际清单任务 + 只含新增内容的补充材料
  重写：  [... , assistant(实际清单), user3]                  user3 = 引文核对未通过的清单

两次材料都从同一份完整视图（= new3 第二次的材料）切出来，编号一致：user1 只留第一次视图里有的记录和字段
（输出端字段本来就不在里面），user2 放其余字段和它们引用的内容。合起来与完整视图逐字段相同（`split_check`）。
system 两次逐字相同；输出结构约束放在各自 user 末尾（见 CACHE-FINDINGS.md：新一轮追加才稳定命中缓存）。

用法：python new_arm_turns.py --pass 1 [--tags a,b]    （结果在 runs/new4/pass<N>/）
     python new_arm_turns.py --split-check               （离线核对切分无损，不调模型）
"""
from __future__ import annotations

import copy
import json
import re
import sys
import traceback

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

import new_arm as N  # noqa: E402
import new_arm_quotes as Q  # noqa: E402
from cmp_view import normalize  # noqa: E402
from llm_transport import Transport, render_output_constraint  # noqa: E402

ARM = "new4"
N.ARM = ARM

SYSTEM = ("你是过程评测员。这次评测分两步：第一步只看输入端材料，写「本应清单」；第二步拿到输出端补充材料，"
          "逐条核对，写「实际清单」。每一步的具体要求和输出结构写在该步的消息里；前一步给过的材料后一步仍然有效，编号沿用。")
TOKEN = re.compile(r"(?:shared|content)#\d+")
META = ("format", "gaps", "missing_endpoints", "excluded", "input_limitations", "reading_guide")


def _tables(view):
    return dict(view.get("shared_contents") or {}), dict(view.get("contents") or {})


def _closure(obj, shared, contents):
    """obj 直接或间接引用到的全部 shared#/content# 编号。"""
    todo, seen = set(TOKEN.findall(json.dumps(obj, ensure_ascii=False))), set()
    while todo:
        key = todo.pop()
        if key in seen:
            continue
        seen.add(key)
        body = shared.get(key) if key.startswith("shared#") else contents.get(key)
        todo |= set(TOKEN.findall(json.dumps(body, ensure_ascii=False))) - seen
    return seen


def _pack(records, keys, shared, contents, meta):
    return {**meta, "records": records,
            "shared_contents": {k: shared[k] for k in sorted(keys) if k in shared},
            "contents": {k: contents[k] for k in sorted(keys) if k in contents}}


def split_views(c1, full):
    """把完整视图 full 切成 (user1 材料, user2 材料)。user1 的记录与字段集合 ⊆ 第一次视图 c1。"""
    shared, contents = _tables(full)
    allowed = {rec.get("id"): rec for rec in c1.get("records") or []}
    first, second = [], []
    for rec in full.get("records") or []:
        seen = allowed.get(rec.get("id"))
        if seen is None:
            second.append(rec)
            continue
        top = {k: v for k, v in rec.items() if k != "fields" and k in seen}
        fields = rec.get("fields") or {}
        keep = {k: v for k, v in fields.items() if k in (seen.get("fields") or {})}
        first.append({**top, "fields": keep})
        rest_top = {k: v for k, v in rec.items() if k != "fields" and k not in seen}
        rest_fields = {k: v for k, v in fields.items() if k not in keep}
        if rest_top or rest_fields:
            second.append({"id": rec.get("id"), **rest_top, "fields": rest_fields})
    k1 = _closure(first, shared, contents)
    k2 = _closure(second, shared, contents) - k1
    m1 = {k: c1.get(k) for k in META if k in c1}
    m2 = {k: full.get(k) for k in META if k in full and k != "format"}
    m2["reading_guide"] = "补充材料：上一轮没给的记录与字段（含输出端），以及它们新引用到的共享内容；编号与上一轮一致。"
    return _pack(first, k1, shared, contents, m1), _pack(second, k2, shared, contents, m2)


def merge(u1, u2):
    out = copy.deepcopy(u1)
    by_id = {rec.get("id"): rec for rec in out["records"]}
    for rec in copy.deepcopy(u2["records"]):
        old = by_id.get(rec.get("id"))
        if old is None:
            out["records"].append(rec)
            by_id[rec.get("id")] = rec
            continue
        fields = rec.pop("fields", {})
        old.update(rec)
        old.setdefault("fields", {}).update(fields)
    out["shared_contents"] = {**out["shared_contents"], **u2["shared_contents"]}
    out["contents"] = {**out["contents"], **u2["contents"]}
    return out


def _canon(view):
    return {r["id"]: r["fields"] for r in normalize(view)}


def split_check():
    """离线：每个 case×轴×批，user1+user2 还原后与完整视图逐字段相同，且 user1 不含第一次视图之外的字段。"""
    bad, n, c1_chars, u1_chars, u2_chars, full_chars = [], 0, 0, 0, 0, 0
    for tag in io.CASES:
        frozen, dossier, analysis = N.build_case(tag)
        suspects = list(analysis["structure"].get("suspects") or [])
        for axis in io.AXES:
            extra = list((analysis.get("selections", {}).get(axis) or {}).get("refs") or [])
            for entry in frozen["axes"][axis]:
                links = (entry["body"].get("links") or {}).get("links") or []
                c1 = N.input_only_view(dossier, links)
                full = N.full_view(dossier, links, suspects, extra)
                u1, u2 = split_views(c1, full)
                n += 1
                if _canon(merge(u1, u2)) != _canon(full):
                    bad.append((tag, axis, "merge!=full"))
                drop = {(end["ref"], end.get("field", "")) for link in links for end in link.get("output") or []}
                inputs = {(end["ref"], end.get("field", "")) for link in links for end in link.get("input") or []}
                for rec in normalize(u1):
                    for field in rec["fields"]:
                        if (rec["id"], field) in drop and (rec["id"], field) not in inputs:
                            bad.append((tag, axis, f"leak {rec['id']}.{field}"))
                c1_chars += len(json.dumps(c1, ensure_ascii=False))
                u1_chars += len(json.dumps(u1, ensure_ascii=False))
                u2_chars += len(json.dumps(u2, ensure_ascii=False))
                full_chars += len(json.dumps(full, ensure_ascii=False))
    print(json.dumps({"batches": n, "problems": bad[:20], "problem_count": len(bad),
                      "chars": {"c1(new3 第一次)": c1_chars, "user1": u1_chars, "user2": u2_chars,
                                "full(new3 第二次)": full_chars,
                                "new3 两次合计": c1_chars + full_chars, "new4 两次新发合计": u1_chars + u2_chars}},
                     ensure_ascii=False, indent=1))
    return not bad


def run_batch(axis, frozen, dossier, analysis, body, links, suspects, extra_refs, index, tag_label):
    transport = Transport(N.PROVIDER, N.MODEL, arm=ARM, tag=tag_label)
    c1 = N.input_only_view(dossier, links)
    full = N.full_view(dossier, links, suspects, extra_refs)
    u1, u2 = split_views(c1, full)
    leaves = Q.record_leaves(full)
    record = {"axis": axis, "batch": index, "links": [l["link_id"] for l in links],
              "leak_check": N.leak_check(u1, full, links), "prompts": [], "http_attempts": [], "program_entries": []}
    trace = f"{frozen['run_id']}:{axis}:b{index}"
    try:
        user1 = N.EXPECTED_SYSTEM + "\n\n" + Q.expected_prompt(axis, body, u1)
        expected = transport.complete_json(SYSTEM, user1, trace_id=trace, reasoning_effort="low",
                                           output_spec=N.EXPECTED_SPEC, stage=f"expected_{axis}_b{index}",
                                           constraint_in_user=True)
        expected.pop("metrics", None)
        record["expected"] = expected
        record["expected_sha256"] = io.digest(json.dumps(expected, ensure_ascii=False, sort_keys=True))
        turn1 = [{"role": "user", "content": user1 + "\n\n" + render_output_constraint(N.EXPECTED_SPEC)},
                 {"role": "assistant", "content": json.dumps(expected, ensure_ascii=False)}]
        user2 = Q.ACTUAL_SYSTEM + "\n\n" + json.dumps(
            {"轴": axis, "本应清单": "见上一轮你的回答（已冻结，id 不得增删改）",
             "本轴实际环节表": {"limits": (body.get("links") or {}).get("limits", ""), "links": links},
             "本轴补充材料": u2,
             "写作要求": "逐条写 actual（id 与冻结清单一一对应）、unexpected、problems；"
                         "problems.items 只能引用 no-go 的条目 id 或 unexpected 的 id；上一轮的材料仍然有效。"},
            ensure_ascii=False)
        actual = transport.complete_json(SYSTEM, user2, trace_id=trace, reasoning_effort="low",
                                         output_spec=Q.ACTUAL_SPEC, stage=f"actual_{axis}_b{index}",
                                         history=turn1, constraint_in_user=True)
        actual.pop("metrics", None)
        bad, total = Q.check_quotes(actual, leaves)
        stats = {"total": total, "bad_first": len(bad), "retried": False, "bad_final": len(bad), "demoted": []}
        if bad:
            turn2 = turn1 + [{"role": "user", "content": user2 + "\n\n" + render_output_constraint(Q.ACTUAL_SPEC)},
                             {"role": "assistant", "content": json.dumps(actual, ensure_ascii=False)}]
            fix = json.dumps({"引文核对未通过": bad,
                              "要求": "只改这些引文：换成对应记录里逐字存在的短句（或换对的记录 id）；"
                                      "找不到支撑就把该行改成无法核。其余内容保持不变，完整重新输出。"}, ensure_ascii=False)
            actual = transport.complete_json(SYSTEM, fix, trace_id=trace, reasoning_effort="low",
                                             output_spec=Q.ACTUAL_SPEC, stage=f"actual_fix_{axis}_b{index}",
                                             history=turn2, constraint_in_user=True)
            actual.pop("metrics", None)
            bad, total = Q.check_quotes(actual, leaves)
            stats.update(retried=True, bad_final=len(bad), total_final=total)
        for kind in ("actual", "unexpected"):
            for row in actual.get(kind) or []:
                row["quotes"] = [q for q in row.get("quotes") or [] if not Q._bad_quotes({"quotes": [q]}, leaves)]
        for row in actual.get("actual") or []:
            if row.get("verdict") == "没达到" and not row.get("quotes"):
                stats["demoted"].append({"id": row["id"], "was": row["verdict"]})
                row["verdict"] = "无法核"
        by_id = {r["id"]: r for r in (actual.get("actual") or []) + (actual.get("unexpected") or [])}
        for problem in actual.get("problems") or []:
            problem["refs"] = sorted({q["ref"] for i in problem.get("items") or [] for q in (by_id.get(i) or {}).get("quotes") or []})
        for row in by_id.values():
            row["refs"] = sorted({q["ref"] for q in row.get("quotes") or []})
        record["actual"] = actual
        record["quote_stats"] = stats
    except Exception as exc:  # noqa: BLE001
        record["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()[-3000:]}
    record["prompts"] = [{"stage": "expected"}, {"stage": "actual"}]
    record["http_attempts"] = [{k: v for k, v in a.items() if k not in {"arm", "started_at"}} for a in transport.attempts]
    return record


N.run_batch = run_batch

if __name__ == "__main__":
    if "--split-check" in sys.argv:
        sys.exit(0 if split_check() else 1)
    N.main()
