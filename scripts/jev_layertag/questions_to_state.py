"""Select question/history via JSON Pointer; never import answers or evaluations."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from jsonpointer import JsonPointer, JsonPointerException
from openpyxl import load_workbook


def parse_json(text):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"重复 JSON 字段：{key}")
            obj[key] = value
        return obj

    def reject(value):
        raise ValueError(f"非 JSON 数值：{value}")

    return json.loads(text, object_pairs_hook=unique, parse_constant=reject)


def rows(path, sheet=None):
    suffix = path.suffix.lower()
    if sheet is not None and suffix != ".xlsx":
        raise ValueError("sheet 仅适用于 XLSX")
    if suffix == ".json":
        value = parse_json(path.read_text(encoding="utf-8-sig"))
        yield from enumerate(value if isinstance(value, list) else [value], 1)
    elif suffix == ".jsonl":
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                yield number, parse_json(line)
    elif suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            validate_headers(reader.fieldnames)
            for number, row in enumerate(reader, 2):
                if None in row or any(v is None for v in row.values()):
                    raise ValueError(f"CSV 第 {number} 行列数不匹配")
                yield number, row
    elif suffix == ".xlsx":
        book = load_workbook(path, read_only=True, data_only=False)
        try:
            if sheet is None:
                if len(book.sheetnames) != 1:
                    raise ValueError("多工作表输入必须在字段字典中指定 sheet")
                sheet = book.sheetnames[0]
            if sheet not in book.sheetnames:
                raise ValueError(f"工作表不存在：{sheet}")
            iterator = book[sheet].iter_rows()
            headers = [c.value for c in next(iterator, ())]
            validate_headers(headers)
            for number, cells in enumerate(iterator, 2):
                if all(c.value is None for c in cells):
                    continue
                if any(c.data_type in {"f", "e"} for c in cells):
                    raise ValueError(f"第 {number} 行含公式或错误单元格，请先导出为值")
                yield number, dict(zip(headers, (c.value for c in cells)))
        finally:
            book.close()
    else:
        raise ValueError("输入仅支持 JSON、JSONL、CSV、XLSX")


def validate_headers(headers):
    if (not headers or any(not isinstance(h, str) or not h.strip() for h in headers)
            or len(set(headers)) != len(headers)):
        raise ValueError("列名必须非空且不重复")


def convert(input_path: Path, mapping_path: Path, output_path: Path) -> int:
    if output_path.exists():
        raise ValueError(f"输出已存在：{output_path}")
    mapping = parse_json(mapping_path.read_text(encoding="utf-8-sig"))
    if not isinstance(mapping, dict) or set(mapping) - {"case_id_path", "fields", "sheet"}:
        raise ValueError("字段字典仅允许 case_id_path、fields、sheet")
    fields = mapping.get("fields")
    if not isinstance(fields, dict) or "user_input" not in fields or set(fields) - {"user_input", "history"}:
        raise ValueError("fields 必须有 user_input，仅可另有 history；不得注入回答或评测字段")
    if "sheet" in mapping and (not isinstance(mapping["sheet"], str) or not mapping["sheet"].strip()):
        raise ValueError("sheet 必须为非空字符串")

    def pointer(value):
        if not isinstance(value, str) or not value.startswith("/"):
            raise ValueError("字段路径必须为以 / 开头的 JSON Pointer")
        try:
            return JsonPointer(value)
        except JsonPointerException as exc:
            raise ValueError(f"无效 JSON Pointer：{value}") from exc

    id_pointer = pointer(mapping.get("case_id_path"))
    selectors = {}
    for key, field in fields.items():
        if not isinstance(field, dict) or set(field) - {"path", "description", "required"}:
            raise ValueError(f"字段定义无效：{key}")
        description, required = field.get("description"), field.get("required", True)
        if not isinstance(description, str) or not description.strip() or type(required) is not bool:
            raise ValueError(f"字段 description/required 无效：{key}")
        if key == "user_input" and not required:
            raise ValueError("user_input 必须为必需字段")
        selectors[key] = (pointer(field.get("path")), description, required)
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    missing, seen, records = object(), set(), []
    for number, row in rows(input_path, mapping.get("sheet")):
        if not isinstance(row, dict):
            raise ValueError(f"第 {number} 条输入必须为对象")
        identifier = id_pointer.resolve(row, default=missing)
        if not isinstance(identifier, str) or not identifier.strip() or identifier != identifier.strip():
            raise ValueError(f"第 {number} 条 ID 必须为非空、无首尾空白的字符串")
        if identifier in seen:
            raise ValueError(f"重复问题 ID：{identifier}")
        seen.add(identifier)
        state = {}
        for key, (selector, description, required) in selectors.items():
            value = selector.resolve(row, default=missing)
            if value is missing and required:
                raise ValueError(f"{identifier}: 缺少 {key}")
            if key == "user_input" and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{identifier}: user_input 必须为非空文本")
            if key == "history" and value is not missing and value is not None and not isinstance(value, (str, list)):
                raise ValueError(f"{identifier}: history 必须为文本、消息数组或 null")
            state[key] = {"description": description, "present": value is not missing,
                          "value": None if value is missing else value}
        records.append({"id": identifier, "state": state,
                        "source": {"file": str(input_path.resolve()), "row": number, "sha256": digest}})
    if not records:
        raise ValueError("输入没有问题")
    # Serialize the full batch before writing; malformed late records cannot publish partial data.
    try:
        text = "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records)
    except (TypeError, ValueError) as exc:
        raise ValueError("所选字段含非 JSON 数据类型，请明确转换") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        count = convert(args.input, args.mapping, args.output)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"错误：{exc}\n")
    print(f"已加工 {count} 条问题 → {args.output}")


if __name__ == "__main__":
    main()
