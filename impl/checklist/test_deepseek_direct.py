#!/usr/bin/env python3
"""Direct diagnostic for DeepSeek through the unified OpenAI-compatible adapter."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path


project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def main() -> int:
    from impl.core.config import ConfigError, get_runtime_config
    from impl.core.llm_client import LlmClient, chat_completions_url

    runtime_config = get_runtime_config()
    try:
        runtime_config.require("llm")
    except ConfigError as exc:
        print(f"❌ {exc}")
        return 1
    llm_config = runtime_config.llm
    print("✓ DeepSeek credential resolved through RuntimeConfig")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {llm_config.api_key}",
    }
    data = {
        "model": llm_config.model,
        "messages": [{"role": "user", "content": "Say 'test ok'"}],
        "temperature": llm_config.temperature,
    }
    try:
        print("\n[Test 1] Raw HTTP request to configured DeepSeek API...")
        request = urllib.request.Request(
            chat_completions_url(llm_config.base_url),
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read())
            print(f"  ✓ Response: {result['choices'][0]['message']['content']}")
    except Exception as exc:
        print(f"  ❌ Failed: {exc}")
        return 1

    print("\n[Test 2] Unified OpenAI-compatible model...")
    from agno.agent import Agent

    try:
        model = LlmClient(config=llm_config).build_model(reasoning_effort=None)
        agent = Agent(
            model=model,
            system_message="You are a helpful assistant.",
            use_json_mode=False,
        )
        result = agent.run("Say 'agno test ok'")
        print(f"  ✓ Response: {result.content if hasattr(result, 'content') else result}")
    except Exception as exc:
        print(f"  ❌ Failed: {exc}")
        return 1

    print("\n✓ All tests passed!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
