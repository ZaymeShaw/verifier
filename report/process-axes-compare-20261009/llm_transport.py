"""两臂共用的模型通道：直连已验证可用的上游（deepseek-flash），逐次调用记账。

与生产 `impl/core/llm_client.LlmClient.complete_json` 等价的三件事（见 CORRECTION-1.md §1）：
1. system 末尾追加 `render_output_constraint(output_spec)`；**不带** `response_format`（生产 LlmClient 从未启用，靠提示词约束 + 事后强校验 + 纠错轮）；
2. 解析用仓库的 `extract_json`（含未转义引号修复）与 `_select_schema_matching_object`；
3. 解析后跑 `enforce_output`，不合规抛 ValueError，交给六轴代码自己的纠错轮，不在本层吞掉。

本层只负责"发请求"：请求体与生产一致（messages/model/temperature/stream/stream_options，
追加六轴传入的 reasoning_effort，**不设** max_tokens，**不带** response_format）；
429/5xx/网络错误退避重试；finish_reason=length（截断）重发；
重试用尽返回 `{"error": "llm_request_failed", "raw_text": ...}`（与生产一致，由
`raise_for_error_payload` 转成轴失败）。每条 HTTP 请求都会留档，失败的那次不丢。

为什么不用仓库的 LlmClient：现行臂要的是 HEAD 的六轴实现，不是生产部署的端点/模型选择；
仓库配置把 judge 固定成 deepseek-v4-pro 且无法从环境改，与本任务"两臂同一个已验证模型"不符。
"""
from __future__ import annotations

import json
import random
import sys
import threading
import time

import requests

import experiment_io as io

sys.path.insert(0, str(io.ROOT))

from impl.core.llm_client import JsonExtractionError, _select_schema_matching_object, extract_json  # noqa: E402
from impl.core.structured_output import enforce_output, render_output_constraint  # noqa: E402

from experiment_io import HERE, load_provider, now, save_json, save_text  # noqa: E402

MAX_ATTEMPTS = 6
# 与生产一致：不设 max_tokens，用模型默认上限。中转若要求必填则降级到 64000（见 DEVIATIONS.md）。
FALLBACK_MAX_TOKENS = 64000
MAX_TOKENS = None
# 整个实验共用一道闸：deepseek 中转站在并发 >3 时开始 429。
CONCURRENCY = threading.Semaphore(2)  # 中转的并发上限是 3，而且是多方共享；本机留一个余量，避免 429


def extract_json_strict(text: str, output_spec):
    """生产的解析顺序：extract_json（宽容）→ 多对象时按 schema 选 → 都不行再抛诊断。"""
    try:
        parsed = extract_json(text)
    except JsonExtractionError:
        parsed = None
    parsed = _select_schema_matching_object(text, parsed, output_spec)
    if parsed is None:
        parsed = extract_json(text)
    return parsed


class Transport:
    """按角色的模型通道；complete_json 的签名与 LlmClient 一致。"""

    def __init__(self, provider: str, model: str, *, arm: str = "arm", tag: str = ""):
        config = load_provider(provider)
        self.provider = provider
        self.model = model
        self.url = config["UPSTREAM_API_BASE"].rstrip("/") + "/chat/completions"
        self.auth = {"Authorization": "Bearer " + config["UPSTREAM_API_KEY"], "Content-Type": "application/json"}
        self.semaphore = CONCURRENCY
        self.lock = threading.Lock()
        self.arm = arm
        self.tag = tag
        self.attempts: list[dict] = []
        self.calls = 0
        self.succeeded = 0
        self.max_tokens = MAX_TOKENS

    # ---- 一次 HTTP 请求 ------------------------------------------------------

    def _one_request(self, system: str, user: str, stage: str, attempt: int, reasoning_effort=None,
                     history=None) -> dict:
        # history：夹在 system 与本轮 user 之间的前几轮消息（多轮追加时用，前缀才能命中缓存）
        body = {"model": self.model,
                "messages": [{"role": "system", "content": system}, *(history or []),
                             {"role": "user", "content": user}],
                "temperature": 0, "stream": True,
                "stream_options": {"include_usage": True}}
        if self.max_tokens:
            body["max_tokens"] = self.max_tokens
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        record = {"arm": self.arm, "tag": self.tag, "stage": stage, "attempt": attempt,
                  "requested_model": self.model, "system_chars": len(system), "user_chars": len(user),
                  "system_sha256": io.digest(system), "max_tokens": self.max_tokens,
                  "reasoning_effort": reasoning_effort, "started_at": now()}
        started = time.monotonic()
        models: set[str] = set()
        usage: dict = {}
        finishes: list[str] = []
        chunks: list[str] = []
        reasoning: list[str] = []
        try:
            with requests.post(self.url, headers=self.auth, json=body, stream=True, timeout=(300, 1500)) as response:
                record["status_code"] = response.status_code
                if response.status_code != 200:
                    record["error_text"] = response.text[:4000]
                else:
                    for line in response.iter_lines():
                        text = line.decode("utf-8")
                        if not text.startswith("data:") or text == "data: [DONE]":
                            continue
                        item = json.loads(text[5:])
                        if item.get("model"):
                            models.add(item["model"])
                        if item.get("usage"):
                            usage = item["usage"]
                        for choice in item.get("choices") or []:
                            delta = choice.get("delta") or {}
                            chunks.append(delta.get("content") or "")
                            reasoning.append(delta.get("reasoning_content") or "")
                            if choice.get("finish_reason"):
                                finishes.append(choice["finish_reason"])
        except Exception as exc:  # noqa: BLE001
            record.update(error_type=type(exc).__name__, error_text=str(exc)[:1000])
        elapsed = round(time.monotonic() - started, 3)
        text = "".join(chunks)
        record.update(elapsed_seconds=elapsed, response_models=sorted(models), usage=usage,
                      finish_reasons=finishes, completion_tokens=int(usage.get("completion_tokens") or 0),
                      prompt_tokens=int(usage.get("prompt_tokens") or 0),
                      content_sha256=io.digest(text), content_chars=len(text),
                      reasoning_chars=len("".join(reasoning)))
        record["truncated"] = "length" in finishes
        record["http_ok"] = record.get("status_code") == 200 and bool(text)
        record["ok"] = record["http_ok"] and not record["truncated"]
        with self.lock:
            index = len(self.attempts)
            self.attempts.append(record)
        save_text(HERE / "runs" / self.arm / "raw" / f"{self.tag}__{stage}__attempt{attempt}__{index}.txt",
                  (text + "\n<<<REASONING>>>\n" + "".join(reasoning)) if (text or reasoning)
                  else (record.get("error_text") or "(no output)"), exclusive=False)
        return {**record, "text": text}

    # ---- 对外接口 -----------------------------------------------------------

    def complete_json(self, system, user, trace_id=None, reasoning_effort=None, output_spec=None, stage="",
                      history=None, constraint_in_user=False, **kw):
        """constraint_in_user=True：输出结构约束放到本轮 user 末尾，system 保持逐字不变（多轮共享前缀缓存）。"""
        if output_spec is None:
            raise TypeError("complete_json 缺少 output_spec 参数（spec/struct_output.md 要求所有 LLM 调用都过结构化输出协议）")
        constraint = render_output_constraint(output_spec)
        if constraint_in_user:
            effective, user = system, user + "\n\n" + constraint
        else:
            effective = system + "\n\n" + constraint
        save_text(HERE / "runs" / self.arm / "prompt" / f"{self.tag}__{stage}__system.txt", effective, exclusive=False)
        with self.semaphore:
            self.calls += 1
            last = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                last = self._one_request(effective, user, stage, attempt, reasoning_effort, history)
                if last["ok"]:
                    break
                if last.get("status_code") == 400 and not self.max_tokens \
                        and "max_tokens" in str(last.get("error_text") or "").lower():
                    # 中转要求必填输出上限时降级（任务允许：不低于 64000）
                    self.max_tokens = FALLBACK_MAX_TOKENS
                    continue
                if last.get("status_code") in (401, 403, 404):
                    return {"error": "llm_request_failed", "raw_text": last.get("error_text", "")[:2000]}
                if last.get("status_code") == 429:
                    # 中转的并发闸是全局的：等别的调用先落地，退避给得比一般错误更宽。
                    time.sleep(min(90.0, 8.0 * attempt) * (0.5 + random.random()))
                else:
                    time.sleep(min(60.0, 4.0 * attempt) * (0.5 + random.random()))
            else:
                detail = (f"{MAX_ATTEMPTS} 次请求均无有效输出；最后 status={last.get('status_code')} "
                          f"truncated={last.get('truncated')} error={(last.get('error_text') or '')[:400]}")
                return {"error": "llm_request_failed", "raw_text": detail}
            self.succeeded += 1
            try:
                parsed = extract_json_strict(last["text"], output_spec)
            except Exception as exc:  # noqa: BLE001  —— ValueError 交给六轴自己的纠错轮
                error = f"[{stage}] {type(exc).__name__}: {exc}"
                with self.lock:
                    self.attempts[-1]["parse_ok"] = False
                    self.attempts[-1]["parse_error"] = error[:1000]
                raise ValueError(error) from exc
            with self.lock:
                self.attempts[-1]["parse_ok"] = True
            # 强校验阻断：不合规抛 ValueError（不吞、不替换），由调用方的纠错轮重问。
            enforce_output(parsed, output_spec, caller=stage)
            if isinstance(parsed, dict):
                parsed.setdefault("metrics", {"model": "/".join(last["response_models"]) or self.model,
                                              "usage": last["usage"], "stage": stage})
            return parsed

    def usage(self) -> dict:
        return {"llm_calls": self.calls, "llm_model": self.model, "llm_endpoint": self.provider,
                "llm_attempts": len(self.attempts),
                "llm_failed_attempts": sum(1 for a in self.attempts if not a["ok"]),
                "model_policy": "same_model"}

    def flush(self, path) -> None:
        with self.lock:
            snapshot = list(self.attempts)
        save_json(path, {"arm": self.arm, "tag": self.tag, "model": self.model,
                         "calls": self.calls, "succeeded": self.succeeded, "attempts": snapshot},
                  exclusive=False)
