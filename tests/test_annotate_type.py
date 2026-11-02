import json

from scripts import annotate_type as at


def test_source_type_mapping():
    assert at.source_type("外部/product_qa") == "产品知识"
    assert at.source_type("生产/client_ops_weekly") == "客户筛选"
    assert at.source_type("生产/standard_llm_log") == at.MIXED
    assert at.source_type("合成/product") == at.UNMAPPED


def test_cli_appends_type_column(tmp_path):
    src, out = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    src.write_text("".join(json.dumps({"id": i, "source": s}, ensure_ascii=False) + "\n"
                           for i, s in [("a", "生产/faq_log"), ("b", "合成/sales")]))
    assert at.main(["--input", str(src), "--output", str(out)]) == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [(r["id"], r["type"]) for r in rows] == [("a", "业务办理与FAQ"), ("b", at.UNMAPPED)]


def test_cli_rejects_existing_type_column(tmp_path):
    src = tmp_path / "in.jsonl"
    src.write_text(json.dumps({"id": "a", "source": "生产/faq_log", "type": "x"}) + "\n")
    assert at.main(["--input", str(src), "--output", str(tmp_path / "o.jsonl")]) == 2
