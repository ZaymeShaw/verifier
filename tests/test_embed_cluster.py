import json

import numpy as np

from scripts import embed_cluster as ec

# 三组近似方向：同组余弦相似度约 0.99，组间约 0
VEC = {"a1": [1, 0.05, 0], "a2": [1, -0.05, 0], "a3": [1, 0, 0.05],
       "b1": [0, 1, 0.05], "b2": [0, 1, -0.05], "c": [0, 0, 1]}


class FakeEmbed:
    def __init__(self):
        self.requested: list[str] = []

    def __call__(self, texts):
        self.requested += list(texts)
        return [VEC[t] for t in texts]


def _assign(texts, threshold=0.9, method="complete", cache=None, embed=None):
    embed = embed or FakeEmbed()
    cache = cache or ec.VectorCache(None, "fake")
    ids, _, requested = ec.assign_clusters(texts, embed, cache, threshold=threshold, method=method, batch_size=2)
    return ids, requested


def test_groups_by_similarity_and_names_by_size():
    ids, _ = _assign(["c", "b1", "a1", "a2", "b2", "a3"])
    assert ids == ["c2", "c1", "c0", "c0", "c1", "c0"]


def test_threshold_one_splits_everything():
    ids, _ = _assign(["a1", "a2", "a3"], threshold=1.0)
    assert len(set(ids)) == 3


def test_complete_linkage_does_not_chain():
    # x-y、y-z 相似度约 0.92，x-z 约 0.71：single 会串成一簇，complete 不会
    vec = {"x": [1, 0], "y": [np.cos(0.4), np.sin(0.4)], "z": [np.cos(0.8), np.sin(0.8)]}
    embed = lambda texts: [vec[t] for t in texts]  # noqa: E731
    single, _ = _assign(["x", "y", "z"], threshold=0.9, method="single", embed=embed)
    complete, _ = _assign(["x", "y", "z"], threshold=0.9, method="complete", embed=embed)
    assert len(set(single)) == 1 and len(set(complete)) == 2


def test_duplicates_embedded_once_and_same_cluster():
    embed = FakeEmbed()
    ids, requested = _assign(["a1", "c", "a1"], embed=embed)
    assert embed.requested == ["a1", "c"] and requested == 2
    assert ids[0] == ids[2]


def test_cache_avoids_second_request(tmp_path):
    path = tmp_path / "cache.jsonl"
    _assign(["a1", "b1"], cache=ec.VectorCache(path, "fake"))
    embed = FakeEmbed()
    _, requested = _assign(["a1", "b1", "c"], cache=ec.VectorCache(path, "fake"), embed=embed)
    assert embed.requested == ["c"] and requested == 1
    # 换模型不复用
    embed2 = FakeEmbed()
    _assign(["a1"], cache=ec.VectorCache(path, "other"), embed=embed2)
    assert embed2.requested == ["a1"]


def test_main_keeps_columns_and_joins_list_text(tmp_path):
    rows = [{"id": "q1", "turns": ["a1"], "src": "x"}, {"id": "q2", "turns": ["a2"], "src": "y"},
            {"id": "q3", "turns": ["c"], "src": "z"}]
    inp, out, rep = tmp_path / "in.jsonl", tmp_path / "out.jsonl", tmp_path / "rep.json"
    inp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    code = ec.main(["--input", str(inp), "--output", str(out), "--text-column", "turns", "--report", str(rep)],
                   embed_factory=lambda _args: (FakeEmbed(), "fake"))
    assert code == 0
    got = [json.loads(line) for line in out.read_text().splitlines()]
    assert [g["src"] for g in got] == ["x", "y", "z"]
    assert got[0]["cluster_id"] == got[1]["cluster_id"] != got[2]["cluster_id"]
    assert json.loads(rep.read_text())["clusters"][0]["size"] == 2


def test_xlsx_output_puts_id_and_cluster_first(tmp_path):
    from openpyxl import load_workbook
    rows = [{"src": "x", "id": "q1", "turns": ["a1"]}, {"src": "y", "id": "q2", "turns": ["c"]}]
    inp, out = tmp_path / "in.jsonl", tmp_path / "out.xlsx"
    inp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert ec.main(["--input", str(inp), "--output", str(out), "--text-column", "turns"],
                   embed_factory=lambda _args: (FakeEmbed(), "fake")) == 0
    got = list(load_workbook(out).active.values)
    assert got[0] == ("id", "cluster_id", "src", "turns")
    assert got[1] == ("q1", "c0", "x", '["a1"]')


def test_record_text_joins_turns():
    assert ec.record_text(["a", "b"]) == "a\nb"


def test_fine_threshold_nests_and_names_by_parent():
    # x-y、y-z 约 0.92，x-z 约 0.70；0.6 下一簇，0.9 下拆成 {x,y} 和 {z}；w 单独
    vec = {"x": [1, 0, 0], "y": [np.cos(0.4), np.sin(0.4), 0], "z": [np.cos(0.8), np.sin(0.8), 0], "w": [0, 0, 1]}
    embed = lambda texts: [vec[t] for t in texts]  # noqa: E731
    ids, fine, _ = ec.assign_clusters(["w", "x", "y", "z"], embed, ec.VectorCache(None, "fake"),
                                      threshold=0.6, method="complete", batch_size=2, fine_threshold=0.9)
    assert ids == ["c1", "c0", "c0", "c0"]
    assert fine[0] == "c1.0" and fine[1] == fine[2] == "c0.0" and fine[3] == "c0.1"


def test_main_fine_column(tmp_path):
    rows = [{"id": "q1", "turns": ["a1"]}, {"id": "q2", "turns": ["c"]}]
    inp, out = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    inp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert ec.main(["--input", str(inp), "--output", str(out), "--text-column", "turns", "--threshold", "0.5",
                    "--fine-threshold", "0.9"], embed_factory=lambda _args: (FakeEmbed(), "fake")) == 0
    got = [json.loads(line) for line in out.read_text().splitlines()]
    assert list(got[0]) == ["id", "cluster_id", "fine_cluster_id", "turns"]
    assert [g["fine_cluster_id"] for g in got] == ["c0.0", "c1.0"]
