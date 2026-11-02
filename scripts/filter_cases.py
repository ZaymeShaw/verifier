"""用 LLM 找出对评测没有价值的题，追加 filter_verdict、filter_reason、filter_note 三列，不删行。

判断标准：只看这段对话本身，能不能确定助手该怎么答。
每次把一批题（默认 40 条，带编号）发给模型，模型只列出它认为没价值的编号、原因类别和一句话理由；
没被列出的算有效。结论由 REASONS 映射决定（保留 / 过滤 / 存疑），不让模型直接定去留：
- 有效：保留
- 单轮缺上文、测试或乱码、占位符未替换：过滤
- 意图不明：存疑，留给人看
多轮里后面的追问有前文可依，不算缺上文；客户/保单搜索的条件短语、人名、号码是正常查询，算有效。

判断结果按「模型 + 提示词版本 + 批大小 + 题目文本」逐条缓存在 JSONL，按批断点续跑；改了提示词要改 PROMPT_VERSION。

用法：
    KIMI_API_KEY=... python scripts/filter_cases.py --input typed.xlsx --output filtered.xlsx \
        --cache filter-cache.jsonl [--model kimi-for-coding] [--batch-size 40] [--limit 200] [--workers 4]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cluster_sample import read_records, write_records  # noqa: E402

KEEP, DROP, UNSURE = "保留", "过滤", "存疑"
VALID = "有效"
REASONS = {
    VALID: KEEP,
    "单轮缺上文": DROP,
    "测试或乱码": DROP,
    "占位符未替换": DROP,
    "意图不明": UNSURE,
}
OUTPUT_COLUMNS = ("filter_verdict", "filter_reason", "filter_note")
PROMPT_VERSION = "batch-v4"
SYSTEM_PROMPT = """你在为一个保险代理人 AI 助手（AskBob）筛选评测题。助手面向平安寿险代理人，覆盖：查客户、查保单、\
产品条款、权益服务、业务办理 FAQ、营销内容生成、营销规划、计划追踪、智能问数（机构/团队经营指标如 NBEV、增员率）。
用户会发来一批题，每题一行，格式为「[编号] 题目」，题目是代理人发给助手的原始问句；多轮时用「第N轮：」分隔，是同一段对话。

判断标准：只看这段对话本身，能不能确定助手该怎么答。给答案、追问缺的参数、说明做不到，都算"能确定"。
大多数题都有效，逐条看，只列出确实属于下面几类的。

列出的类别（reason 用引号里的类别名）：
1. "单轮缺上文"：只有一轮，而且这句话是在接一段看不到的对话，离开前文就不知道在问什么：
   - 指代词指回前文、句中没有对象："它的等待期呢""那第二个呢""这个要怎么弄"；
   - 省略成半句的追问："换成五年交的""那女的呢""还能加吗"；
   - 纠正或回应前文："我问的不是这个""对，就是刚才那款"。
2. "测试或乱码"：随手敲的字符、单个字母、一串无关的数字、语音转写错乱到完全读不懂。
   例："asdfg""嗯嗯嗯""第1轮：12 第2轮：345"。
3. "占位符未替换"：含花括号模板变量，如 {客户姓名}、{保单号}。
4. "意图不明"：连指的是哪个业务对象都看不出——残缺的产品名或版本号（"某某版""2号款"）、\
   与保险业务无关联的泛词。

以下都有效，不要列出：
- 一句话本身是完整请求、只是缺一个参数："查一下客户名下的保单"（没说哪个客户）、"帮我做个计划书"——期望是追问；
- 陈述句形式的确认问题："这个权益是终身的""摔骨折不算重疾"——期望是确认或纠正；
- 关键词或短语，只要说出了业务对象：产品名、权益名、疾病名、险种类别、业务术语、流程名\
  （"护理金给付""糖尿病核保""续收件""长护险""年金转换"）——期望是介绍或问清要了解哪方面；
- 名称里带数字或字母的业务术语（"1+N 组合""V2 会员""款式代号 Z9"），不是占位符；
- 客户/保单搜索的条件短语、人名、地名、公司名、客户号、保单号、手机号——这是搜索框的正常输入；
- 多轮对话：后面的追问有前文可依，哪怕是同一问题换说法重问、或中途换话题；
- 错别字、口语、语音转写痕迹但能看懂的；超出能力或与保险无关但意思清楚的；带 <userContext> 的；带攻击或诱导意图的。

只输出 JSON：{"items": [{"id": <编号>, "reason": "<类别名>", "note": "<一句话理由，不超过40字>"}]}。\
全部有效时输出 {"items": []}。"""

Judge = Callable[[list[str]], dict[int, dict[str, str]]]


def case_text(turns: Any) -> str:
    if isinstance(turns, str) and turns.startswith("["):
        turns = json.loads(turns)
    if isinstance(turns, list):
        return turns[0] if len(turns) == 1 else "\n".join(f"第{i}轮：{t}" for i, t in enumerate(turns, 1))
    return str(turns)


def batch_prompt(texts: list[str]) -> str:
    return "\n".join(f"[{i}] " + t.replace("\n", " / ") for i, t in enumerate(texts, 1))


def parse_answer(content: str, size: int) -> dict[int, dict[str, str]]:
    """模型输出 → {批内序号(0 起): {reason, note}}，只含被列出的题。编号越界或原因未知时报错，整批重判。"""
    start, end = content.find("{"), content.rfind("}")
    flagged = {}
    for item in json.loads(content[start:end + 1])["items"]:
        idx, reason = int(item["id"]), str(item.get("reason", "")).strip()
        if not 1 <= idx <= size:
            raise ValueError(f"编号越界：{idx}（本批 {size} 条）")
        if reason not in REASONS or reason == VALID:
            raise ValueError(f"未知原因类别：{reason!r}")
        flagged[idx - 1] = {"reason": reason, "note": str(item.get("note", "")).strip()}
    return flagged


class Cache:
    def __init__(self, path: Path | None, model: str, batch_size: int) -> None:
        self.path, self.salt, self.items = path, f"{model}\0{PROMPT_VERSION}\0{batch_size}", {}
        if path and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.items[row["key"]] = row["answer"]

    def key(self, text: str) -> str:
        return hashlib.sha256(f"{self.salt}\0{text}".encode()).hexdigest()

    def get(self, text: str) -> dict[str, str] | None:
        return self.items.get(self.key(text))

    def add(self, answers: dict[str, dict[str, str]]) -> None:
        self.items.update({self.key(t): a for t, a in answers.items()})
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.writelines(json.dumps({"key": self.key(t), "answer": a}, ensure_ascii=False) + "\n"
                             for t, a in answers.items())


def judge_all(texts: list[str], judge: Judge, cache: Cache, batch_size: int,
              workers: int) -> tuple[dict[str, dict[str, str]], int]:
    """返回 ({文本: 判断}, 失败的条数)。失败的批不写缓存，下次重跑补上。"""
    todo = [t for t in dict.fromkeys(texts) if cache.get(t) is None]
    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
    failed = 0
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(judge, b): b for b in batches}
        for i, fut in enumerate(as_completed(futures), 1):
            batch = futures[fut]
            try:
                flagged = fut.result()
            except Exception as e:  # noqa: BLE001 单批失败不影响其他批
                failed += len(batch)
                print(f"失败一批 {len(batch)} 条（首条 {batch[0][:20]!r}）：{e}", file=sys.stderr)
                continue
            cache.add({t: flagged.get(j, {"reason": VALID, "note": ""}) for j, t in enumerate(batch)})
            print(f"判断 {i}/{len(batches)} 批")
    return {t: a for t in texts if (a := cache.get(t)) is not None}, failed


def kimi_judge(args: argparse.Namespace) -> Judge:
    from openai import OpenAI

    api_key = os.environ.get("KIMI_API_KEY")
    if not api_key:
        raise SystemExit("缺少环境变量 KIMI_API_KEY")
    client = OpenAI(base_url=args.base_url, api_key=api_key, timeout=600, max_retries=3)

    def judge(texts: list[str]) -> dict[int, dict[str, str]]:
        resp = client.chat.completions.create(
            model=args.model, reasoning_effort=args.reasoning_effort, max_tokens=32000,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": batch_prompt(texts)}])
        return parse_answer(resp.choices[0].message.content or "", len(texts))

    return judge


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, help="判断缓存 JSONL，不给则不缓存")
    parser.add_argument("--text-column", default="turns")
    parser.add_argument("--limit", type=int, help="只判前 N 条（试跑用），输出也只含这 N 条")
    parser.add_argument("--batch-size", type=int, default=40, help="每次发给模型的题数")
    parser.add_argument("--model", default="kimi-for-coding")
    parser.add_argument("--base-url", default="https://api.kimi.com/coding/v1")
    parser.add_argument("--reasoning-effort", choices=["low", "high", "max"], default="low")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, judge_factory: Callable[[argparse.Namespace], Judge] = kimi_judge) -> int:
    args = parse_args(argv)
    records, columns = read_records(args.input)
    if args.limit:
        records = records[:args.limit]
    clash = [c for c in OUTPUT_COLUMNS if c in columns]
    if clash:
        print(f"错误：输入已包含输出列 {clash}", file=sys.stderr)
        return 2
    texts = [case_text(r[args.text_column]) for r in records]
    cache = Cache(args.cache, args.model, args.batch_size)
    answers, failed = judge_all(texts, judge_factory(args), cache, args.batch_size, args.workers)

    output = []
    for r, t in zip(records, texts):
        a = answers.get(t)
        output.append({**r, "filter_verdict": REASONS[a["reason"]] if a else "",
                       "filter_reason": a["reason"] if a else "", "filter_note": a["note"] if a else ""})
    write_records(args.output, output, [*columns, *OUTPUT_COLUMNS])

    print(f"共 {len(records)} 条，结论：" + "，".join(f"{k} {n}" for k, n in
                                                Counter(o["filter_verdict"] or "未判" for o in output).most_common()))
    print("原因：" + "，".join(f"{k} {n}" for k, n in Counter(o["filter_reason"] or "未判" for o in output).most_common()))
    if failed:
        print(f"失败 {failed} 条，重跑同一命令补上", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
