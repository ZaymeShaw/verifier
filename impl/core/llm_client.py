from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import time

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MODEL_DEFAULT = "deepseek-v4-pro"
BASE_URL_DEFAULT = "https://api.deepseek.com/v1/chat/completions"

# Session start timestamp: ensures sessions from different runs don't share context
SESSION_START_TIME = int(time.time())


# REMOVED: _project_memory_path() - this function creates impl/knowledge directory
# which triggers Agno's auto-persistence. We don't use it anymore.


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


# CRITICAL: Set OPENAI_API_KEY before importing Agno modules.
# Agno's DeepSeek inherits from OpenAILike, which uses OpenAI SDK internally.
# The OpenAI SDK may cache environment variables at import time, so we must
# set OPENAI_API_KEY to DeepSeek key BEFORE any Agno imports.
_deepseek_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY") or load_env_md_key()
if _deepseek_key and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = _deepseek_key

from agno.agent import Agent
try:  # agno 1.x
    from agno.db.json import JsonDb
except ModuleNotFoundError:  # agno 2.x removed JsonDb
    class JsonDb:  # pragma: no cover - compatibility shim for legacy tests only
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

try:  # agno 1.x
    from agno.memory.manager import MemoryManager
except ModuleNotFoundError:  # agno 2.x compatibility
    class MemoryManager:  # pragma: no cover - compatibility shim for legacy tests only
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

from agno.models.deepseek import DeepSeek


def extract_json(text: str) -> Any:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try every fenced block in order. Many LLM outputs embed non-JSON
    # snippets (yaml configs, regex examples) inside ``` fences BEFORE the
    # actual JSON block — a non-greedy single match would silently grab the
    # first fence and drop the real JSON. Prefer json-tagged fences, then
    # any fence, then a bare-object fallback.
    fence_matches = list(re.finditer(r"```(\w+)?\s*(.*?)```", text, re.S))
    json_tagged = [m for m in fence_matches if (m.group(1) or "").lower() == "json"]
    untagged = [m for m in fence_matches if (m.group(1) or "").lower() not in {"json", ""}]
    any_tagged = fence_matches
    for group in (json_tagged, untagged, any_tagged):
        for m in group:
            body = m.group(2)
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                continue
    start = min([idx for idx in [text.find("{"), text.find("[")] if idx >= 0], default=-1)
    if start >= 0:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            return {"raw_text": text}
    return {"raw_text": text}


def _response_content(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False)
    return str(content or "")


# Substrings that indicate the upstream provider returned an error message
# instead of a JSON model payload. Agno 2.x surfaces these as plain content.
_PROVIDER_ERROR_MARKERS = (
    "insufficient balance",
    "insufficient_quota",
    "rate limit",
    "rate_limit",
    "exceeded your current quota",
    "incorrect api key",
    "authentication",
    "unauthorized",
    "401",
    "402",
    "429",
    "service unavailable",
    "internal server error",
    "gateway timeout",
)


def _detect_response_failure(content: str, parsed: Any) -> str:
    """Return a human-readable failure reason when the response is clearly not
    a usable JSON payload produced by the model.

    Returns an empty string when the response looks like a legitimate (possibly
    partial) structured payload so we never reject real judging/attribution
    output.
    """
    text = (content or "").strip()
    lower = text.lower()

    # 1) Provider error strings surfaced verbatim instead of JSON.
    if text and lower in {m.strip() for m in _PROVIDER_ERROR_MARKERS}:
        return f"provider error: {text}"

    # 2) extract_json wraps a non-JSON string in {"raw_text": ...}. When that
    #    is the only key (no judging/attribution fields), the model did not
    #    produce structured output.
    if isinstance(parsed, dict):
        keys = set(parsed.keys()) - {"raw_text", "raw_model_response", "value"}
        if not keys:
            raw_text = str(parsed.get("raw_text") or parsed.get("value") or text)
            if any(marker in raw_text.lower() for marker in _PROVIDER_ERROR_MARKERS):
                return f"provider error: {raw_text}"
            if raw_text and raw_text.strip() and "content" not in parsed:
                # Non-empty, non-JSON prose: the call did not yield structured JSON.
                return f"non-json response: {raw_text[:200]}"

    # 3) Empty content entirely.
    if not text:
        return "empty response"

    return ""


def _raw_response(result: Any) -> Any:
    raw = getattr(result, "raw_response", None)
    if raw is not None:
        return raw
    if hasattr(result, "model_dump"):
        try:
            dump = result.model_dump()
            # Preserve metrics if available
            if hasattr(result, "metrics") and "metrics" not in dump:
                metrics = getattr(result, "metrics")
                if hasattr(metrics, "model_dump"):
                    dump["metrics"] = metrics.model_dump()
                elif isinstance(metrics, dict):
                    dump["metrics"] = metrics
            return dump
        except Exception:
            pass
    if isinstance(result, dict):
        return result
    response = {"content": _response_content(result)}
    # Try to extract metrics from Agno RunOutput
    if hasattr(result, "metrics"):
        metrics = getattr(result, "metrics")
        if hasattr(metrics, "model_dump"):
            response["metrics"] = metrics.model_dump()
        elif isinstance(metrics, dict):
            response["metrics"] = metrics
    return response


def _normalize_base_url(base_url: str) -> str:
    return base_url.rsplit("/v1/chat/completions", 1)[0] if base_url.endswith("/v1/chat/completions") else base_url


def project_llm_client(spec: Any, role: str, knowledge: Any = None, tools: list = None,
                       tool_call_limit: Optional[int] = None,
                       compress_tool_results: bool = False,
                       max_tool_calls_from_history: Optional[int] = None) -> "LlmClient":
    """
    Create LLM client for judge/attribute with NO persistence, NO memories, NO sessions.

    Context engineering strategy:
    - Knowledge: NO - use tools for on-demand retrieval
    - User memories: NO - each case should be independent
    - Session history: NO - each judge call is stateless
    - DB persistence: NO - no session/memory storage
    - Tool call budget: only set for roles that actually use tools (attribute).

    Args:
        spec: Project specification
        role: Role name (e.g., "judge", "attribute")
        knowledge: Optional knowledge base (DEPRECATED - use tools instead)
        tools: Optional list of tools to provide to the agent
        tool_call_limit: Cap on tool calls within one agent.run() (attribute only)
        compress_tool_results: If True, compress prior tool results (attribute only)
        max_tool_calls_from_history: Prune tool messages from history (attribute only)
    """
    project_id = str(getattr(spec, "project_id", "default") or "default")
    # CRITICAL: Do NOT create JsonDb or MemoryManager
    # CRITICAL: Do NOT set user_id - it triggers Agno to auto-create impl/knowledge/{user_id}/ directory
    return LlmClient(
        memory_db=None,  # NO persistence
        memory_manager=None,  # NO memories
        knowledge=knowledge,  # Will be set to None by caller
        knowledge_retriever=None,
        tools=tools,
        user_id=None,  # CRITICAL: None to prevent auto directory creation
        session_id=None,  # NO session persistence
        tool_call_limit=tool_call_limit,
        compress_tool_results=compress_tool_results,
        max_tool_calls_from_history=max_tool_calls_from_history,
    )


class LlmClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = MODEL_DEFAULT,
        memory_manager: Any = None,
        memory_db: Any = None,
        knowledge: Any = None,
        knowledge_retriever: Any = None,
        tools: list = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tool_call_limit: Optional[int] = None,
        compress_tool_results: bool = False,
        max_tool_calls_from_history: Optional[int] = None,
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY") or load_env_md_key()
        self.base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("LLM_BASE_URL") or BASE_URL_DEFAULT
        self.model = model
        self.memory_manager = memory_manager
        self.memory_db = memory_db
        self.knowledge = knowledge
        self.knowledge_retriever = knowledge_retriever
        self.tools = tools or []
        self.user_id = user_id
        self.session_id = session_id
        self.tool_call_limit = tool_call_limit
        self.compress_tool_results = compress_tool_results
        self.max_tool_calls_from_history = max_tool_calls_from_history

    def complete_json(self, system: str, user: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Complete JSON request with isolated session per trace.

        Args:
            system: System prompt
            user: User prompt
            trace_id: Optional trace ID for session isolation. If provided, creates a unique
                     session for this specific case/trace, preventing cross-case contamination.
        """
        if not self.api_key:
            return {"error": "missing_api_key", "raw_text": "No DeepSeek API key configured."}

        # Ensure OPENAI_API_KEY is set for this request (defensive, already set at module import)
        original_openai_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = self.api_key

        try:
            model = DeepSeek(
                id=self.model,
                api_key=self.api_key,
                base_url=_normalize_base_url(self.base_url),
                temperature=0,
                reasoning_effort="max",
            )

            # CRITICAL: Use trace-specific session ID to isolate different cases
            # BUT: Prevent conversation history accumulation within same session
            if trace_id is None:
                import uuid
                trace_id = str(uuid.uuid4())

            # Each trace gets unique session, prevents cross-case contamination
            effective_session_id = f"{trace_id}:{SESSION_START_TIME}"

            # Retry once on transient LLM failure (network/timeout/rate-limit).
            # Without this, a single hiccup yields verdict=uncertain for the case.
            last_exc: Optional[Exception] = None
            result = None
            for attempt in range(2):
                try:
                    try:
                        agent = Agent(
                            model=model,
                            system_message=system,
                            use_json_mode=True,
                            tools=self.tools,
                            memory_manager=None,
                            db=None,
                            knowledge=None,
                            knowledge_retriever=None,
                            user_id=self.user_id,
                            session_id=f"{effective_session_id}:retry{attempt}" if attempt else effective_session_id,
                            enable_user_memories=False,
                            add_memories_to_context=False,
                            add_knowledge_to_context=False,
                            add_history_to_context=False,
                            num_history_runs=0,
                            num_history_messages=0,
                            tool_call_limit=self.tool_call_limit,
                            compress_tool_results=self.compress_tool_results,
                            max_tool_calls_from_history=self.max_tool_calls_from_history,
                        )
                    except TypeError as exc:
                        if "unexpected keyword" not in str(exc):
                            raise
                        agent = Agent(
                            model=model,
                            system_message=system,
                            use_json_mode=True,
                            tools=self.tools,
                            memory=None,
                            storage=None,
                            knowledge=None,
                            retriever=None,
                            user_id=self.user_id,
                            session_id=f"{effective_session_id}:retry{attempt}" if attempt else effective_session_id,
                            enable_user_memories=False,
                            add_memory_references=False,
                            add_references=False,
                            add_history_to_messages=False,
                            num_history_runs=0,
                            num_history_responses=0,
                            tool_call_limit=self.tool_call_limit,
                        )
                    result = agent.run(user)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    logger.warning("LLM retry attempt %s failed: %s", attempt + 1, exc)
                    if attempt == 0:
                        time.sleep(2)
            if last_exc is not None:
                raise last_exc

            # Extract metrics for token tracking
            token_metrics = {}
            if hasattr(result, "metrics") and result.metrics:
                metrics = result.metrics
                token_metrics = {
                    "input_tokens": getattr(metrics, "input_tokens", 0),
                    "output_tokens": getattr(metrics, "output_tokens", 0),
                    "cache_read_tokens": getattr(metrics, "cache_read_tokens", 0),
                    "cache_write_tokens": getattr(metrics, "cache_write_tokens", 0),
                    "reasoning_tokens": getattr(metrics, "reasoning_tokens", 0),
                    "total_tokens": getattr(metrics, "total_tokens", 0),
                }
                logger.debug(
                    "Token usage: %s in + %s out + %s cache = %s total",
                    token_metrics["input_tokens"],
                    token_metrics["output_tokens"],
                    token_metrics["cache_read_tokens"],
                    token_metrics["total_tokens"],
                )
        except Exception as exc:
            # Restore original OPENAI_API_KEY on error
            if original_openai_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = original_openai_key
            return {"error": "llm_request_failed", "raw_text": str(exc)}
        finally:
            # Always restore original OPENAI_API_KEY
            if original_openai_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = original_openai_key

        content = _response_content(result)
        parsed = extract_json(content)
        raw_response = _raw_response(result)

        # Add token metrics to raw_response if available
        if token_metrics:
            if isinstance(raw_response, dict):
                raw_response["metrics"] = token_metrics

        # Detect provider-level failures. Agno 2.x (unlike 1.x) does not raise
        # on HTTP errors such as 402 Insufficient Balance / 429 / auth errors;
        # it returns a RunResponse whose content is the bare error string. Such
        # a payload carries no judging/attribution fields, so flag it as a failed
        # request rather than letting callers treat the error string as a
        # (garbage) verdict and silently fall through to non-deterministic paths.
        failure_reason = _detect_response_failure(content, parsed)
        if failure_reason:
            logger.warning("LLM response treated as failure: %s", failure_reason)
            return {"error": "llm_request_failed", "raw_text": failure_reason, "raw_model_response": raw_response}

        if isinstance(parsed, dict):
            parsed.setdefault("raw_model_response", raw_response)
            return parsed
        return {"value": parsed, "raw_model_response": raw_response}
