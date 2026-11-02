"""临时脚本：实测每个 LLM 端点的 prompt 容量上限（接受/拒绝的分界）。

用法：python scripts/_calibrate_endpoint_capacity_tmp.py [--sizes 102400,204800,307200]
不写任何配置，只打印结论。
"""
from __future__ import annotations

import argparse
import time

from openai import OpenAI

from impl.core.config import get_llm_config
from impl.core.llm_client import provider_error_body

DEFAULT_SIZES = (102_400, 204_800, 307_200)


def probe(client: OpenAI, model: str, size: int) -> tuple[str, str]:
    """返回 (verdict, detail)：ok / rejected / error。"""
    body = "x" * max(size - 64, 1)
    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": body}],
            max_tokens=8,
            temperature=0,
        )
    except Exception as exc:
        return "error", f"{type(exc).__name__}: {str(exc)[:160]}"
    elapsed = time.monotonic() - started
    content = ""
    try:
        content = (response.choices[0].message.content or "").strip()
    except Exception:
        content = ""
    if provider_error_body(content):
        return "rejected", f"{content[:120]!r} ({elapsed:.1f}s)"
    if not content:
        return "rejected", f"empty content ({elapsed:.1f}s)"
    return "ok", f"{content[:40]!r} ({elapsed:.1f}s)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default=",".join(str(s) for s in DEFAULT_SIZES))
    args = parser.parse_args()
    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]

    config = get_llm_config()
    endpoints = [("primary", config.model, config.base_url, config.api_key)]
    for index, fallback in enumerate(config.fallbacks, start=1):
        endpoints.append((f"fallback{index}", fallback.model, fallback.base_url, fallback.api_key))

    print(f"声明窗口 context_window_tokens={config.capabilities.context_window_tokens}，"
          f"max_prompt_chars={config.max_prompt_chars}\n")
    for name, model, base_url, api_key in endpoints:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=300, max_retries=0)
        print(f"### {name}  {model}  {base_url}")
        for size in sizes:
            verdict, detail = probe(client, model, size)
            print(f"  {size:>9,} chars -> {verdict:9s} {detail}")
        print()


if __name__ == "__main__":
    main()
