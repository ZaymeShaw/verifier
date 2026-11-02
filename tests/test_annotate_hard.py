import json
import sys

import pytest

from scripts import annotate_hard as ah

TAGS_PY = '''
import yaml
from pathlib import Path
BENCH = Path(__file__).resolve().parents[1]
def load_hard_case():
    rule = yaml.safe_load((BENCH / "hard_case.yaml").read_text(encoding="utf-8"))
    rule["axis"] = {t: a for a, tags in rule["难点"].items() for t in tags}
    rule["hard"] = list(rule["axis"])
    return rule
def hard_case(tags, hard, exclude):
    hits, excluded = [t for t in hard if t in tags], [t for t in exclude if t in tags]
    return bool(hits) and not excluded, hits, excluded
'''


@pytest.fixture
def bench(tmp_path):
    root = tmp_path / "benchmark"
    (root / "tools").mkdir(parents=True)
    (root / "labels").mkdir()
    (root / "tools" / "tags.py").write_text(TAGS_PY)
    (root / "hard_case.yaml").write_text(
        "难点:\n  工具:\n    - 难点.工具:相对时间\n    - 难点.工具:冷门字段\nexclude:\n  - 无效输入\n")
    # 冷门字段不在 usable 里：命中它不算 hard
    (root / "labels" / "L.meta.yaml").write_text("usable: [难点.工具:相对时间, 无效输入]\n")
    labels = [{"id": "a", "tags": ["难点.工具:相对时间", "问法:短句"]},
              {"id": "b", "tags": ["难点.工具:冷门字段"]},
              {"id": "c", "tags": ["难点.工具:相对时间", "无效输入"]}]
    (root / "labels" / "L.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in labels))
    yield root
    sys.modules.pop("tags", None)
    sys.path[:] = [p for p in sys.path if p != str(root / "tools")]


def test_annotate_follows_usable_and_exclude(bench, tmp_path):
    src, out = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    src.write_text("".join(json.dumps({"id": i, "segment": "tail:1"}) + "\n" for i in ["a", "b", "c", "z"]))
    assert ah.main(["--input", str(src), "--output", str(out), "--bench", str(bench), "--labels", "L"]) == 0
    rows = {r["id"]: r for r in map(json.loads, out.read_text().splitlines())}
    assert list(rows["a"]) == ["id", "segment", "tags", "hard", "hard_hits"]
    assert (rows["a"]["hard"], rows["a"]["hard_hits"]) == (True, ["难点.工具:相对时间"])
    assert (rows["b"]["hard"], rows["b"]["hard_hits"]) == (False, [])
    assert (rows["c"]["hard"], rows["c"]["hard_hits"]) == (False, ["难点.工具:相对时间"])
    assert rows["c"]["tags"] == ["难点.工具:相对时间", "无效输入"]
    assert rows["z"]["tags"] is None and rows["z"]["hard"] is None


def test_xlsx_keeps_tags_in_one_cell(bench, tmp_path):
    from openpyxl import load_workbook
    src, out = tmp_path / "in.jsonl", tmp_path / "out.xlsx"
    src.write_text(json.dumps({"id": "a"}) + "\n")
    assert ah.main(["--input", str(src), "--output", str(out), "--bench", str(bench), "--labels", "L"]) == 0
    header, row = list(load_workbook(out).active.values)
    assert header == ("id", "tags", "hard", "hard_hits")
    assert json.loads(row[1]) == ["难点.工具:相对时间", "问法:短句"] and row[2] is True


def test_existing_output_column_rejected(bench, tmp_path):
    src = tmp_path / "in.jsonl"
    src.write_text(json.dumps({"id": "a", "hard": True}) + "\n")
    assert ah.main(["--input", str(src), "--output", str(tmp_path / "o.jsonl"), "--bench", str(bench),
                    "--labels", "L"]) == 2
