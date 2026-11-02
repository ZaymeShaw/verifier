"""中断时的状态盘点：两臂每个 case 每个轴有没有合格记录，以及调用/token 消耗。"""
from __future__ import annotations

import sys

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))


def axis_state(arm: str, pass_no: str):
    """返回 {(tag, axis): (state, pass_dir, calls, prompt_tokens, completion_tokens, models)}。

    state: ok / failed / blocked402 / missing；合格记录优先 pass<N>b。
    """
    rows = {}
    for directory in (f"pass{pass_no}", f"pass{pass_no}b"):
        for case_dir in sorted((io.HERE / "runs" / arm / directory).glob("*")):
            if not case_dir.is_dir():
                continue
            for path in sorted(case_dir.glob("*.json")):
                record = io.load_json(path)
                attempts = record.get("http_attempts") or []
                if arm == "new":
                    attempts = [a for batch in record.get("batches") or [] for a in batch.get("http_attempts") or []]
                blocked = any(a.get("status_code") == 402 for a in attempts)
                state = ("blocked402" if blocked else ("failed" if record.get("failed") else "ok"))
                if state != "blocked402" and record.get("bookkeeping_ok") is False:
                    state = "failed"
                key = (case_dir.name, path.stem)
                old = rows.get(key)
                if old and old[0] == "ok" and directory.endswith("b"):
                    pass
                if old and old[0] == "ok" and state != "ok":
                    continue  # 已有合格记录，坏的那份不覆盖
                rows[key] = (state, directory, len(attempts),
                             sum(a.get("prompt_tokens") or 0 for a in attempts),
                             sum(a.get("completion_tokens") or 0 for a in attempts),
                             sorted({m for a in attempts for m in (a.get("response_models") or [])}))
    return rows


def main():
    lines = ["# 中断时状态（每 case × 每轴）", ""]
    for arm in ("current", "new"):
        rows = axis_state(arm, "1")
        lines += [f"## {arm}", "", "| case | 轴 | 状态 | 记录位置 | 请求 | 输入token | 输出token | 应答模型 |",
                  "|---|---|---|---|---|---|---|---|"]
        for tag in io.CASES:
            for axis in io.AXES:
                state, directory, calls, ptok, ctok, models = rows.get((tag, axis), ("missing", "-", 0, 0, 0, []))
                lines.append(f"| {tag} | {axis} | {state} | {directory} | {calls} | {ptok} | {ctok} | {','.join(models) or '-'} |")
        ok = sum(1 for tag in io.CASES for axis in io.AXES if rows.get((tag, axis), ("missing",))[0] == "ok")
        lines += ["", f"合格轴 {ok}/48，"
                  f"被402挡 {sum(1 for k, v in rows.items() if v[0] == 'blocked402')}，"
                  f"模型侧失败 {sum(1 for k, v in rows.items() if v[0] == 'failed')}，"
                  f"缺 {sum(1 for tag in io.CASES for axis in io.AXES if rows.get((tag, axis), ('missing',))[0] == 'missing')}",
                  ""]
    io.save_text(io.HERE / "score" / "state.md", "\n".join(lines), exclusive=False)
    print("\n".join(lines[-8:]))


if __name__ == "__main__":
    main()
