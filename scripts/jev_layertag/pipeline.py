"""Question files -> state -> standard JEV requests -> business label results."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from dotenv import dotenv_values

from questions_to_state import convert, parse_json
from taxonomy_to_template import SPECIAL, catalog_from_template

HERE = Path(__file__).resolve().parent
BUILDER = HERE.parent / "jev_build_requests.py"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def connection_config(config):
    values = {}
    for key in ("JEV_API_URL", "JEV_API_KEY", "JEV_TIMEOUT_SECONDS"):
        value = config.get(key)
        if not value or value != value.strip() or any(c in value for c in "\r\n"):
            raise ValueError(f"请在 .env 中设置有效的 {key}")
        values[key] = value
    url = urlsplit(values["JEV_API_URL"])
    if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password or url.fragment:
        raise ValueError("JEV_API_URL 必须为完整 HTTP(S) 地址，不含账号或 fragment")
    try:
        timeout = float(values["JEV_TIMEOUT_SECONDS"])
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        raise ValueError("JEV_TIMEOUT_SECONDS 必须为有限正数") from None
    curl = shutil.which("curl")
    if curl is None:
        raise ValueError("未找到 curl")
    return values["JEV_API_URL"], values["JEV_API_KEY"], timeout, curl


def prepare(input_path, mapping_path, template_path, output_dir, *, model):
    if not isinstance(model, str) or not model.strip() or model != model.strip():
        raise ValueError("JEV_MODEL 必须为非空、无首尾空白的字符串")
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise ValueError("输出路径必须为普通目录")
    output_dir = output_dir.resolve()
    for source in (input_path, mapping_path, template_path, HERE, BUILDER):
        if source.resolve() == output_dir or output_dir in source.resolve().parents:
            raise ValueError("输出目录不能包含输入、模板、字典或工作流代码")
    template = parse_json(template_path.read_text(encoding="utf-8-sig"))
    if not isinstance(template, dict):
        raise ValueError("模板必须为对象")
    catalog_from_template(template)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".jev-layertag-", dir=output_dir.parent) as temp:
        stage = Path(temp) / "output"
        stage.mkdir()
        count = convert(input_path, mapping_path, stage / "processed.jsonl")
        shutil.copyfile(mapping_path, stage / "input-mapping.json")
        built = subprocess.run([
            sys.executable, str(BUILDER), "--input", str(stage / "processed.jsonl"),
            "--template", str(template_path), "--output-dir", str(stage / "requests"), "--model", model,
        ], capture_output=True, text=True, encoding="utf-8", check=False)
        if built.returncode:
            raise ValueError(f"JEV 请求组装失败：{built.stderr.strip() or built.stdout.strip()}")
        effective = parse_json((stage / "requests/template.json").read_text(encoding="utf-8"))
        catalog = catalog_from_template(effective)
        write_json(stage / "label-catalog.json", catalog)
        write_json(stage / "run.json", {
            "input_file": str(input_path.resolve()), "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "mapping_sha256": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
            "template_sha256": hashlib.sha256(template_path.read_bytes()).hexdigest(),
            "model": model, "question_count": count, "label_count": len(catalog),
        })
        previous = Path(temp) / "previous"
        if output_dir.exists():
            output_dir.rename(previous)
        try:
            stage.rename(output_dir)
        except OSError:
            if previous.exists():
                previous.rename(output_dir)
            raise
    return count


def classification_result(data, request):
    catalog = catalog_from_template(request)
    if not isinstance(data, dict) or not isinstance(data.get("model"), str) or not data["model"].strip():
        raise ValueError("JEV 响应缺少有效 model")
    answers = data.get("answers")
    answer = answers.get("classification") if isinstance(answers, dict) else None
    criteria = request["questions"]["classification"]["criteria"]
    if (not isinstance(answer, dict) or answer.get("type") != "choice"
            or not isinstance(answer.get("choice"), str) or answer["choice"] not in criteria):
        raise ValueError("JEV 响应缺少有效 classification Choice")

    def probability(value):
        return type(value) in {float, int} and math.isfinite(value) and 0 <= value <= 1

    probabilities = answer.get("probabilities")
    if (not probability(answer.get("confidence")) or not isinstance(probabilities, dict)
            or set(probabilities) != set(criteria) or not all(probability(v) for v in probabilities.values())
            or not math.isclose(sum(probabilities.values()), 1, abs_tol=0.02)):
        raise ValueError("JEV 响应的 confidence/probabilities 不完整或无效")
    usage = data.get("usage")
    if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0 for k in ("input_tokens", "output_tokens")):
        raise ValueError("JEV 响应缺少有效 usage")
    choice = answer["choice"]
    label = catalog.get(choice)
    if choice in SPECIAL:
        status = choice.strip("_")
        reason = choice.strip("_")
    elif label["review_required"]:
        status, reason = "review", "taxonomy_definition_unverified"
    else:
        status, reason = "ready", None
    return {
        "classification": choice, "classification_status": status, "review_reason": reason,
        "candidate_label_id": choice if label else None, "candidate_path": label["path"] if label else None,
        "label_id": choice if status == "ready" else None,
        "path": label["path"] if status == "ready" else None,
        "model": data["model"], "answers": answers, "usage": usage,
    }


def send_requests(output_dir, api_url, api_key, timeout, curl):
    manifest = parse_json((output_dir / "requests/manifest.json").read_text(encoding="utf-8"))
    prepared = []
    for entry in manifest["requests"]:
        name = entry["request_file"]
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("manifest 请求文件必须为本目录文件名")
        path = output_dir / "requests" / name
        if path.is_symlink():
            raise ValueError("请求文件不能为符号链接")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"请求文件哈希不匹配：{name}")
        request = parse_json(raw.decode("utf-8"))
        catalog_from_template(request)
        prepared.append((entry, path, request))
    responses = output_dir / "responses"
    responses.mkdir()
    results = []
    write_json(output_dir / "classification-results.json", results)
    # Keep authorization out of argv, persisted requests and diagnostic output.
    curl_config = "\n".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in [
        ("url", api_url), ("header", f"Authorization: Bearer {api_key}"),
        ("header", "Content-Type: application/json"), ("header", "Accept: application/json"),
        ("max-time", str(timeout)),
    ])
    for index, (entry, path, request) in enumerate(prepared, 1):
        response_path = responses / path.name
        record = {"id": entry["id"], "requested_model": request["model"], "success": False,
                  "request_sha256": entry["sha256"], "response_file": f"responses/{path.name}", "http_status": None}
        print(f"JEV [{index}/{len(prepared)}] {entry['id']}：发送中", flush=True)
        started = time.monotonic()
        try:
            response = subprocess.run([
                curl, "--disable", "--config", "-", "--silent", "--show-error", "--request", "POST",
                "--data-binary", f"@{path.resolve()}", "--output", str(response_path.resolve()), "--write-out", "%{http_code}",
            ], input=curl_config, capture_output=True, text=True, encoding="utf-8", timeout=timeout + 5)
            status = response.stdout.strip()
            record["http_status"] = int(status) if status.isdigit() and status != "000" else None
            if response.returncode:
                raise ValueError(f"curl 退出码 {response.returncode}：{response.stderr.strip()}")
            if record["http_status"] != 200:
                raise ValueError(f"JEV HTTP {record['http_status']}，详见原始响应")
            record.update(classification_result(parse_json(response_path.read_text(encoding="utf-8")), request))
            record["success"] = True
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            record["error"] = str(exc).replace(api_key, "[REDACTED]")
        record["elapsed_seconds"] = round(time.monotonic() - started, 2)
        results.append(record)
        write_json(output_dir / "classification-results.json", results)
        if not record["success"]:
            raise ValueError(f"{entry['id']} 调用失败：{record['error']}；已保存结果，后续未发送")
        print(f"  {record['classification']} / {record['classification_status']}", flush=True)
    return len(results)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="只校验输入并生成请求，不发送")
    args = parser.parse_args(argv)
    try:
        config = dotenv_values(HERE / ".env", encoding="utf-8-sig", interpolate=False)

        def configured_path(key, *, input_file=True):
            value = config.get(key)
            if not value or not value.strip():
                raise ValueError(f"请在 {HERE / '.env'} 中设置 {key}")
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = HERE / path
            if input_file and not path.is_file():
                raise ValueError(f"{key} 文件不存在：{path}")
            return path

        input_path = configured_path("INPUT_PATH")
        mapping = configured_path("INPUT_MAP_PATH")
        template = configured_path("JEV_TEMPLATE_PATH")
        output_dir = configured_path("OUTPUT_DIR", input_file=False)
        connection = None if args.prepare_only else connection_config(config)
        count = prepare(input_path, mapping, template, output_dir, model=config.get("JEV_MODEL"))
        print(f"已生成 {count} 个请求体 → {output_dir.resolve()}", flush=True)
        if connection is not None:
            send_requests(output_dir, *connection)
            print(f"完成：{count} 条分类结果 → {(output_dir / 'classification-results.json').resolve()}")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"错误：{exc}\n")


if __name__ == "__main__":
    main()
