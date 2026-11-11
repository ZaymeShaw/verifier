"""在默认 GBK 文本编码下验证 UTF-8 输入、缓存、报告和 Excel 交付。"""
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from scripts import cluster_sample as cs
from scripts import embed_cluster as ec


@pytest.mark.parametrize("suffix", [".jsonl", ".csv"])
@pytest.mark.parametrize("bom", [False, True])
def test_utf8_pipeline_under_gbk_default(tmp_path, monkeypatch, suffix, bom):
    # Path.read_text 经 io.text_encoding 把默认值转换为 "locale"。
    original_open = Path.open

    def gbk_open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "gbk"
        return original_open(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", gbk_open)
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.test/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "encoding-test")
    inp = tmp_path / ("题目" + suffix)
    rows = [{"id": "题一", "text": "如何退款😀？"}, {"id": "题二", "text": "怎么下载发票？"}]
    cs.write_records(inp, rows, ["id", "text"])
    raw = inp.read_bytes()
    assert "如何退款😀？" in raw.decode("utf-8")
    if bom:
        inp.write_bytes(b"\xef\xbb\xbf" + raw)
    assert cs.read_records(inp)[0] == rows

    clustered, cluster_report, cache = [tmp_path / n for n in ("clustered.jsonl", "cluster-report.json", "cache.jsonl")]
    vectors = {rows[0]["text"]: [1, 0], rows[1]["text"]: [0, 1]}
    factory = lambda args: (lambda texts: [vectors[t] for t in texts], "中文模型")
    assert ec.main(["--input", str(inp), "--output", str(clustered), "--report", str(cluster_report),
                    "--cache", str(cache)], embed_factory=factory) == 0
    assert len(ec.VectorCache(cache, "中文模型").vectors) == 2
    assert json.loads(cluster_report.read_bytes().decode("utf-8"))["clusters"][0]["members"][0]["text"] == rows[0]["text"]

    report = tmp_path / "sample-report.json"
    excel = tmp_path / "sampled.xlsx"
    # 用中文簇 ID 确认采样报告也显式写 UTF-8，而不只测试 ASCII 元数据。
    records, columns = cs.read_records(clustered)
    for row in records:
        row["cluster_id"] = "簇😀" + row["cluster_id"]
    cs.write_records(clustered, records, columns)
    assert cs.main(["--input", str(clustered), "--output", str(excel), "--total", "2",
                    "--tail-bins", "", "--single-max-size", "0", "--report", str(report)]) == 0
    assert "簇😀" in report.read_bytes().decode("utf-8")
    workbook = load_workbook(excel, read_only=True)
    try:
        values = list(workbook.active.values)
        actual = [dict(zip(values[0], row)) for row in values[1:]]
        assert [{k: row[k] for k in ("id", "text")} for row in actual] == rows
    finally:
        workbook.close()
