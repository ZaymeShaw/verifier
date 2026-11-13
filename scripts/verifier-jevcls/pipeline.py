"""Verifier XLSX -> processed JSONL -> JEV requests -> classification results."""
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
from openpyxl import Workbook
from openpyxl.styles import Font

from verifier_excel_to_jev_state import convert

HERE = Path(__file__).resolve().parent
BUILDER = HERE.parent / "jev_build_requests.py"


def connection_config(config):
    values = {}
    for key in ("JEV_API_URL", "JEV_API_KEY", "JEV_TIMEOUT_SECONDS"):
        value = config.get(key)
        if not value or value != value.strip() or any(c in value for c in "\r\n"):
            raise ValueError(f"请在 .env 中设置有效的 {key}")
        values[key] = value
    url = urlsplit(values["JEV_API_URL"])
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.fragment:
        raise ValueError("JEV_API_URL 必须是完整 HTTP(S) 地址，不含账号或 fragment")
    try:
        timeout = float(values["JEV_TIMEOUT_SECONDS"])
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        raise ValueError("JEV_TIMEOUT_SECONDS 必须是有限正数") from None
    curl = shutil.which("curl")
    if curl is None:
        raise ValueError("未找到 curl，请安装后再运行")
    return values["JEV_API_URL"], values["JEV_API_KEY"], timeout, curl


def classification_result(data, request):
    if not isinstance(data, dict) or not isinstance(data.get("model"), str) or not data["model"].strip():
        raise ValueError("JEV 响应缺少有效 model")
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("JEV 响应缺少 answers")
    answer = answers.get("classification")
    if (not isinstance(answer, dict) or answer.get("type") != "choice"
            or not isinstance(answer.get("choice"), str)
            or answer["choice"] not in request["questions"]["classification"]["criteria"]):
        raise ValueError("JEV 响应中的 classification 缺失或不符合模板选项")
    review = answers.get("needs_review")
    if not isinstance(review, dict) or review.get("type") != "noul":
        raise ValueError("JEV 响应缺少 Noul 判断 needs_review")
    score = review.get("noul")
    if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("needs_review.noul 必须是 0 到 1 的有限数值")
    usage = data.get("usage")
    if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0
                                         for k in ("input_tokens", "output_tokens")):
        raise ValueError("JEV 响应缺少有效 usage")
    return {"model": data["model"], "answers": answers, "usage": usage,
            "classification": answers["classification"]["choice"],
            "needs_review_score": score}


def write_classification_table(output_dir, results):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "分类结果"
    sheet.append(["traceid", "标签", "待复核分数"])
    for record in results:
        sheet.append([record["id"], record["classification"], record["needs_review_score"]])
        for cell in sheet[sheet.max_row][:2]:
            cell.data_type = "s"
            cell.number_format = "@"
        sheet.cell(sheet.max_row, 3).number_format = "0.00"
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.column_dimensions["A"].width = 44
    sheet.column_dimensions["B"].width = 32
    sheet.column_dimensions["C"].width = 20
    sheet.freeze_panes = "A2"
    workbook.save(output_dir / "classification-results.xlsx")
    workbook.close()


def send_requests(output_dir, api_url, api_key, timeout, curl):
    manifest = json.loads((output_dir / "requests/manifest.json").read_text(encoding="utf-8"))
    prepared = []
    for entry in manifest["requests"]:
        path = output_dir / "requests" / entry["request_file"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"请求文件哈希不匹配：{path.name}")
        request = json.loads(raw)
        prepared.append((entry, path, request))
    responses = output_dir / "responses"
    responses.mkdir()
    results = []
    # Secrets go through stdin, never shell text, process arguments or a config file.
    curl_config = "\n".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in [
        ("url", api_url), ("header", f"Authorization: Bearer {api_key}"),
        ("header", "Content-Type: application/json"), ("header", "Accept: application/json"),
        ("max-time", str(timeout)),
    ])
    for index, (entry, path, request) in enumerate(prepared, 1):
        response_path = responses / path.name
        record = {"id": entry["id"], "requested_model": request["model"],
                  "request_sha256": entry["sha256"], "success": False,
                  "http_status": None, "response_file": f"responses/{path.name}"}
        print(f"JEV [{index}/{len(prepared)}] {entry['id']}：发送中", flush=True)
        started = time.monotonic()
        try:
            response = subprocess.run(
                [curl, "--disable", "--config", "-", "--silent", "--show-error",
                 "--request", "POST", "--data-binary", f"@{path.resolve()}",
                 "--output", str(response_path.resolve()), "--write-out", "%{http_code}"],
                input=curl_config, capture_output=True, text=True, encoding="utf-8", timeout=timeout + 5,
            )
            status = response.stdout.strip()
            record["http_status"] = int(status) if status.isdigit() and status != "000" else None
            if response.returncode:
                raise ValueError(f"curl 退出码 {response.returncode}：{response.stderr.strip()}")
            if record["http_status"] != 200:
                raise ValueError(f"JEV HTTP {record['http_status']}，详见原始响应")
            data = json.loads(response_path.read_text(encoding="utf-8"))
            json.dumps(data, allow_nan=False)
            record.update(classification_result(data, request))
            record["success"] = True
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            record["error"] = str(exc).replace(api_key, "[REDACTED]")
        record["elapsed_seconds"] = round(time.monotonic() - started, 2)
        results.append(record)
        (output_dir / "classification-results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        if not record["success"]:
            raise ValueError(f"{entry['id']} 调用失败：{record['error']}；已保存结果，后续请求未发送")
        print(f"  {record['classification']} / 待复核分数：{record['needs_review_score']:.2f} ({record['elapsed_seconds']}s)", flush=True)
    write_classification_table(output_dir, results)
    return len(results)


def run(input_path, output_dir, template, materials=None, mapping=None, *, model=None, axes_scope="main", tags_scope="bad"):
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise ValueError(f"输出路径必须是普通目录：{output_dir}")
    output_dir = output_dir.resolve()
    # Replacing the output must never remove its own inputs or workflow files.
    for source in [input_path, template, materials, mapping, HERE, BUILDER]:
        if source is not None and (source.resolve() == output_dir or output_dir in source.resolve().parents):
            raise ValueError(f"输出目录不能包含输入文件或工作流：{source}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".jev-pipeline-", dir=output_dir.parent) as temp:
        stage = Path(temp) / "output"
        stage.mkdir()
        processed = stage / "processed.jsonl"
        count = convert(input_path, processed, materials, mapping, axes_scope=axes_scope, tags_scope=tags_scope)
        if mapping is not None:
            (stage / "materials-mapping.json").write_text(mapping.read_text(encoding="utf-8-sig"), encoding="utf-8")
        command = [sys.executable, str(BUILDER), "--input", str(processed),
                   "--template", str(template), "--output-dir", str(stage / "requests")]
        if model is not None:
            command += ["--model", model]
        result = subprocess.run(
            command,
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        if result.returncode:
            raise ValueError(f"JEV 请求组装失败：{result.stderr.strip() or result.stdout.strip()}")
        effective_template = json.loads((stage / "requests/template.json").read_text(encoding="utf-8"))
        for name, kind in {"classification": "choice", "needs_review": "noul"}.items():
            if effective_template["questions"].get(name, {}).get("type") != kind:
                raise ValueError(f"分类模板必须包含 {kind} 问题 {name}")
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        config = dotenv_values(HERE / ".env", encoding="utf-8-sig", interpolate=False)

        def configured_path(key, *, required=True, input_file=True):
            value = config.get(key)
            if not value or not value.strip():
                if required:
                    raise ValueError(f"请在 {HERE / '.env'} 中设置 {key}")
                return None
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = HERE / path
            if input_file and not path.is_file():
                raise ValueError(f"{key} 文件不存在：{path}")
            return path

        input_path = configured_path("INPUT_PATH", required=False)
        output_dir = configured_path("OUTPUT_DIR", input_file=False)
        template = configured_path("JEV_TEMPLATE_PATH")
        materials = configured_path("MATERIALS_PATH", required=False)
        mapping = configured_path("MATERIALS_MAP_PATH", required=False)
        if (materials is None) != (mapping is None):
            raise ValueError("MATERIALS_PATH 和 MATERIALS_MAP_PATH 必须同时配置或同时留空")
        if input_path is None and materials is None:
            raise ValueError("INPUT_PATH 留空时必须配置 MATERIALS_PATH 和 MATERIALS_MAP_PATH")
        model = config.get("JEV_MODEL")
        if not model or not model.strip() or model != model.strip():
            raise ValueError("请在 .env 中设置非空、无首尾空白的 JEV_MODEL")
        connection = connection_config(config)
        count = run(input_path, output_dir, template, materials, mapping,
                    model=model,
                    axes_scope=config.get("EVAL_AXES_SCOPE", "main"),
                    tags_scope=config.get("EVAL_TAGS_SCOPE", "bad"))
        print(f"已生成 {count} 个请求体 → {output_dir.resolve()}", flush=True)
        send_requests(output_dir, *connection)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"错误：{exc}\n")
    print(f"完成：{count} 条 JEV 分类结果 → {(output_dir / 'classification-results.xlsx').resolve()}")


if __name__ == "__main__":
    main()
