"""llm_probe 文本形态轴2：capability 预设的 boundary 作为 G。

StructuredCarrier 的平行形态——不做字段×操作符×值查表。
G 的两种供给：
- boundary 文本（含预算内内联展开的资料正文），prompt-load；
- 超预算的大资料转目录条目，正文由资料工具箱（material_tools，孵化在本项目）按需查。
正确性由外壳保证，不靠模型智力：骨架先行、locator 只复制不计算、
引用机械核验打回重试（不放行假引用）、预算耗尽才允许说不清。
boundary 为空且无目录资料时，所有期望归位为「说不清（缺能力边界资料）」。
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from impl.core.capability_carrier import (
    CARRY_NO,
    CARRY_UNDECIDABLE,
    CARRY_YES,
    GAP_AMBIGUITY,
    GAP_UNGOVERNED,
    RECOG_BOUNDARY_STATEMENT,
    CarrierError,
    CarrierVerdict,
    CapabilityCarrierBase,
    placement_request,
)

_DEFAULT_RETRIES = 3
_DEFAULT_RETRY_BACKOFF = (0.5, 1.5, 3.0)
_TOOL_CALL_LIMIT = 8

CompleterFn = Callable[[str, str], Mapping[str, Any]]


@dataclass
class _TextVerdictOutput:
    carry: str = ""
    reason: str = ""
    self_recognition: str = ""
    citations: list[dict[str, str]] = field(default_factory=list)
    gap_kind: str = ""
    missing_material: str = ""


_CARRIER_SYSTEM = """\
你是承载性判定器。给你一条未达成的期望和一份能力边界描述。
只判断：这份能力边界描述能否证明该期望承载得了、还是承载不了、还是信息不够说不清。

规则：
- 只看能力边界描述和资料原文，不看这次交付了什么，不看 live 说了什么话
- carry 只能是 yes / no / undecidable
- carry=yes：能力边界描述明确表明该期望在覆盖范围内（承载得了）
- carry=no：能力边界描述明确表明该期望不在覆盖范围内（承载不了）——必须引用表明「承载不了」的原文语句作为自认
- carry=undecidable：描述不足以判定（信息不够、描述模糊、或期望与描述口径不一致）
- self_recognition：carry=no 时必填，逐字摘自能力边界描述或资料原文
- citations：每条引用必须可回指且会被机器核验——
  source 填资料 uri（material://项目/资料id）或 boundary（内联边界文本）；
  ref 填工具返回的行区间 locator（如 L43-L79，原样复制）或 boundary；
  note 逐字摘自该位置的原文（机器会回读核验，改写即被打回）
- gap_kind：carry=undecidable 时必填，取值「口径分歧」或「空间未受治理」
- missing_material：carry=undecidable 时必填，说明缺什么资料才能判定
- 不要编造能力边界描述中没有的信息；描述没说的就是说不清
"""

_CARRIER_TOOLS_GUIDE = """\
- 有「大资料未内联」目录条目时，正文不在上下文里：先 material_outline 看骨架菜单，
  从菜单选条目用 material_read 精读；找不到条目再 material_search 换关键词查。不查就下结论是失职
- locator 只复制不计算：下一步调用和 citations 的 ref 都原样复制工具返回的行区间
- 检索未命中 ≠ 资料没写：换词、换条目再试；工具预算耗尽仍无依据才允许 undecidable
"""


def _verdict_output_spec():
    from impl.core.structured_output import StructuredOutputSpec
    return StructuredOutputSpec.from_dataclass(
        _TextVerdictOutput,
        required_nonempty=["carry", "reason"],
        description="轴2承载性判定：对单条期望输出 carry/reason/self_recognition/citations/gap_kind/missing_material",
    )


def _citations_from(data: Mapping[str, Any], fallback_note: str) -> tuple[dict[str, str], ...]:
    citations = tuple(
        {
            "source": str(item.get("source") or "boundary"),
            "ref": str(item.get("ref") or "boundary"),
            "note": str(item.get("note") or ""),
        }
        for item in (data.get("citations") or [])
        if isinstance(item, Mapping)
    )
    if citations:
        return citations
    note = str(fallback_note or "").strip()
    if not note:
        return ()
    return ({"source": "boundary", "ref": "boundary", "note": note},)


def _parse_verdict(data: Mapping[str, Any] | None) -> CarrierVerdict | None:
    if not isinstance(data, Mapping):
        return None
    carry = str(data.get("carry") or "").strip()
    if carry not in (CARRY_YES, CARRY_NO, CARRY_UNDECIDABLE):
        return None
    reason = str(data.get("reason") or "").strip()
    if not reason:
        return None
    if carry == CARRY_NO:
        quote = str(data.get("self_recognition") or "").strip()
        if not quote:
            return None
        return CarrierVerdict(
            CARRY_NO, reason,
            citations=_citations_from(data, quote),
            recognition=RECOG_BOUNDARY_STATEMENT,
        )
    if carry == CARRY_UNDECIDABLE:
        gap = str(data.get("gap_kind") or "").strip()
        missing = str(data.get("missing_material") or "").strip()
        if gap not in (GAP_AMBIGUITY, GAP_UNGOVERNED) or not missing:
            return None
        return CarrierVerdict(
            CARRY_UNDECIDABLE, reason,
            gap_kind=gap, missing_material=missing,
            citations=_citations_from(data, reason),
        )
    citations = _citations_from(data, reason)
    if not citations:
        return None
    return CarrierVerdict(CARRY_YES, reason, citations=citations)


def _verify_citations(
    verdict: CarrierVerdict,
    boundary_text: str,
) -> list[str]:
    """产出时机械核验：source=material 回读 locator 验引句；source=boundary 验内联文本。

    只对 carry=yes/no（要落「做错了/做不了」的结论）强制；说不清不带结论性引用。
    返回失败明细列表，空列表即通过。
    """
    if verdict.carry not in (CARRY_YES, CARRY_NO):
        return []
    from impl.projects.llm_probe.material_tools import quote_in_text, verify_quote

    failures: list[str] = []
    for citation in verdict.citations:
        source = str(citation.get("source") or "")
        ref = str(citation.get("ref") or "")
        note = str(citation.get("note") or "")
        if not note.strip():
            failures.append(f"引用缺 note 引句（source={source}）")
            continue
        if source.startswith("material://"):
            parts = source[len("material://"):].split("/")
            if len(parts) != 2:
                failures.append(f"source 不是合法资料 uri: {source}")
                continue
            if ref and ref != "boundary":
                try:
                    ok = verify_quote(parts[0], parts[1], ref, note)
                except ValueError as exc:
                    failures.append(f"{source}#{ref}: {exc}")
                    continue
                if not ok:
                    failures.append(f"{source}#{ref} 处未找到引句「{note[:40]}…」")
            elif not quote_in_text(note, boundary_text):
                # 内联进 boundary 的资料没有独立 locator，退回边界文本核验。
                failures.append(f"{source} 的引句未出现在内联边界文本中")
        else:
            if not quote_in_text(note, boundary_text):
                failures.append(f"boundary 引句「{note[:40]}…」未出现在边界文本中")
    if verdict.carry == CARRY_NO:
        recognition_quotes = [str(c.get("note") or "") for c in verdict.citations]
        if not recognition_quotes:
            failures.append("carry=no 必须至少一条自认引用")
    return failures


def _catalog_signature(catalog: Sequence[Mapping[str, Any]]) -> str:
    return "|".join(f"{item.get('uri')}@{item.get('sha256')}" for item in catalog)


def _catalog_prompt(catalog: Sequence[Mapping[str, Any]]) -> str:
    if not catalog:
        return ""
    lines = ["\n可检索资料目录（正文不在上下文，用工具查询）："]
    for item in catalog:
        lines.append(
            f"- material_id=\"{item.get('id')}\" · {item.get('title')} · "
            f"{item.get('size_chars')} 字符 · {item.get('description') or '（无描述）'}"
        )
    return "\n".join(lines)


class TextCarrier(CapabilityCarrierBase):
    """文本形态：本 case 的 boundary（文本 + 可检索目录）作为 G，LLM 判承载性。"""

    def __init__(
        self,
        boundary_loader: Callable[[], str] | None = None,
        *,
        spec: Any = None,
        completer: CompleterFn | None = None,
        retries: int = _DEFAULT_RETRIES,
        retry_backoff: Sequence[float] = _DEFAULT_RETRY_BACKOFF,
    ):
        self._boundary_loader = boundary_loader
        self._spec = spec
        self._completer = completer
        self._retries = max(1, retries)
        self._backoff_schedule = tuple(retry_backoff)
        self._cache: dict[str, CarrierVerdict | CarrierError] = {}

    def _current_boundary(self) -> dict[str, Any]:
        """返回 {"text": str, "catalog": list}。"""
        if self._boundary_loader is not None:
            return {"text": str(self._boundary_loader() or "").strip(), "catalog": []}
        from impl.projects.llm_probe.capability import resolve_boundary

        request = placement_request()
        if not isinstance(request, Mapping):
            return {"text": "", "catalog": []}
        return resolve_boundary(dict(request))

    def snapshot_revision(self) -> str:
        boundary = self._current_boundary()
        signature = boundary["text"] + "\n" + _catalog_signature(boundary["catalog"])
        if not signature.strip():
            return ""
        return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]

    def citation_space(self) -> set[str] | None:
        return None

    def verdict_for(self, expectation: Mapping[str, Any]) -> CarrierVerdict | CarrierError:
        boundary = self._current_boundary()
        if not boundary["text"] and not boundary["catalog"]:
            return CarrierVerdict(
                CARRY_UNDECIDABLE,
                "未填写能力边界描述",
                gap_kind=GAP_UNGOVERNED,
                missing_material=(
                    "能力边界描述（请在资料管理页的 capability 预设中填写 boundary 字段）"
                ),
            )
        text = self._expectation_text(expectation)
        cache_key = hashlib.sha256(
            (text + "|" + boundary["text"] + "|" + _catalog_signature(boundary["catalog"]))
            .encode("utf-8")
        ).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]
        outcome = self._judge_with_retry(text, boundary)
        self._cache[cache_key] = outcome
        return outcome

    @staticmethod
    def _expectation_text(expectation: Mapping[str, Any]) -> str:
        parts = [
            str(expectation.get(key) or "")
            for key in ("expectation_id", "user_intent", "expected_outcome")
        ]
        criteria = expectation.get("acceptance_criteria")
        if isinstance(criteria, (list, tuple)):
            parts.extend(str(item) for item in criteria)
        elif criteria:
            parts.append(str(criteria))
        return " ".join(part for part in parts if part)

    def _judge_with_retry(
        self, expectation_text: str, boundary: Mapping[str, Any]
    ) -> CarrierVerdict | CarrierError:
        last_error = "LLM 输出无法解析为承载性判定"
        feedback = ""
        for attempt in range(self._retries):
            receipts: list[dict[str, Any]] = []
            try:
                result = self._call_llm(expectation_text, boundary, receipts, feedback)
            except Exception as exc:
                last_error = str(exc)
                self._wait(attempt)
                continue
            verdict = _parse_verdict(result)
            if verdict is None:
                last_error = "LLM 输出缺少必填字段或取值非法"
                self._wait(attempt)
                continue
            failures = _verify_citations(verdict, str(boundary.get("text") or ""))
            if failures:
                # 不放行假引用：带核验失败明细打回重试，重试耗尽落归位失败。
                last_error = "引用核验未通过：" + "；".join(failures)
                feedback = (
                    "上次输出的引用未通过机械核验：" + "；".join(failures)
                    + "。citations.note 必须逐字摘自 ref 所指位置的原文（可用 material_read 回读确认），"
                    "ref 必须原样复制工具返回的行区间 locator。"
                )
                self._wait(attempt)
                continue
            if receipts:
                verdict = replace(verdict, tool_trail=tuple(receipts))
            return verdict
        return CarrierError("text_carrier", "承载性判定重试耗尽", last_error)

    def _call_llm(
        self,
        expectation_text: str,
        boundary: Mapping[str, Any],
        receipts: list[dict[str, Any]],
        feedback: str = "",
    ) -> Mapping[str, Any]:
        if self._completer is not None:
            data = self._completer(expectation_text, boundary["text"])
            if not isinstance(data, Mapping):
                raise ValueError("completer must return a mapping")
            return data
        if self._spec is None:
            raise ValueError("TextCarrier 需要 spec 才能调 LLM")
        from impl.core.llm_client import project_llm_client
        from impl.projects.llm_probe.material_tools import build_material_tools

        catalog = list(boundary.get("catalog") or [])
        tools = build_material_tools(catalog, receipts)
        client = project_llm_client(
            self._spec,
            role="capability_carrier_mapper",
            tools=tools,
            tool_call_limit=_TOOL_CALL_LIMIT if tools else None,
        )
        system = _CARRIER_SYSTEM + (_CARRIER_TOOLS_GUIDE if tools else "")
        user = (
            f"未达成的期望：\n{expectation_text}\n\n"
            f"能力边界描述：\n{boundary['text']}"
            f"{_catalog_prompt(catalog)}"
        )
        if feedback:
            user += f"\n\n{feedback}"
        return client.complete_json(
            system,
            user,
            # 智能在外壳：骨架菜单 + 机械核验兜底，low 档起判（基线集验收）。
            reasoning_effort="low",
            output_spec=_verdict_output_spec(),
            stage="llm_probe_text_carrier",
        )

    def _wait(self, attempt: int) -> None:
        if attempt + 1 >= self._retries:
            return
        delay = self._backoff_schedule[min(attempt, len(self._backoff_schedule) - 1)]
        if delay > 0:
            time.sleep(delay)
