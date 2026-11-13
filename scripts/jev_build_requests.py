"""Processed JSONL + standard JEV template -> validated request files.

Text-only System One protocol: https://docs.typesafe.ai/api/system-one.
Choice/Noul/Score field types and limits checked against docs on 2026-11-11.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Content = str | dict[str, JsonValue] | list[JsonValue]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NoulCriteria(StrictModel):
    true: Content | None = None
    false: Content | None = None


class Noul(StrictModel):
    type: Literal["noul"]
    instructions: Content | None = None
    criteria: NoulCriteria | None = None


class Choice(StrictModel):
    type: Literal["choice"]
    instructions: Content | None = None
    criteria: dict[str, Content | None] = Field(min_length=1, max_length=255)


class Score(StrictModel):
    type: Literal["score"]
    instructions: Content | None = None
    criteria: list[Content] = Field(min_length=1, max_length=10)


Question = Annotated[Noul | Choice | Score, Field(discriminator="type")]


class Request(StrictModel):
    model: str = Field(min_length=1)
    state: Content
    questions: dict[str, Question] = Field(min_length=1)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 字段：{key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"不是合法 JSON 数值：{value}")


def parse_json(text: str):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)


def validate_request(body: dict) -> None:
    # Validate without reserializing the model: preserve omitted optional fields.
    Request.model_validate(body)
    json.dumps(body, allow_nan=False)


def read_records(path):
    records, seen = [], set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = parse_json(line)
            if not isinstance(record, dict):
                raise ValueError("记录必须是对象")
            identifier = record.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("id 必须是非空字符串")
            if identifier in seen:
                raise ValueError(f"重复 id：{identifier}")
        except ValueError as exc:
            raise ValueError(f"{path.name}:{line_no}: {exc}") from exc
        seen.add(identifier)
        records.append(record)
    if not records:
        raise ValueError(f"输入没有记录：{path}")
    return records


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def build(input_path: Path, template_path: Path, output_dir: Path, model: str | None = None) -> int:
    if output_dir.exists():
        raise ValueError(f"输出目录已存在，请指定新目录：{output_dir}")
    template_bytes = template_path.read_bytes()
    template = parse_json(template_bytes.decode("utf-8-sig"))
    validate_request(template)
    if model is not None:
        if not isinstance(model, str) or not model.strip() or model != model.strip():
            raise ValueError("model 必须为非空、无首尾空白的字符串")
        template = {**template, "model": model}
        validate_request(template)
    records = read_records(input_path)
    bodies = []
    for record in records:
        if "state" not in record:
            raise ValueError(f"{record['id']}: 缺少 state")
        state = record["state"]
        if state in (None, "", {}, []) or (isinstance(state, str) and not state.strip()):
            raise ValueError(f"{record['id']}: state 为空，尚未填充")
        body = {**template, "state": state}
        try:
            validate_request(body)
        except ValueError as exc:
            raise ValueError(f"{record['id']}: 请求体校验失败：{exc}") from exc
        bodies.append(body)

    # Publish only after all rows validate and all files have been written.
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".jev-build-", dir=output_dir.parent) as temp:
        stage = Path(temp) / "requests"
        stage.mkdir()
        entries = []
        for index, (record, body) in enumerate(zip(records, bodies), 1):
            name = f"{index:06d}.json"  # IDs never become filesystem paths.
            write_json(stage / name, body)
            entries.append({"id": record["id"], "request_file": name,
                            "sha256": hashlib.sha256((stage / name).read_bytes()).hexdigest()})
        write_json(stage / "template.json", template)
        write_json(stage / "manifest.json", {
            "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "template_sha256": hashlib.sha256(template_bytes).hexdigest(),
            "model": template["model"],
            "count": len(entries), "requests": entries,
        })
        stage.rename(output_dir)
    return len(entries)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="含 id、state 的 JSONL")
    parser.add_argument("--template", type=Path, required=True, help="标准 JEV 请求模板")
    parser.add_argument("--model", help="明确覆盖模板 model，并记录到请求和模板快照")
    parser.add_argument("--output-dir", type=Path, required=True, help="尚不存在的输出目录")
    args = parser.parse_args(argv)
    try:
        count = build(args.input, args.template, args.output_dir, args.model)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"错误：{exc}\n")
    print(f"已生成 {count} 个请求体：{args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
