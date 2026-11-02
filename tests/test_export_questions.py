import json

import pytest

from scripts import export_questions as eq


def write(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")


def q(id_, text):
    return {"id": id_, "scenario": "s", "env": {"data": "none"}, "turns": [text], "source": {"type": "real-log"}}


def test_export_orders_by_path_and_keeps_fields(tmp_path):
    root = tmp_path / "benchmark"
    write(root / "questions" / "生产" / "faq_log.jsonl", [q("faq-2", "b"), q("faq-1", "a")])
    write(root / "questions" / "合成" / "benefit.jsonl", [q("benefit-1", "c")])
    out = tmp_path / "out.jsonl"

    assert eq.main(["--bench", str(root), "--output", str(out)]) == 0

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in rows] == ["benefit-1", "faq-2", "faq-1"]
    assert rows[1] == {"id": "faq-2", "source": "生产/faq_log", "scenario": "s", "turns": ["b"]}


def test_export_rejects_duplicate_id(tmp_path):
    write(tmp_path / "生产" / "a.jsonl", [q("x", "a")])
    write(tmp_path / "生产" / "b.jsonl", [q("x", "b")])
    with pytest.raises(ValueError, match="重复 id"):
        eq.export(tmp_path)
