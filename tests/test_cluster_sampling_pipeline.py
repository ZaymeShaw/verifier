import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/cluster-sampling/pipeline.py"
    spec = importlib.util.spec_from_file_location("cluster_sampling_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "MODULE_DIR", tmp_path)
    for name in ("INPUT_PATH", "OUTPUT_DIR", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        'EMBEDDING_BASE_URL="https://embedding.test/v1"\n'
        'EMBEDDING_MODEL="test-embedding"\nEMBEDDING_API_KEY="test-secret"\n')
    (tmp_path / "example-input.jsonl").write_text(json.dumps({"id": "q1", "text": "测试题"}) + "\n")
    return module


def capture_commands(pipeline, monkeypatch, returncode=0):
    calls = []

    def run(command, *, env, check):
        calls.append((command, env))
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(pipeline.subprocess, "run", run)
    return calls


def option(command, name):
    return command[command.index(name) + 1]


def test_default_paths_are_relative_to_module_and_reused(pipeline, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    calls = capture_commands(pipeline, monkeypatch)
    assert pipeline.main(["--total", "1", "--fine-threshold", "0.85"]) == 0
    cluster, sample = calls[0][0], calls[1][0]
    assert Path(cluster[1]) == pipeline.SCRIPTS_DIR / "embed_cluster.py"
    assert Path(sample[1]) == pipeline.SCRIPTS_DIR / "cluster_sample.py"
    assert option(cluster, "--input") == str(tmp_path / "example-input.jsonl")
    assert option(sample, "--input") == option(cluster, "--output")
    assert option(sample, "--fine-column") == "fine_cluster_id"
    assert calls[0][1]["EMBEDDING_API_KEY"] == "test-secret"
    assert "test-secret" not in " ".join(cluster)
    first_run = Path(option(sample, "--output")).parent
    assert first_run == tmp_path / "output"
    assert pipeline.main(["--total", "1", "--fine-threshold", ""]) == 0
    assert Path(option(calls[-1][0], "--output")).parent == first_run
    assert "--fine-column" not in calls[-1][0]


def test_input_output_and_model_config_precedence(pipeline, tmp_path, monkeypatch):
    with (tmp_path / ".env").open("a") as f:
        f.write("INPUT_PATH=./example-input.jsonl\nOUTPUT_DIR=./from-file\n")
    calls = capture_commands(pipeline, monkeypatch)
    assert pipeline.main([]) == 0
    assert Path(option(calls[-1][0], "--output")).parent == tmp_path / "from-file"
    monkeypatch.setenv("OUTPUT_DIR", "./from-process")
    monkeypatch.setenv("EMBEDDING_MODEL", "process-model")
    assert pipeline.main([]) == 0
    assert option(calls[-2][0], "--model") == "process-model"
    assert Path(option(calls[-1][0], "--output")).parent == tmp_path / "from-process"
    absolute_input = tmp_path / "absolute.jsonl"
    absolute_input.write_text('{"id":"q2","text":"另一题"}\n')
    assert pipeline.main(["--input", str(absolute_input), "--output-dir", "./from-cli", "--model", "cli-model"]) == 0
    assert option(calls[-2][0], "--input") == str(absolute_input)
    assert option(calls[-2][0], "--model") == "cli-model"
    assert Path(option(calls[-1][0], "--output")).parent == tmp_path / "from-cli"


def test_clustering_failure_stops_sampling(pipeline, monkeypatch, capsys):
    calls = capture_commands(pipeline, monkeypatch, returncode=2)
    assert pipeline.main([]) == 2
    assert len(calls) == 1
    assert "最终样本" not in capsys.readouterr().out


def test_missing_input_does_not_start_subprocess(pipeline, monkeypatch):
    calls = capture_commands(pipeline, monkeypatch)
    with pytest.raises(SystemExit):
        pipeline.main(["--input", "missing.jsonl"])
    assert calls == []


def test_defaults_match_large_workflow(pipeline, tmp_path, monkeypatch):
    # 移除测试模型覆盖，验证产品默认模型；参数来自冻结的大题库运行报告。
    (tmp_path / ".env").write_text("EMBEDDING_API_KEY=test-secret\n")
    calls = capture_commands(pipeline, monkeypatch)
    assert pipeline.main([]) == 0
    cluster, sample = calls[0][0], calls[1][0]
    assert option(cluster, "--model") == "qwen3.7-text-embedding"
    assert option(cluster, "--dimension") == "1024"
    assert option(cluster, "--threshold") == "0.7"
    assert option(cluster, "--fine-threshold") == "0.85"
    assert option(cluster, "--linkage") == "complete"
    for name, value in {"total": "1087", "alpha": "0.6", "tail-bins": "1,3", "single-max-size": "20",
                        "rounding": "pps", "seed": "42", "fine-column": "fine_cluster_id"}.items():
        assert option(sample, "--" + name) == value
    assert "--cluster-cap" not in sample
    assert Path(option(sample, "--output")).suffix == ".xlsx"


def test_algorithm_env_values_and_cli_overrides(pipeline, tmp_path, monkeypatch):
    with (tmp_path / ".env").open("a") as f:
        f.write("CLUSTER_THRESHOLD=0.6\nCLUSTER_FINE_THRESHOLD=\nCLUSTER_LINKAGE=average\n"
                "EMBEDDING_DIMENSION=\nEMBEDDING_BATCH_SIZE=8\nEMBEDDING_TIMEOUT=90\n"
                'EMBEDDING_EXTRA_BODY={"instruct":"Group texts"}\n'
                "SAMPLE_TOTAL=80\nSAMPLE_ALPHA=0.5\nSAMPLE_TAIL_BINS=\nSAMPLE_SINGLE_MAX_SIZE=10\n"
                "SAMPLE_CLUSTER_CAP=3\nSAMPLE_ROUNDING=largest_remainder\nSAMPLE_SEED=7\n"
                "INPUT_ID_COLUMN=case_id\nINPUT_TEXT_COLUMN=turns\n")
    calls = capture_commands(pipeline, monkeypatch)
    monkeypatch.setenv("SAMPLE_TOTAL", "90")
    assert pipeline.main([]) == 0
    cluster, sample = calls[0][0], calls[1][0]
    assert "--dimension" not in cluster and "--fine-threshold" not in cluster
    assert "--fine-column" not in sample
    for name, value in {"threshold": "0.6", "linkage": "average", "batch-size": "8", "timeout": "90.0",
                        "id-column": "case_id", "text-column": "turns",
                        "extra-body": '{"instruct":"Group texts"}'}.items():
        assert option(cluster, "--" + name) == value
    for name, value in {"total": "90", "alpha": "0.5", "tail-bins": "", "single-max-size": "10",
                        "cluster-cap": "3", "rounding": "largest_remainder", "seed": "7"}.items():
        assert option(sample, "--" + name) == value
    assert pipeline.main(["--total", "100", "--fine-threshold", "0.9", "--cluster-cap", ""]) == 0
    assert option(calls[-1][0], "--total") == "100"
    assert option(calls[-2][0], "--fine-threshold") == "0.9"
    assert "--cluster-cap" not in calls[-1][0]


def test_invalid_numeric_env_stops_before_request(pipeline, monkeypatch):
    monkeypatch.setenv("CLUSTER_FINE_THRESHOLD", "invalid")
    calls = capture_commands(pipeline, monkeypatch)
    with pytest.raises(SystemExit):
        pipeline.main([])
    assert calls == []


def test_failure_removes_old_results_but_keeps_cache_and_other_files(pipeline, tmp_path, monkeypatch):
    out = tmp_path / "output"
    (out / ".cache").mkdir(parents=True)
    names = ("sampled.xlsx", "clustered.jsonl", "cluster-report.json", "sample-report.json")
    for name in names:
        (out / name).write_text("old result")
    (out / ".cache/embeddings.jsonl").write_text("cache")
    (out / "notes.txt").write_text("keep")
    calls = capture_commands(pipeline, monkeypatch, returncode=1)
    assert pipeline.main([]) == 1
    assert len(calls) == 1
    assert all(not (out / name).exists() for name in names)
    assert (out / ".cache/embeddings.jsonl").read_text() == "cache"
    assert (out / "notes.txt").read_text() == "keep"


def test_sampling_failure_removes_partial_final_files(pipeline, tmp_path, monkeypatch):
    def run(command, *, env, check):
        Path(option(command, "--output")).write_text("partial")
        Path(option(command, "--report")).write_text("partial")
        return SimpleNamespace(returncode=1 if Path(command[1]).name == "cluster_sample.py" else 0)

    monkeypatch.setattr(pipeline.subprocess, "run", run)
    assert pipeline.main([]) == 1
    out = tmp_path / "output"
    assert (out / "clustered.jsonl").exists()
    assert not (out / "sampled.xlsx").exists()
    assert not (out / "sample-report.json").exists()


def test_input_cannot_be_overwritten_by_outputs(pipeline, tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    source = out / "clustered.jsonl"
    source.write_text('{"id":"q1","text":"keep input"}\n')
    calls = capture_commands(pipeline, monkeypatch)
    with pytest.raises(SystemExit):
        pipeline.main(["--input", str(source)])
    assert source.read_text() == '{"id":"q1","text":"keep input"}\n'
    assert calls == []


def test_dotenv_utf8_bom_preserves_first_setting(pipeline, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("SAMPLE_TOTAL=7\nEMBEDDING_API_KEY=test-secret\n", encoding="utf-8-sig")
    calls = capture_commands(pipeline, monkeypatch)
    assert pipeline.main([]) == 0
    assert option(calls[-1][0], "--total") == "7"
