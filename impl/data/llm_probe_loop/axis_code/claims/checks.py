"""说法抽取的逐字与隔离规则（同 llm_probe knowledge_loop/extract.parse_claims，口径不变）。

spans 每段 {turn, text}：turn 是材料里给了的轮，text 逐字出自那一轮的回答，可几条共用；claim 自由写；
context 逐字出自任一轮回答或用户问题；qualifies 指向另一条说法；
context 不夹带别条说法的片段。逐字比对前去掉空白与 Markdown 强调符、统一引号；回答是 JSON 时也比对解码后的字段。
"""
import json
import re
from collections.abc import Mapping

_FORMAT = re.compile(r'[\s*`]+')
_QUOTES = str.maketrans({c: '"' for c in '“”„‟＂「」『』'} | {c: "'" for c in '‘’‚‛＇'})


def _plain(text):
    return _FORMAT.sub('', text).translate(_QUOTES)


def _answer_texts(output_text):
    try:
        parsed = json.loads(output_text)
    except ValueError:
        return (_plain(output_text),)
    leaves, stack = [], [parsed]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            leaves.append(node)
        elif isinstance(node, Mapping):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return (_plain(output_text), *(_plain(leaf) for leaf in leaves))


def _in(segment, texts):
    return any(_plain(segment) in text for text in texts)


def _contains_value(segment, value):
    edge = re.compile(r'[A-Za-z0-9]')
    start = segment.find(value)
    while start >= 0:
        end = start + len(value)
        inside = (start > 0 and edge.match(segment[start - 1]) and edge.match(value[0])) or \
                 (end < len(segment) and edge.match(segment[end]) and edge.match(value[-1]))
        if not inside:
            return True
        start = segment.find(value, start + 1)
    return False


def check(view):
    turns = {d["turn"]: _answer_texts(d["output_text"]) for d in view.materials["case.deliveries"]}
    answer = tuple(t for texts in turns.values() for t in texts)
    asked = (_plain("\n".join(view.materials["case.user_turns"])),)
    claims, problems, seen = view.own["claims"], [], set()
    for claim in claims:
        key = claim["claim_id"]
        if not key.strip() or key in seen:
            problems.append(f"claim_id 必须唯一且非空：{key!r}")
        seen.add(key)
        if not claim["claim"].strip():
            problems.append(f"说法 {key} 的 claim 不能为空")
        for span in claim["spans"]:
            if span["turn"] not in turns:
                problems.append(f"说法 {key} 的 spans 段 turn={span['turn']!r} 不是材料里给了的轮（{sorted(turns)}）")
            elif not span["text"].strip() or not _in(span["text"], turns[span["turn"]]):
                problems.append(f"说法 {key} 的 spans 段 {span['text']!r} 不是第 {span['turn']} 轮 output_text 的逐字连续原文")
        bad = [c for c in claim["context"] if not c.strip() or not (_in(c, answer) or _in(c, asked))]
        if bad:
            problems.append(f"说法 {key} 的 context 段 {bad[0]!r} 既不是任一轮回答也不是用户问题的逐字连续原文")
    for claim in claims:
        q = claim["qualifies"].strip()
        if q and (q == claim["claim_id"] or q not in seen):
            problems.append(f"说法 {claim['claim_id']} 的 qualifies {q!r} 不是另一条说法的 claim_id")
    for claim in claims:
        own = {s["text"] for s in claim["spans"]}
        for other in claims:
            for span in {s["text"] for s in other["spans"]}:
                if span in own:
                    continue
                leaked = [c for c in claim["context"] if _plain(c) != _plain(span) and _contains_value(c, span)]
                if leaked:
                    problems.append(f"说法 {claim['claim_id']} 的 context {leaked[0]!r} 含了说法 {other['claim_id']} 的片段 {span!r}，只放定位所需的上下文")
    return problems
