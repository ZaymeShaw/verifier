from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
MODEL_DEFAULT = "deepseek-v4-pro"
BASE_URL_DEFAULT = "https://api.deepseek.com/v1/chat/completions"


def load_env_md_key() -> str:
    path = ROOT / "env.md"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.lower().startswith("deepseek key") and "：" in line:
            return line.split("：", 1)[1].strip()
        if line.lower().startswith("deepseek key") and ":" in line:
            return line.split(":", 1)[1].strip()
    return ""


def extract_json(text: str) -> Any:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    start = min([idx for idx in [text.find("{"), text.find("[")] if idx >= 0], default=-1)
    if start >= 0:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            return {"raw_text": text}
    return {"raw_text": text}


class LlmClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: str = MODEL_DEFAULT):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY") or load_env_md_key()
        self.base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("LLM_BASE_URL") or BASE_URL_DEFAULT
        self.model = model

    def complete_json(self, system: str, user: str) -> Dict[str, Any]:
        if not self.api_key:
            return {"error": "missing_api_key", "raw_text": "No DeepSeek API key configured."}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"error": "llm_request_failed", "raw_text": str(exc)}
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = extract_json(content)
        if isinstance(parsed, dict):
            parsed.setdefault("raw_model_response", result)
            return parsed
        return {"value": parsed, "raw_model_response": result}
