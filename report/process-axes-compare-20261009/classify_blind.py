"""按 triage_rules.md 对盲测问题做一次独立模型归类（同模型：primary/gemini-3.8-flash-medium）。

- 输入：`blind_problems.jsonl`（无臂标签）、`triage_rules.md`（冻结）、`gold.json`（冻结）。
- 每批 8 条一次调用；输出 [{"id","verdict","code","gold_id","note"}]。
- 归类结果写 `classification.json`（id → {verdict, code, kind, gold_id, note, model}），
  逐条 kind 由 score.py 统一折算（真问题命中清单 / 清单外真问题 / 重复计数 / 判据主观 / 与案卷冲突 / 其他误报 / 无法判断）。
- 只有 transport 判定成功的批次才写入；失败的批次保留原始应答，重跑时用同一脚本再调（已归类的 id 跳过）。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

from llm_transport import Transport  # noqa: E402

MODEL = "gemini-3.8-flash-medium"
PROVIDER = "primary"
BATCH_SIZE = 8
RUN = "classify"  # 原始应答目录 runs/<RUN>/raw；第二遍用 classify_r2，避免覆盖第一遍
VERDICTS = ("真问题", "误报", "无法判断")
CODES = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "F1", "F2", "F3", "F4", "F5", "")


@dataclasses.dataclass
class Judgement:
    id: str
    verdict: str          # 真问题 / 误报 / 无法判断
    code: str             # T1..T7 / F1..F5 / 空
    gold_id: str          # 命中 known_issues 的条目 id；清单外真问题写 none
    note: str             # 一句话理由，指明冲突对象


@dataclasses.dataclass
class Judgements:
    items: list[Judgement]


def kind_of(judgement: dict) -> str:
    """按 triage_rules.md 折算成评分用的粗类。"""
    verdict, code, gold_id = judgement["verdict"], (judgement["code"] or ""), (judgement["gold_id"] or "")
    if verdict == "真问题":
        return "hit" if gold_id and gold_id != "none" else "out_of_list_real"
    if verdict == "无法判断":
        return "unclear"
    return {"F2": "overclaim", "F4": "contradicted", "F5": "split"}.get(code, "other_false_positive")


def build_system() -> str:
    rules = (io.HERE / "triage_rules.md").read_text(encoding="utf-8")
    gold = io.load_json(io.HERE / "gold.json")["items"]
    gold_lines = [f"- {item['id']}（{item['case']}，{item['grade']}）：{item['statement']}"
                  f"｜证据参考：{'、'.join(item['refs'][:3])}" for item in gold]
    return (
        "你是独立复核员，只做归类，不改写问题。按下面的冻结规则和已知问题清单，逐条判断候选问题。\n\n"
        "# 判定规则（冻结）\n" + rules + "\n\n"
        "# 已知问题清单（gold，冻结）\n" + "\n".join(gold_lines) + "\n\n"
        "# 你的任务\n"
        "对每条候选问题输出一条判定：\n"
        "- verdict：`真问题`（命中 T1–T7 任一）、`误报`（命中 F1–F5 任一）、`无法判断`（证据不足以判两者之一）。\n"
        "- code：真问题填命中的 T 码，误报填命中的 F 码，无法判断填空字符串。\n"
        "- gold_id：若这条候选问题就是在报 gold 清单里某一条缺陷，填该条 id（如 `REN-1`）；"
        "是清单外的真问题或误报，填 `none`。一条候选最多匹配一个 gold 条目。\n"
        "- note：一句话说明你依据的记录级冲突（或判误报的理由），不超过 60 字。\n"
        "只输出 JSON，不要解释过程。"
    )


def build_user(batch) -> str:
    lines = [f"逐条判定下面这 {len(batch)} 条候选问题（refs 是该问题给出的证据 id）。",
             f"本批必须返回 {len(batch)} 个元素：`{{\"items\": [ ... ]}}`，items 是数组，每条一个对象。"]
    for row in batch:
        lines.append(json.dumps({"id": row["id"], "case": row["case"], "claim": row["claim"],
                                 "observed": (row["observed"] or "")[:400], "refs": row["refs"][:8],
                                 "attribution": row["attribution"]}, ensure_ascii=False))
    return "\n".join(lines)


def normalize(payload):
    """宽容解析：模型偶尔把 items 写成单对象（契约层会拦），这里只用于记录归类结果。"""
    from impl.core.llm_client import extract_json

    if isinstance(payload, str):
        payload = extract_json(payload)
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = [rows]
    return [row for row in (rows or []) if isinstance(row, dict)]


def out_spec():
    from impl.core.structured_output import StructuredOutputSpec

    return StructuredOutputSpec.from_dataclass(Judgements, required_nonempty=["items"], description="盲测问题归类")


def run_batch(index: int, batch, existing: dict):
    transport = Transport(PROVIDER, MODEL, arm=RUN, tag=f"batch{index:03d}")
    lenient = False
    try:
        result = transport.complete_json(build_system(), build_user(batch), reasoning_effort="high",
                                         output_spec=out_spec(), stage=f"classify_batch{index:03d}")
        rows_raw = result.get("items") if "error" not in result else None
    except ValueError as exc:  # 结构化契约拦下（常见：items 写成单对象）→ 用最后一次原始应答宽容解析
        lenient = True
        raws = sorted((io.HERE / "runs" / RUN / "raw").glob(f"batch{index:03d}__classify_batch{index:03d}__attempt*__*.txt"),
                      key=lambda path: path.stat().st_mtime)
        if not raws:
            return index, {}, f"lenient 失败：{exc}"
        text = raws[-1].read_text(encoding="utf-8").split("<<<REASONING>>>")[0]
        rows_raw = normalize(text)
    if rows_raw is None:
        return index, {}, (result.get("raw_text") or "error")[:200]
    rows = {}
    for item in normalize(rows_raw):
        if item.get("verdict") not in VERDICTS or (item.get("code") or "") not in CODES or not item.get("id"):
            continue
        rows[item["id"]] = {**item, "kind": kind_of(item), "model": MODEL, "batch": index, "lenient": lenient}
    passed = sum(1 for row in batch if row["id"] in rows)
    return index, rows, f"{'lenient ' if lenient else 'ok '}{passed}/{len(batch)}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=0, help="只跑前 N 批（调试用）")
    parser.add_argument("--workers", type=int, default=2, help="并发批次数；中转并发上限 3 且与臂运行共享，臂在跑时降到 1")
    parser.add_argument("--only", default="", help="只跑这些 id（逗号分隔）")
    parser.add_argument("--out", default="classification.json",
                        help="归类结果文件；第二遍独立归类写 classification_r2.json")
    args = parser.parse_args()
    global RUN
    RUN = "classify" if args.out == "classification.json" else "classify_" + args.out.removeprefix("classification_").removesuffix(".json")
    io.init_secret_guard()
    import llm_transport
    llm_transport.MAX_ATTEMPTS = 2  # 归类调用：契约层偶尔把 items 写成单对象，少重试、走宽容解析
    rows = [json.loads(line) for line in (io.HERE / "blind_problems.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    path = io.HERE / args.out
    done = io.load_json(path) if path.exists() else {}
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        rows = [row for row in rows if row["id"] in wanted]
    rows = [row for row in rows if row["id"] not in done]  # 只发未归类的，已归类的标签不会被覆盖
    if args.batches:
        rows = rows[: args.batches * BATCH_SIZE]
    batches = [(index, rows[start:start + BATCH_SIZE]) for index, start in
               enumerate(range(0, len(rows), BATCH_SIZE), 1)]
    print(f"待归类 {len(rows)} 条 / {len(batches)} 批", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, got, note in pool.map(lambda pair: run_batch(pair[0], pair[1], done), batches):
            print(f"batch{index:03d}: {note}", flush=True)
            if got:
                done.update(got)
                io.save_json(path, done, exclusive=False)
    io.save_json(path, done, exclusive=False)
    counts = {}
    for row in done.values():
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    print(json.dumps({"classified": len(done), "kinds": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
