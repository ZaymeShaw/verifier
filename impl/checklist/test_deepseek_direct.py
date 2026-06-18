#!/usr/bin/env python3
"""
直接测试 DeepSeek API 是否正常工作
"""
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from impl.core.llm_client import load_env_md_key

# Load DeepSeek key
key = load_env_md_key()
if not key:
    print("❌ No DeepSeek key found in env.md")
    sys.exit(1)

print(f"✓ DeepSeek key loaded: {key[:10]}...")

# Test with raw HTTP request
import urllib.request
import json

url = "https://api.deepseek.com/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {key}"
}
data = {
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "Say 'test ok'"}],
    "temperature": 0
}

try:
    print("\n[Test 1] Raw HTTP request to DeepSeek API...")
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read())
        content = result["choices"][0]["message"]["content"]
        print(f"  ✓ Response: {content}")
except Exception as e:
    print(f"  ❌ Failed: {e}")
    sys.exit(1)

# Test with Agno DeepSeek
print("\n[Test 2] Agno DeepSeek model...")
os.environ["OPENAI_API_KEY"] = key

from agno.models.deepseek import DeepSeek
from agno.agent import Agent

try:
    model = DeepSeek(
        id="deepseek-chat",
        api_key=key,
        base_url="https://api.deepseek.com",
        temperature=0
    )
    agent = Agent(
        model=model,
        system_message="You are a helpful assistant.",
        use_json_mode=False
    )
    result = agent.run("Say 'agno test ok'")
    print(f"  ✓ Response: {result.content if hasattr(result, 'content') else result}")
except Exception as e:
    print(f"  ❌ Failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✓ All tests passed!")
