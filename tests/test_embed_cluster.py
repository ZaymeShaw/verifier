import json

import numpy as np
import httpx
import pytest

from scripts import embed_cluster as ec


@pytest.fixture(autouse=True)
def embedding_environment(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.test/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embedding")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-secret")


def mock_http(monkeypatch, handler):
    init = httpx.Client.__init__
    monkeypatch.setattr(httpx.Client, "__init__", lambda self, **kwargs: init(
        self, transport=httpx.MockTransport(handler), **kwargs))

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


@pytest.mark.parametrize("fine", [False, True])
def test_extra_excel_matches_jsonl_without_repeating_embeddings(tmp_path, fine):
    from openpyxl import load_workbook
    rows = [{"id": "q1", "turns": ["a1"], "meta": {"来源": "样例"}},
            {"id": "q2", "turns": ["c"], "meta": {"来源": "其他"}}]
    inp, out, excel = [tmp_path / name for name in ("in.jsonl", "clustered.jsonl", "clustered.xlsx")]
    inp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    embed = FakeEmbed()
    args = ["--input", str(inp), "--output", str(out), "--excel-output", str(excel), "--text-column", "turns"]
    if fine:
        args += ["--fine-threshold", "0.95"]
    assert ec.main(args, embed_factory=lambda _: (embed, "fake")) == 0
    assert embed.requested == ["a1", "c"]
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    book = load_workbook(excel)
    values = list(book.active.values)
    assert book.active.freeze_panes == "A2"
    assert ("fine_cluster_id" in values[0]) == fine
    assert values[1:] == [tuple(json.dumps(r[k], ensure_ascii=False) if isinstance(r[k], (list, dict)) else r[k]
                                for k in values[0]) for r in records]
    assert isinstance(records[0]["turns"], list) and isinstance(records[0]["meta"], dict)
    book.close()


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


def test_openai_endpoint_and_cache_end_to_end(tmp_path, monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer test-secret"
        assert body == {"model": "test-embedding", "input": ["a1", "a2", "c"], "encoding_format": "float"}
        return httpx.Response(200, json={"object": "list", "model": body["model"],
            "data": [{"object": "embedding", "index": i, "embedding": VEC[t]}
                     for i, t in reversed(list(enumerate(body["input"])))],
            "usage": {"prompt_tokens": 3, "total_tokens": 3}})

    mock_http(monkeypatch, handle)
    inp, out, cache, report = [tmp_path / name for name in ("in.jsonl", "out.jsonl", "cache.jsonl", "report.json")]
    inp.write_text("".join(json.dumps({"id": i, "text": t}) + "\n" for i, t in enumerate(["a1", "a2", "c"])))
    argv = ["--input", str(inp), "--output", str(out), "--cache", str(cache), "--report", str(report)]
    assert ec.main(argv) == 0
    got = [json.loads(line) for line in out.read_text().splitlines()]
    assert [row["cluster_id"] for row in got] == ["c0", "c0", "c1"]
    assert str(requests[0].url) == "https://embedding.test/v1/embeddings"
    assert ec.main(argv) == 0
    assert len(requests) == 1
    assert ec.main(argv + ["--base-url", "https://other.test/api/v1/"]) == 0
    assert len(requests) == 2
    assert str(requests[-1].url) == "https://other.test/api/v1/embeddings"
    assert "test-secret" not in cache.read_text() + report.read_text()


def test_openai_optional_parameters_and_named_key(monkeypatch):
    monkeypatch.setenv("CUSTOM_EMBED_KEY", "custom-secret")

    def handle(request):
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer custom-secret"
        assert body == {"model": "other-model", "input": ["a1"], "encoding_format": "float",
                        "dimensions": 3, "instruct": "Cluster texts"}
        assert request.extensions["timeout"]["read"] == 90
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": VEC["a1"]}]})

    mock_http(monkeypatch, handle)
    args = ec.parse_args(["--input", "in.jsonl", "--output", "out.jsonl", "--model", "other-model",
                          "--dimension", "3", "--extra-body", '{"instruct":"Cluster texts"}',
                          "--api-key-env", "CUSTOM_EMBED_KEY", "--timeout", "90"])
    embed, identity = ec.openai_embed(args)
    assert embed(["a1"]) == [VEC["a1"]]
    assert json.loads(identity)["model"] == "other-model"


@pytest.mark.parametrize("data", [
    [{"index": 1, "embedding": [1, 0]}],
    [{"index": 0, "embedding": [1, 0]}, {"index": 0, "embedding": [0, 1]}],
    [{"index": 0, "embedding": [0, 0]}],
    [{"index": 0, "embedding": []}],
    [{"index": 0, "embedding": [1, 0, 0]}],
])
def test_invalid_embedding_response_is_not_cached(tmp_path, monkeypatch, data):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"data": data}))
    args = ec.parse_args(["--input", "in.jsonl", "--output", "out.jsonl", "--dimension", "2"])
    embed, identity = ec.openai_embed(args)
    cache = ec.VectorCache(tmp_path / "cache.jsonl", identity)
    with pytest.raises(ValueError):
        ec.embed_texts(["a1"], embed, cache, 20)
    assert not cache.vectors and not cache.path.exists()


def test_api_failure_propagates_without_cache_or_retry(tmp_path, monkeypatch):
    from openai import RateLimitError
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(429, json={"error": {"message": "rate limited", "type": "rate_limit"}})

    mock_http(monkeypatch, handle)
    args = ec.parse_args(["--input", "in.jsonl", "--output", "out.jsonl"])
    embed, identity = ec.openai_embed(args)
    cache = ec.VectorCache(tmp_path / "cache.jsonl", identity)
    with pytest.raises(RateLimitError):
        ec.embed_texts(["a1"], embed, cache, 20)
    assert len(requests) == 1 and not cache.path.exists()


def test_missing_key_fails_before_request(monkeypatch):
    monkeypatch.delenv("EMBEDDING_API_KEY")
    args = ec.parse_args(["--input", "in.jsonl", "--output", "out.jsonl"])
    with pytest.raises(SystemExit, match="EMBEDDING_API_KEY"):
        ec.openai_embed(args)


@pytest.mark.parametrize("flags", [
    ["--dimension", "0"], ["--timeout", "nan"], ["--extra-body", "[]"],
    ["--extra-body", '{"model":"hidden-override"}'], ["--base-url", "not-a-url"],
])
def test_invalid_api_options_are_rejected(flags):
    with pytest.raises(SystemExit):
        ec.parse_args(["--input", "in.jsonl", "--output", "out.jsonl", *flags])
