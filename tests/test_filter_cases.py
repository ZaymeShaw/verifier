import json

import pytest

from scripts import filter_cases as fc
from scripts.cluster_sample import read_records, write_records


def make_input(path, turns_list):
    rows = [{"id": f"q{i}", "turns": json.dumps(t, ensure_ascii=False)} for i, t in enumerate(turns_list)]
    write_records(path, rows, ["id", "turns"])


def fake_factory(bad, calls, fail_on=None):
    """bad: {文本: 原因}；fail_on: 批里含该文本时整批抛错。"""
    def factory(args):
        def judge(texts):
            calls.append(list(texts))
            if fail_on in texts:
                raise RuntimeError("boom")
            return {i: {"reason": bad[t], "note": "n"} for i, t in enumerate(texts) if t in bad}
        return judge
    return factory


def test_case_text_and_batch_prompt():
    assert fc.case_text('["安有护"]') == "安有护"
    assert fc.case_text('["a", "b"]') == "第1轮：a\n第2轮：b"
    assert fc.batch_prompt(["x", "第1轮：a\n第2轮：b"]) == "[1] x\n[2] 第1轮：a / 第2轮：b"


def test_parse_answer_validates():
    assert fc.parse_answer('想想…{"items": [{"id": 2, "reason": "单轮缺上文", "note": "x"}]}', 3) == \
        {1: {"reason": "单轮缺上文", "note": "x"}}
    with pytest.raises(ValueError, match="越界"):
        fc.parse_answer('{"items": [{"id": 4, "reason": "意图不明"}]}', 3)
    with pytest.raises(ValueError, match="未知"):
        fc.parse_answer('{"items": [{"id": 1, "reason": "有效"}]}', 3)


def test_main_batches_maps_and_caches(tmp_path):
    src, out, cache = tmp_path / "in.jsonl", tmp_path / "out.jsonl", tmp_path / "cache.jsonl"
    make_input(src, [["安有护"], ["如果身故了呢"], ["安有护"], ["test"], ["孤儿单"]])
    bad = {"如果身故了呢": "单轮缺上文", "test": "测试或乱码"}
    calls = []
    argv = ["--input", str(src), "--output", str(out), "--cache", str(cache), "--batch-size", "2", "--workers", "1"]

    assert fc.main(argv, fake_factory(bad, calls)) == 0
    rows, _ = read_records(out)
    assert [r["filter_verdict"] for r in rows] == ["保留", "过滤", "保留", "过滤", "保留"]
    assert [r["filter_reason"] for r in rows][:2] == ["有效", "单轮缺上文"]
    assert [len(b) for b in calls] == [2, 2]  # 去重后 4 条，批大小 2

    calls.clear()
    assert fc.main(argv, fake_factory(bad, calls)) == 0
    assert calls == []


def test_main_failed_batch_left_blank_and_retried(tmp_path):
    src, out, cache = tmp_path / "in.jsonl", tmp_path / "out.jsonl", tmp_path / "cache.jsonl"
    make_input(src, [["a"], ["b"], ["c"]])
    argv = ["--input", str(src), "--output", str(out), "--cache", str(cache), "--batch-size", "2", "--workers", "1"]

    assert fc.main(argv, fake_factory({}, [], fail_on="c")) == 1
    rows, _ = read_records(out)
    assert [r["filter_verdict"] for r in rows] == ["保留", "保留", ""]

    calls = []
    assert fc.main(argv, fake_factory({"c": "意图不明"}, calls)) == 0
    assert calls == [["c"]]
    assert read_records(out)[0][2]["filter_verdict"] == "存疑"
