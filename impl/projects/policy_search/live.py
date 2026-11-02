"""Policy Search 真实服务适配。主体单轮；追问场景走同一 POST 的多轮循环。"""
from __future__ import annotations

import urllib.error
from typing import Any, Dict
from urllib.parse import urljoin

from impl.core.live_protocol import LiveServiceUnavailableError, RealServiceLive
from impl.core.live_transport import LiveHTTPStatusError, LiveTransport


def _single_response(raw_response: list[Any]) -> Dict[str, Any]:
    if len(raw_response) != 1 or not isinstance(raw_response[0], dict):
        raise ValueError("policy-search must return exactly one JSON object")
    return dict(raw_response[0])


class PolicySearchLive(RealServiceLive):
    """通过受控 transport 调用 policy-search。"""

    def deliver_real(self, request: Any, transport: LiveTransport) -> LiveTransport:
        service = self.spec.require_service("primary")
        url = urljoin(
            str(service["base_url"]).rstrip("/") + "/",
            str(service["endpoint"]).lstrip("/"),
        )
        try:
            transport.request(
                str(service["method"]),
                url,
                json_body=request,
                timeout=float(service["timeout_seconds"]),
                carries_live_request=True,
                contributes_raw_response=True,
            )
        except LiveHTTPStatusError as exc:
            raise RuntimeError(f"policy-search API request rejected: {exc}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LiveServiceUnavailableError(
                f"policy-search service unavailable: {exc}"
            ) from exc
        return transport

    def extract_output(self, raw_response: list[Any]) -> Dict[str, Any]:
        envelope = _single_response(raw_response)
        code = int(envelope.get("code", -1))
        msg = str(envelope.get("msg") or "")
        if code != 0:
            raise RuntimeError(f"policy-search API failed: code={code}, msg={msg}")

        data = envelope.get("data")
        if not isinstance(data, dict):
            raise ValueError("policy-search success response is missing data")
        extra = data.get("extra_output_params")
        if not isinstance(extra, dict):
            raise ValueError("policy-search response is missing extra_output_params")
        result = extra.get("policySearchParseResult")
        if not isinstance(result, dict):
            raise ValueError("policy-search response is missing policySearchParseResult")

        status = str(result.get("status") or "")
        filter_tree = result.get("filter")
        if status not in {"SUCCESS", "UNSUPPORTED"}:
            raise ValueError(f"unsupported policy-search status: {status!r}")
        if status == "SUCCESS" and not isinstance(filter_tree, dict):
            raise ValueError("policy-search SUCCESS requires a filter object")
        if status == "UNSUPPORTED" and filter_tree is not None:
            raise ValueError("policy-search UNSUPPORTED must not return a partial filter")

        return {
            "code": code,
            "msg": msg,
            "status": status,
            "query": str(result.get("query") or ""),
            "filter": filter_tree,
            "message": str(result.get("message") or ""),
        }

    def application_boundary(
        self,
        raw_response: Any,
        extracted_output: Dict[str, Any],
        request: Any,
    ) -> Dict[str, Any]:
        return {
            "dependency_status": "available",
            "allow_fallback": False,
            "excluded_evidence": [],
            "notes": (
                "UNSUPPORTED is an in-scope parser decision"
                if extracted_output.get("status") == "UNSUPPORTED"
                else "parser returned an executable filter"
            ),
        }

    def project_fields(
        self,
        raw_response: Any,
        extracted_output: Dict[str, Any],
        request: Any,
        application_boundary: Dict[str, Any],
    ) -> Dict[str, Any]:
        tree = extracted_output.get("filter")
        return {
            "parse_status": extracted_output.get("status"),
            "filter_root_type": tree.get("type") if isinstance(tree, dict) else None,
        }

    def _has_visible_goal_evidence(self, output: Any) -> bool:
        if not isinstance(output, dict) or not output:
            return False
        if output.get("filter"):
            return True
        if str(output.get("message") or "").strip():
            return True
        return str(output.get("status") or "") in {"SUCCESS", "UNSUPPORTED"}

    def _summarize_assistant(self, extracted: Dict[str, Any]) -> str:
        if not extracted:
            return "empty"
        message = str(extracted.get("message") or "").strip()
        if message:
            return message
        status = str(extracted.get("status") or "").strip()
        return f"status={status}" if status else "ok"
