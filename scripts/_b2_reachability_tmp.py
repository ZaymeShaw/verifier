"""B2 可达性抽查：用「清单 + read」重走 5 个有人工结论的冻结样本的取证路径。

计划里的用途有两个：
1. 验证历史判词引用过的每条证据，是否都能由清单定位、由取证件读到（可达性）；
2. 记录「读几次、读进多少字符」，作为侦探预算（工具调用上限 / 单次读取上限）的标定依据。

离线可跑，不打 LLM。输出 report/process-dossier-20260920/evidence-index/b2-reachability.json。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from impl.core.schema import RunTrace  # noqa: E402
from impl.projects.llm_probe.business_trace.dossier import (  # noqa: E402
    build_catalog, build_dossier, catalog_ids)
from impl.projects.llm_probe.business_trace.tools import EvidenceIndex  # noqa: E402

FROZEN = ROOT / "report/business-trace-agno-20260913/snapshots"
RESULTS = ROOT / "report/process-dossier-20260920/results"
OUT = ROOT / "report/process-dossier-20260920/evidence-index"
REF_KEYS = ("evidence_refs",)


def _frozen_trace(path: Path) -> RunTrace:
    snapshot = json.loads(path.read_text())
    run = snapshot["records"]["run"]
    request = run.get("run_input") if isinstance(run.get("run_input"), dict) else {}
    return RunTrace(
        trace_id=f"replay-{path.stem}", project_id="llm_probe", case_id=f"frozen-{path.stem[5:]}",
        normalized_request={"capability_ref": "insurance-agno-e2e",
                            "body": request.get("body") or {"messages": [{"role": "user", "content": str(run.get("run_input") or "")}]}},
        extracted_output={"output_text": run.get("content")},
        project_fields={"business_trace": snapshot},
    )


def _citations(row: dict) -> list[str]:
    """历史判词引用过的编号：逐轴 checks + 主轴 + 分析轴的选段与路线。"""
    found: list[str] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in REF_KEYS and isinstance(child, list):
                    found.extend(str(item) for item in child if isinstance(item, str))
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(row)
    return found


def walk_sample(name: str, path: Path) -> dict:
    result_path = RESULTS / f"frozen--snap-{name}.json"
    trace = _frozen_trace(path)
    dossier = build_dossier(trace, trace.project_fields.get("business_trace"))
    ids = catalog_ids(build_catalog(dossier))
    index = EvidenceIndex(dossier)
    citations = _citations(json.loads(result_path.read_text()) if result_path.exists() else {})
    unique = sorted(set(citations))
    steps = 0
    chars = 0
    missing: list[str] = []
    for ref in unique:
        if ref not in ids or not index.knows(ref):
            missing.append(ref)
            continue
        steps += 1
        seen_chars = 0
        paths = [""]
        # 与侦探同规则：节点过大就下钻，预算按实际读入算
        while paths:
            path = paths.pop(0)
            out = index.read(ref, path)
            steps += 1
            if out.get("error"):
                missing.append(f"{ref}{path}")
                break
            seen_chars += out["chars"] if out.get("too_large") else len(out.get("text") or "")
            if out.get("too_large"):
                paths.extend(f"{path}/{key}" for key in list(out["shape"])[:3] if key != "...")
        chars += seen_chars
    return {"sample": name, "citations": len(unique), "reachable": len(unique) - len(missing),
            "missing": missing, "reads": steps, "chars_read": chars, "catalog_entries": len(ids)}


def main() -> None:
    rows = [walk_sample(path.stem[5:], path) for path in sorted(FROZEN.glob("snap-*.json"))]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b2-reachability.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1))
    for row in rows:
        print(f"{row['sample']:16s} 引用 {row['citations']:3d} 可达 {row['reachable']:3d} "
              f"读取 {row['reads']:3d} 次 读入 {row['chars_read']:8d} 字符 目录 {row['catalog_entries']:3d} 条 "
              f"缺失 {row['missing'][:2]}")
    total = sum(row["citations"] for row in rows)
    reachable = sum(row["reachable"] for row in rows)
    print(f"合计 {reachable}/{total} 可达；读取 {sum(r['reads'] for r in rows)} 次，"
          f"读入 {sum(r['chars_read'] for r in rows)} 字符")
    print("已写入", (OUT / "b2-reachability.json").relative_to(ROOT))


if __name__ == "__main__":
    main()
