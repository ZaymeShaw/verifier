"""Raw materials + optional Verifier XLSX -> one {id, state, source} per case.

The workbook is read only. Evaluator opinions remain separate from observations.
The case id is the Langfuse from_trace.trace_id; no separate trace-id field.
Raw materials are selected through an explicit JSON Pointer field dictionary.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import json
from pathlib import Path

from openpyxl import load_workbook
from jsonpointer import JsonPointer, JsonPointerException

MAIN_SHEET = "用例池候选区"
AXIS_SHEET = "评测轴汇总"
REQUIRED = {"ID", "Input / Live Request"}
AXIS_REQUIRED = {"case_id", "axis_id", "展示分组", "运行状态", "轴级判定", "是否问题 tag", "轴级说明"}


def parse_json(text):
    # Input integrity belongs to this converter; no dependency on JEV assembly.
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"重复 JSON 字段：{key}")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"不是合法 JSON 数值：{value}")

    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)


def material_rows(path, sheet=None):
    suffix = path.suffix.lower()
    if sheet is not None and suffix != ".xlsx":
        raise ValueError("字段字典 sheet 仅适用于 XLSX")
    if suffix == ".json":
        data = parse_json(path.read_text(encoding="utf-8-sig"))
        records = data if isinstance(data, list) else [data]
        yield from enumerate(records, 1)
    elif suffix == ".jsonl":
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                yield number, parse_json(line)
    elif suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = csv.DictReader(stream)
            headers = rows.fieldnames
            if not headers or any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
                raise ValueError("CSV 列名必须非空且不重复")
            for number, row in enumerate(rows, 2):
                if None in row or any(v is None for v in row.values()):
                    raise ValueError(f"CSV 第 {number} 条记录列数不匹配")
                yield number, row
    elif suffix == ".xlsx":
        book = load_workbook(path, read_only=True, data_only=False)
        try:
            if sheet is None:
                if len(book.sheetnames) != 1:
                    raise ValueError("多工作表材料必须在字段字典中指定 sheet")
                sheet = book.sheetnames[0]
            if sheet not in book.sheetnames:
                raise ValueError(f"材料工作表不存在：{sheet}")
            # Reject formulas/errors instead of treating unevaluated text as evidence.
            for row in book[sheet].iter_rows():
                if any(cell.data_type in {"f", "e"} for cell in row):
                    raise ValueError("XLSX 材料含公式或错误单元格，请先导出为值")
            yield from sheet_rows(book[sheet])
        finally:
            book.close()
    else:
        raise ValueError("材料文件只支持 .json / .jsonl / .csv / .xlsx")


def read_materials(path, mapping_path):
    mapping = parse_json(mapping_path.read_text(encoding="utf-8-sig"))
    if not isinstance(mapping, dict) or set(mapping) - {"case_id_path", "fields", "sheet"}:
        raise ValueError("字段字典仅支持 case_id_path、fields、sheet")
    if "sheet" in mapping and (not isinstance(mapping["sheet"], str) or not mapping["sheet"].strip()):
        raise ValueError("sheet 必须是非空字符串")
    fields = mapping.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ValueError("字段字典 fields 必须是非空对象")

    def pointer(value):
        if not isinstance(value, str):
            raise ValueError("字段路径必须是 JSON Pointer 字符串")
        try:
            return JsonPointer(value)
        except JsonPointerException as exc:
            raise ValueError(f"无效 JSON Pointer：{value}") from exc

    id_pointer = pointer(mapping.get("case_id_path"))
    selectors = {}
    for key, field in fields.items():
        if not key.strip() or not isinstance(field, dict) or set(field) - {"path", "description", "required"}:
            raise ValueError(f"无效字段定义：{key}")
        description = field.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{key}: description 必须是非空字符串")
        required = field.get("required", True)
        if type(required) is not bool:
            raise ValueError(f"{key}: required 必须为布尔值")
        selectors[key] = (pointer(field.get("path")), description, required)
    materials = {}
    missing = object()
    for number, record in material_rows(path, mapping.get("sheet")):
        location = f"{path.name}:{number}"
        if not isinstance(record, dict):
            raise ValueError(f"{location}: 材料记录必须为对象")
        identifier = id_pointer.resolve(record, default=missing)
        if not isinstance(identifier, str) or not identifier.strip() or identifier != identifier.strip():
            raise ValueError(f"{location}: Langfuse trace ID 必须是非空、无首尾空白的字符串")
        if identifier in materials:
            raise ValueError(f"重复材料 Langfuse trace ID：{identifier}")
        selected = {}
        for key, (selector, description, required) in selectors.items():
            value = selector.resolve(record, default=missing)
            if value is missing and required:
                raise ValueError(f"{location}: 缺少必需字段 {key} ({selector.path})")
            selected[key] = {"description": description, "present": value is not missing,
                             "value": None if value is missing else value}
        try:
            json.dumps(selected, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{location}: 所选字段含非 JSON 数据类型，请在输入中明确转换") from exc
        materials[identifier] = selected
    if not materials:
        raise ValueError(f"材料文件没有记录：{path}")
    return materials


def sheet_rows(sheet, columns=None):
    rows = sheet.iter_rows(values_only=True)
    headers = next(rows, ())
    if not headers or any(not isinstance(h, str) or not h.strip() for h in headers):
        raise ValueError(f"{sheet.title}: 缺少有效列名")
    if len(set(headers)) != len(headers):
        raise ValueError(f"{sheet.title}: 列名重复")
    for number, values in enumerate(rows, 2):
        if all(v is None or v == "" for v in values):
            continue
        row = {k: v for k, v in zip(headers, values) if columns is None or k in columns}
        if any("[已因 Excel 单元格 32767 字符上限截断]" in str(v) for v in row.values()):
            raise ValueError(f"{sheet.title}!{number}: 材料已截断，请提供完整数据")
        yield number, row


def cell_json(row, column, location):
    value = row.get(column)
    if value is None or value == "":
        return None
    try:
        return parse_json(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{location} {column}: 无效 JSON") from exc


def case_id_from_request(request, location):
    from_trace = request.get("from_trace") if isinstance(request, dict) else None
    case_id = from_trace.get("trace_id") if isinstance(from_trace, dict) else None
    if not isinstance(case_id, str) or not case_id.strip() or case_id != case_id.strip():
        raise ValueError(f"{location}: 缺少明确的 Langfuse from_trace.trace_id，不能生成 case ID")
    return case_id


def write_records(output_path, records):
    text = "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        stream.write(text)
    return len(records)


def convert(input_path: Path | None, output_path: Path, materials_path: Path | None = None, mapping_path: Path | None = None, *, axes_scope="main", tags_scope="bad") -> int:
    if input_path is not None and (axes_scope not in {"main", "all"} or tags_scope not in {"bad", "all"}):
        raise ValueError("EVAL_AXES_SCOPE 只能为 main/all；EVAL_TAGS_SCOPE 只能为 bad/all")
    if output_path.exists():
        raise ValueError(f"输出文件已存在：{output_path}")
    if (materials_path is None) != (mapping_path is None):
        raise ValueError("--materials 和 --materials-map 必须一起提供")
    materials = read_materials(materials_path, mapping_path) if materials_path is not None else {}
    if input_path is None:
        if materials_path is None:
            raise ValueError("未提供评测 Excel 时，必须提供 MATERIALS_PATH 和 MATERIALS_MAP_PATH")
        records = [{"id": identifier, "state": {
            "materials": selected,
            "material_notes": ["原始输入、输出、上下文通过 materials 提供；未提供的材料不推定其内容。"],
        }, "source": {"file": str(materials_path.resolve())}}
            for identifier, selected in materials.items()]
        return write_records(output_path, records)
    workbook = load_workbook(input_path, read_only=True, data_only=False)
    try:
        if MAIN_SHEET not in workbook.sheetnames:
            raise ValueError(f"缺少工作表：{MAIN_SHEET}")
        sheet = workbook[MAIN_SHEET]
        headers = next(sheet.iter_rows(values_only=True), ())
        if not REQUIRED.issubset(headers):
            raise ValueError(f"缺少列：{sorted(REQUIRED - set(headers))}")
        main_rows = list(sheet_rows(sheet, REQUIRED))
        ids = [row["ID"] for _, row in main_rows]
        if any(not isinstance(i, str) or not i.strip() for i in ids) or len(ids) != len(set(ids)):
            raise ValueError("主表 ID 必须为非空且不重复的字符串")
        # Excel row keys only join its sheets. External material joins and output
        # IDs use Langfuse's trace ID, never the evaluator's internal trace_id.
        inputs = {row["ID"]: cell_json(row, "Input / Live Request", f"{MAIN_SHEET}!{number}")
                  for number, row in main_rows}
        case_ids = {row["ID"]: case_id_from_request(inputs[row["ID"]], f"{MAIN_SHEET}!{number}")
                    for number, row in main_rows}
        if len(set(case_ids.values())) != len(case_ids):
            raise ValueError("Langfuse trace ID 重复：每批只能有一条对应的 case")
        if materials_path is not None and set(materials) != set(case_ids.values()):
            raise ValueError("材料 Langfuse trace ID 必须与本次 Excel 完全一致，不能缺少或多出 case")
        if AXIS_SHEET not in workbook.sheetnames:
            raise ValueError(f"缺少工作表：{AXIS_SHEET}")
        axes_sheet = workbook[AXIS_SHEET]
        axes_headers = next(axes_sheet.iter_rows(values_only=True), ())
        if not AXIS_REQUIRED.issubset(axes_headers):
            raise ValueError(f"{AXIS_SHEET} 缺少列：{sorted(AXIS_REQUIRED - set(axes_headers))}")
        axis_results = defaultdict(list)
        for number, row in sheet_rows(axes_sheet, AXIS_REQUIRED):
            identifier = row["case_id"]
            location = f"{AXIS_SHEET}!{number}"
            if identifier not in case_ids:
                raise ValueError(f"{location}: case_id 无法关联主表")
            if row["展示分组"] not in {"主要展示", "其余分析"}:
                raise ValueError(f"{location}: 未知展示分组")
            if row["是否问题 tag"] not in {"是", "否"}:
                raise ValueError(f"{location}: 是否问题 tag 必须为 是/否")
            if axes_scope == "main" and row["展示分组"] != "主要展示":
                continue
            if tags_scope == "bad" and row["是否问题 tag"] != "是":
                continue
            if row["运行状态"] != "succeeded":
                continue
            axis_id, verdict = row["axis_id"], row["轴级判定"]
            if not isinstance(axis_id, str) or not axis_id.strip() or not isinstance(verdict, str) or not verdict.strip():
                raise ValueError(f"{location}: 成功评测轴缺少 axis_id 或轴级判定")
            tag = f"[{axis_id}:{verdict}]"
            reason = row["轴级说明"]
            if reason is not None and not isinstance(reason, str):
                raise ValueError(f"{location}: 轴级说明必须为文本或空值")
            axis_results[identifier].append({
                "axis_id": axis_id, "tag": tag, "verdict": verdict, "reason": reason,
            })
        records = []
        for number, row in main_rows:
            identifier = row["ID"]
            state = {
                "materials": materials.get(case_ids[identifier]),
                "evaluations": {
                    "description": "已有评测轴结论及理由，供参考，不作为原始事实或最终分类",
                    "filters": {"axes_scope": axes_scope, "tags_scope": tags_scope,
                                "run_status": "succeeded"},
                    "value": axis_results[identifier],
                },
                "material_notes": [
                    "空评测数组只表示当前筛选下没有结论，不代表回答正确或没有问题。",
                    "原始输入、输出、上下文通过 materials 提供；未提供的材料不推定其内容。",
                ],
            }
            records.append({"id": case_ids[identifier], "state": state,
                            "source": {"file": str(input_path.resolve()), "sheet": MAIN_SHEET,
                                       "row": number}})
        if not records:
            raise ValueError("Excel 没有 case")
    finally:
        workbook.close()
    return write_records(output_path, records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="可选评测 Excel；省略时仅使用原始材料")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--materials", type=Path, help="原始材料 JSON / JSONL / CSV / XLSX")
    parser.add_argument("--materials-map", type=Path, help="字段字典 JSON")
    parser.add_argument("--axes-scope", choices=["main", "all"], default="main")
    parser.add_argument("--tags-scope", choices=["bad", "all"], default="bad")
    args = parser.parse_args(argv)
    try:
        count = convert(args.input, args.output, args.materials, args.materials_map,
                        axes_scope=args.axes_scope, tags_scope=args.tags_scope)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"错误：{exc}\n")
    print(f"已加工 {count} 条：{args.output.resolve()}")


if __name__ == "__main__":
    main()
