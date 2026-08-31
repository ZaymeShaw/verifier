"""Axis-2 capability carrier protocol: post-judge placement, never writes JudgeResult.

Form-agnostic contract. A project opts in with
`verifier.authority.enabled_scopes: [capability_carrier]` and a
`capability_provider(spec)` that returns a CapabilityCarrierBase.
The structured field/operator/value form lives in capability_structured.py.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping, Sequence
from typing import final as typing_final

from .authority_scopes import capability_carrier_enabled
from .protocol_base import check_forbidden_overrides

CARRY_YES = "yes"
CARRY_NO = "no"
CARRY_UNDECIDABLE = "undecidable"

PLACEMENT_CANNOT = "做不了"
PLACEMENT_WRONG = "做错了"
PLACEMENT_UNCLEAR = "说不清"

GAP_AMBIGUITY = "口径分歧"
GAP_UNGOVERNED = "空间未受治理"
GAP_TOOL = "工具失败"

RECOG_UNSUPPORTED = "unsupported"
RECOG_MISSING_VALUE = "missing_value"
RECOG_MISSING_OPERATOR = "missing_operator"
RECOG_UNMAPPED = "unmapped"
RECOG_BOUNDARY_STATEMENT = "boundary_statement"

# 信任档位（spec/math-abstract/judge.md §6）：档位随"谁担保/担保多强"定，
# 不由内容类型单独决定。定位序保留为典型担保强度的缺省映射。
TIER_NORMATIVE_RULE = "normative_rule"
TIER_EXTERNAL_FACT = "external_fact"
TIER_INLIVE_BOUNDARY = "inlive_boundary"
TIER_CURRENT_BEHAVIOR = "current_behavior"
TIER_CALLER_STATED = "caller_stated"

TRUST_TIERS = (
    TIER_NORMATIVE_RULE,
    TIER_EXTERNAL_FACT,
    TIER_INLIVE_BOUNDARY,
    TIER_CURRENT_BEHAVIOR,
    TIER_CALLER_STATED,
)
# 受治理 YAML 物料担保的断言的缺省档位（既有项目零迁移）。
DEFAULT_TRUST_TIER = TIER_NORMATIVE_RULE
# 担保缺失（w 偏关系暂缺）落低档，不硬拒（judge.md §3/§6）。
LOW_TRUST_TIER = TIER_CALLER_STATED

STAMP_KEYS = ("provenance", "trust_tier", "staleness")

CALLER_STATED_PROVENANCE = "caller_stated"

# 探针供给（judge.md §5：llm_probe 是 G 的供给方）。探到的是当下行为，
# 缺省 current_behavior；目标系统的明确边界声明经信任模型登记（带 warrant）
# 可作 inlive_boundary；探针证据永不 normative_rule / external_fact
#（provider-contract §4.2，防被测系统自述自我背书）。
PROBE_PROVENANCE_PREFIX = "llm_probe:"
PROBE_ALLOWED_TIERS = frozenset({TIER_CURRENT_BEHAVIOR, TIER_INLIVE_BOUNDARY})

# provider 只交值不交结论（judge.md §5 判别式）：断言载荷里出现三态/承载结论键
# 即冒充 J，拒绝入 G。
VERDICT_PAYLOAD_KEYS = frozenset({"placement", "carry"})

# e / 轴1 的载荷键：caller-stated 声明里出现任何一个即拒（judge.md §7.3——
# 调用方声明不得作为 e 的来源、不得给 C 的对账结果洗分；结构保证，非纪律要求）。
AXIS1_PAYLOAD_KEYS = frozenset({
    "business_expectations",
    "fulfillment_assessments",
    "overall_fulfillment",
    "expectations",
    "expectation_id",
    "acceptance_criteria",
    "expected_outcome",
    "user_intent",
})


class CapabilityCarrierNotBound(RuntimeError):
    """Scope is on but the project has not declared capability_provider."""


class CapabilityClaimsUnstamped(RuntimeError):
    """断言集戳记不完整或档位非法：装载期 fail-fast，不进判定。"""


class CallerStatedOverlayRejected(RuntimeError):
    """caller-stated 声明只准进 g/注意力：携带期望/轴1载荷或形状非法即拒。"""


class ProbeClaimsRejected(RuntimeError):
    """探针断言非法：档位越界（探针永不 normative_rule）、缺回溯出处、
    或携带期望/结论载荷（provider 只交值不交结论）。装载期 fail-fast。"""


def assertion_warrant(entry: Mapping[str, Any]) -> str:
    """担保 w：断言回溯到为它背书的材料（judge.md §3）。source 键即历史担保链，保留不删。"""
    return str(entry.get("warrant") or entry.get("source") or "").strip()


def assertion_tier(entry: Mapping[str, Any]) -> str:
    """档位随担保强度定：显式声明优先；有担保材料走缺省档，担保暂缺落低档。"""
    declared = str(entry.get("trust_tier") or "").strip()
    if declared:
        return declared
    return DEFAULT_TRUST_TIER if assertion_warrant(entry) else LOW_TRUST_TIER


def stamp_claims(
    snapshot: Mapping[str, Any],
    *,
    default_provenance: str = "capability_manifest",
) -> dict[str, Any]:
    """为快照断言补三件套缺省戳记（出处/信任档位/新鲜度）。

    既有 YAML 项目零迁移：source 即出处与担保，档位按担保强度走缺省映射，
    新鲜度定格到快照 revision。不改任何承载性语义字段。
    """
    out = dict(snapshot)
    fields = out.get("fields")
    if not isinstance(fields, Mapping):
        return out
    revision = str(out.get("revision") or "").strip() or snapshot_id(snapshot)[:16]
    stamped: dict[str, Any] = {}
    for name, entry in fields.items():
        if not isinstance(entry, Mapping):
            stamped[name] = entry
            continue
        item = dict(entry)
        if not str(item.get("provenance") or "").strip():
            item["provenance"] = assertion_warrant(entry) or default_provenance
        if not str(item.get("trust_tier") or "").strip():
            item["trust_tier"] = assertion_tier(entry)
        if not str(item.get("staleness") or "").strip():
            item["staleness"] = revision
        stamped[str(name)] = item
    out["fields"] = stamped
    out.setdefault("revision", revision)
    return out


def validate_claim_stamps(snapshot: Mapping[str, Any]) -> list[str]:
    """校验断言集是否可问责：每条断言必须带完整三件套且档位合法。"""
    fields = snapshot.get("fields") if isinstance(snapshot, Mapping) else None
    if not isinstance(fields, Mapping):
        return ["claims missing fields"]
    errors: list[str] = []
    for name, entry in fields.items():
        if not isinstance(entry, Mapping):
            errors.append(f"{name}: assertion is not a mapping")
            continue
        for key in STAMP_KEYS:
            if not str(entry.get(key) or "").strip():
                errors.append(f"{name}: missing {key}")
        tier = str(entry.get("trust_tier") or "").strip()
        if tier and tier not in TRUST_TIERS:
            errors.append(f"{name}: unknown trust_tier {tier}")
    return errors


def require_stamped_claims(snapshot: Mapping[str, Any], *, owner: str = "") -> None:
    errors = validate_claim_stamps(snapshot)
    if errors:
        raise CapabilityClaimsUnstamped(
            f"{owner or '<claims>'} 断言戳记不完整（出处/信任档位/新鲜度）："
            + "; ".join(errors[:8])
        )


def caller_stated_provenance(caller: str = "") -> str:
    name = str(caller or "").strip()
    return f"{CALLER_STATED_PROVENANCE}:{name}" if name else CALLER_STATED_PROVENANCE


def _reject_axis1_payload(keys: Iterable[Any], owner: str) -> None:
    hit = sorted({str(key) for key in keys} & AXIS1_PAYLOAD_KEYS)
    if hit:
        raise CallerStatedOverlayRejected(
            f"{owner}：caller-stated 声明携带期望/轴1载荷键 {hit}；"
            "调用方声明只进 g/注意力，不得作为 e 的来源（judge.md §7.3）"
        )


def probe_provenance(run_id: str) -> str:
    """探针断言的出处：可回溯到具体一次探测（provider-contract §4.2）。"""
    run = str(run_id or "").strip()
    if not run:
        raise ProbeClaimsRejected("探针断言必须可回溯到具体探测：缺 run_id")
    return f"{PROBE_PROVENANCE_PREFIX}{run}"


def _require_probe_entry(field: str, entry: Mapping[str, Any]) -> None:
    keys = {str(key) for key in entry.keys()}
    hit = sorted(keys & (AXIS1_PAYLOAD_KEYS | VERDICT_PAYLOAD_KEYS))
    if hit:
        raise ProbeClaimsRejected(
            f"{field}: 探针断言携带期望/结论载荷键 {hit}；"
            "provider 只交值不交结论（judge.md §5 判别式）"
        )
    provenance = str(entry.get("provenance") or "").strip()
    if not provenance.startswith(PROBE_PROVENANCE_PREFIX):
        raise ProbeClaimsRejected(
            f"{field}: 探针断言出处必须回溯到探测运行"
            f"（{PROBE_PROVENANCE_PREFIX}<run>），得到 {provenance!r}"
        )
    tier = str(entry.get("trust_tier") or "").strip()
    if tier not in PROBE_ALLOWED_TIERS:
        raise ProbeClaimsRejected(
            f"{field}: 探针证据档位只能是 {sorted(PROBE_ALLOWED_TIERS)}，"
            f"得到 {tier!r}（探到的是当下行为，永不 normative_rule）"
        )
    if tier == TIER_INLIVE_BOUNDARY and not str(entry.get("warrant") or "").strip():
        raise ProbeClaimsRejected(
            f"{field}: inlive_boundary 档需信任模型登记担保（warrant）；"
            "探针自身只担保到 current_behavior"
        )
    if not str(entry.get("staleness") or "").strip():
        raise ProbeClaimsRejected(
            f"{field}: 探针断言缺 staleness（定格于探测时刻，过期重探）"
        )


def overlay_probe_claims(
    snapshot: Mapping[str, Any],
    probe_claims: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """探针供给入 G（judge.md §5）：叠加已戳记的探针断言，不覆盖既有断言。

    - 每条探针断言必须完整戳记且出处回溯到探测运行；档位只允许
      current_behavior / inlive_boundary（后者需登记担保）；
    - 只叠加不覆盖：G 已有同名断言按原样保留（字节不变），探针结果降级为
      注意力提示——受治理断言的改写走治理，不走探针旁路；
    - 不进 e / 轴1：断言携带期望/结论载荷键即拒（结构保证）。
    """
    fields = snapshot.get("fields") if isinstance(snapshot, Mapping) else None
    if not isinstance(fields, Mapping):
        raise ProbeClaimsRejected(
            "探针断言是 G 的叠加层：能力空间快照不可用时无叠加对象；"
            "探针独立构成 G 走 carrier_from_claims 的恒等路径"
        )
    if probe_claims is not None and not isinstance(probe_claims, Mapping):
        raise ProbeClaimsRejected("探针断言必须是 字段名→断言 的映射")
    declared = probe_claims or {}

    out = dict(snapshot)
    merged = dict(fields)
    notes = [dict(item) for item in (out.get("attention") or []) if isinstance(item, Mapping)]

    for name, entry in declared.items():
        field = str(name)
        if not isinstance(entry, Mapping):
            raise ProbeClaimsRejected(f"{field}: 探针断言条目必须是断言映射")
        _require_probe_entry(field, entry)
        if field in merged:
            # 已有断言不覆盖：探针差异降级为注意力提示，改写走治理。
            note_text = str(entry.get("note") or entry.get("description") or "").strip()
            notes.append({
                "field": field,
                "tier": str(entry.get("trust_tier")),
                "provenance": str(entry.get("provenance")),
                "note": note_text or "探针结果与既有断言同名：未覆盖，仅注意力提示",
            })
            continue
        merged[field] = dict(entry)

    out["fields"] = merged
    out.setdefault("revision", str(out.get("revision") or "").strip() or snapshot_id(snapshot)[:16])
    if notes:
        out["attention"] = notes
    return out


def overlay_caller_stated(
    snapshot: Mapping[str, Any],
    declarations: Mapping[str, Any] | None = None,
    *,
    caller: str = "",
    attention: Sequence[str] = (),
) -> dict[str, Any]:
    """caller-stated 叠加层（judge.md §5/§7.3）：调用方声明只进 g / 注意力。

    - 只落最低信任档：声明的 trust_tier / warrant / source / provenance 一律
      改写为 caller_stated——调用方不能自我担保出更高档位（防循环格挡，§7.4）；
    - 只叠加不覆盖：G 已有的断言按原样保留（字节不变），同名声明降级为
      注意力提示，不得改写既有档位、operators、is_supported 等任何承载语义；
    - 不进 e / 轴1：声明或其条目携带期望/轴1载荷键即拒（结构保证）。
    """
    fields = snapshot.get("fields") if isinstance(snapshot, Mapping) else None
    if not isinstance(fields, Mapping):
        raise CallerStatedOverlayRejected(
            "caller-stated 是 G 的叠加层：能力空间快照不可用时无叠加对象，"
            "不得由调用方声明凭空构成 G"
        )
    declared = declarations if isinstance(declarations, Mapping) else {}
    if declarations is not None and not isinstance(declarations, Mapping):
        raise CallerStatedOverlayRejected("caller-stated 声明必须是 字段名→断言 的映射")
    _reject_axis1_payload(declared.keys(), "<declarations>")

    out = dict(snapshot)
    merged = dict(fields)
    revision = str(out.get("revision") or "").strip() or snapshot_id(snapshot)[:16]
    provenance = caller_stated_provenance(caller)
    notes = [dict(item) for item in (out.get("attention") or []) if isinstance(item, Mapping)]

    for name, entry in declared.items():
        field = str(name)
        if not isinstance(entry, Mapping):
            raise CallerStatedOverlayRejected(
                f"{field}: caller-stated 声明条目必须是断言映射"
            )
        _reject_axis1_payload(entry.keys(), field)
        note_text = str(entry.get("note") or entry.get("description") or "").strip()
        if field in merged:
            # 已有断言不覆盖：同名声明降级为注意力提示（§7.3 的第二用途）。
            notes.append({
                "field": field,
                "tier": TIER_CALLER_STATED,
                "provenance": provenance,
                "note": note_text or "调用方声明与既有断言同名：未覆盖，仅注意力提示",
            })
            continue
        item = {
            key: value
            for key, value in entry.items()
            if key not in ("trust_tier", "provenance", "warrant", "source")
        }
        item["trust_tier"] = TIER_CALLER_STATED
        item["provenance"] = provenance
        item["source"] = provenance
        if not str(item.get("staleness") or "").strip():
            item["staleness"] = revision
        merged[field] = item

    for text in attention:
        note = str(text or "").strip()
        if not note:
            continue
        notes.append({
            "field": "",
            "tier": TIER_CALLER_STATED,
            "provenance": provenance,
            "note": note,
        })

    out["fields"] = merged
    out.setdefault("revision", revision)
    if notes:
        out["attention"] = notes
    return out


@dataclass(frozen=True)
class CarrierError:
    stage: str
    reason: str
    last_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "reason": self.reason,
            "last_error": self.last_error,
        }


@dataclass(frozen=True)
class CarrierVerdict:
    carry: str
    reason: str
    gap_kind: str = ""
    missing_material: str = ""
    citations: tuple[Mapping[str, str], ...] = ()
    recognition: str = ""
    # 检索式消费的审计轨迹：判定期间的工具调用（tool/arguments/result 摘要）。
    tool_trail: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "carry": self.carry,
            "reason": self.reason,
            "citations": [dict(item) for item in self.citations],
        }
        if self.gap_kind:
            payload["gap_kind"] = self.gap_kind
        if self.missing_material:
            payload["missing_material"] = self.missing_material
        if self.recognition:
            payload["recognition"] = self.recognition
        if self.tool_trail:
            payload["tool_trail"] = [dict(item) for item in self.tool_trail]
        return payload


def snapshot_id(snapshot: Mapping[str, Any]) -> str:
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def map_placement(axis1_status: str, verdict: CarrierVerdict) -> dict[str, Any] | None:
    if str(axis1_status or "").strip().lower() != "not_fulfilled":
        return None
    if verdict.carry == CARRY_NO:
        placement = PLACEMENT_CANNOT
    elif verdict.carry == CARRY_YES:
        placement = PLACEMENT_WRONG
    elif verdict.gap_kind == GAP_TOOL:
        raise ValueError("工具失败不得落说不清，必须升为归位失败")
    else:
        placement = PLACEMENT_UNCLEAR
    payload = {
        "placement": placement,
        **verdict.as_dict(),
    }
    if placement == PLACEMENT_UNCLEAR and not payload.get("gap_kind"):
        raise ValueError("说不清 must include gap_kind")
    if placement == PLACEMENT_UNCLEAR and not payload.get("missing_material"):
        raise ValueError("说不清 must include missing_material")
    if not payload.get("citations") and placement != PLACEMENT_UNCLEAR:
        raise ValueError("归位结论必须带资料引用")
    return payload


class CapabilityCarrierBase(ABC):
    """Protocol-owned carrier. Forms implement verdict_for; place is final."""

    _FORBIDDEN_OVERRIDES = frozenset({"place"})

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    @abstractmethod
    def verdict_for(self, expectation: Mapping[str, Any]) -> CarrierVerdict | CarrierError:
        raise NotImplementedError

    @abstractmethod
    def snapshot_revision(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def citation_space(self) -> set[str] | None:
        raise NotImplementedError

    @typing_final
    def place(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        return place_not_fulfilled_payload(payload, cache=self)


def _project_id(spec: Any) -> str:
    return str(getattr(spec, "project_id", "") or "").strip()


def resolve_capability_provider(spec: Any):
    """g-provider 的显式装载合同（judge.md §8：不再是散落的 getattr 约定）。

    装载期 fail-fast，四种失败各有其名，不互相伪装：
    - spec 缺 project_id / live 模块不存在 / 模块未声明 capability_provider /
      声明不可调用 → CapabilityCarrierNotBound（接入未完成）；
    - live 模块存在但装载崩溃（依赖缺失、语法错误）→ 原始异常原样上抛
      （装载期失败，judge.md §7.7：不得伪装成"缺 capability_provider"）。
    """
    project_id = _project_id(spec)
    if not project_id:
        raise CapabilityCarrierNotBound(
            "轴2接入未完成：spec 缺 project_id，无法定位 capability_provider"
        )
    module_name = f"impl.projects.{project_id}.live"
    try:
        found = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        found = None  # 父包都不存在，同样是声明缺失
    if found is None:
        raise CapabilityCarrierNotBound(
            f"轴2接入未完成：{project_id} 缺 capability_provider"
            f"（模块 {module_name} 不存在）"
        )
    module = importlib.import_module(module_name)
    provider = getattr(module, "capability_provider", None)
    if provider is None:
        raise CapabilityCarrierNotBound(
            f"轴2接入未完成：{project_id} 的 {module_name} 未声明 capability_provider"
        )
    if not callable(provider):
        raise CapabilityCarrierNotBound(
            f"轴2接入未完成：{project_id} 的 capability_provider 不可调用"
            f"（{type(provider).__name__}）"
        )
    return provider


def bind_capability_carrier(spec: Any, *, shared: bool = False) -> CapabilityCarrierBase | None:
    if not capability_carrier_enabled(spec):
        return None
    provider = resolve_capability_provider(spec)
    project_id = _project_id(spec)
    if not shared:
        return _instantiate_provider(provider, spec, project_id)
    with _LIVE_LOCK:
        existing = _LIVE_CARRIERS.get(project_id)
        if existing is not None:
            return existing
        bound = _instantiate_provider(provider, spec, project_id)
        if project_id:
            _LIVE_CARRIERS[project_id] = bound
        return bound


def _instantiate_provider(provider, spec: Any, project_id: str) -> CapabilityCarrierBase:
    carrier = provider(spec)
    if isinstance(carrier, CapabilityCarrierBase):
        return carrier
    if isinstance(carrier, Mapping):
        return carrier_from_claims(carrier, spec=spec, owner=project_id)
    raise CapabilityCarrierNotBound(
        f"轴2接入未完成：{project_id or '<unknown>'} capability_provider "
        "未返回 CapabilityCarrierBase 或已戳记断言集"
    )


def carrier_from_claims(
    claims: Mapping[str, Any],
    *,
    spec: Any = None,
    owner: str = "",
    probe_claims: Mapping[str, Any] | None = None,
    caller_stated: Mapping[str, Any] | None = None,
    caller: str = "",
    attention: Sequence[str] = (),
) -> CapabilityCarrierBase:
    """g 的恒等下界（judge.md §4）：项目已持有戳记完整的 G 时，校验后恒等交出。

    这里不补缺省戳记——最低要求是可问责的 G 本身，缺三件套在装载期 fail-fast。
    需要缺省映射的供给方走 StructuredCarrier.from_materials（YAML 装载路径）。
    probe_claims 是探针供给（judge.md §5：llm_probe 是 G 的供给方），
    先于 caller-stated 叠加：探针档位（current_behavior）高于调用方声明档。
    caller_stated / attention 是调用方声明的低档叠加层（judge.md §7.3）。
    两路叠加都只叠加不覆盖既有断言。
    """
    snapshot = dict(claims) if "fields" in claims else {"fields": dict(claims)}
    require_stamped_claims(snapshot, owner=owner)
    if probe_claims:
        snapshot = overlay_probe_claims(snapshot, probe_claims)
        require_stamped_claims(snapshot, owner=owner)
    if caller_stated or attention:
        snapshot = overlay_caller_stated(
            snapshot, caller_stated, caller=caller or owner, attention=attention,
        )
        require_stamped_claims(snapshot, owner=owner)
    from .capability_structured import StructuredCarrier

    return StructuredCarrier(snapshot, spec=spec)


_LIVE_CARRIERS: dict[str, CapabilityCarrierBase] = {}
_LIVE_LOCK = threading.Lock()


def reset_live_carriers() -> None:
    with _LIVE_LOCK:
        _LIVE_CARRIERS.clear()


def _expectation_status(
    expectation_id: str,
    assessments: Iterable[Mapping[str, Any]],
) -> str:
    for item in assessments:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("expectation_id") or "") == expectation_id:
            return str(item.get("status") or "").strip().lower()
    return ""


def place_not_fulfilled_payload(
    payload: Mapping[str, Any] | None,
    *,
    cache: CapabilityCarrierBase,
) -> dict[str, Any]:
    data = payload if isinstance(payload, Mapping) else {}
    overall = data.get("overall_fulfillment") or {}
    axis1 = ""
    if isinstance(overall, Mapping):
        axis1 = str(overall.get("status") or "").strip().lower()
    result = {
        "applicable": axis1 == "not_fulfilled",
        "axis1_status": axis1,
        "placements": [],
        "errors": [],
        "snapshot_id": cache.snapshot_revision(),
    }
    if axis1 != "not_fulfilled":
        return result
    assessments = [
        item for item in (data.get("fulfillment_assessments") or []) if isinstance(item, Mapping)
    ]
    for expectation in data.get("business_expectations") or []:
        if not isinstance(expectation, Mapping):
            continue
        if expectation.get("blocking") is False:
            continue
        expectation_id = str(expectation.get("expectation_id") or "")
        if _expectation_status(expectation_id, assessments) != "not_fulfilled":
            continue
        outcome = cache.verdict_for(expectation)
        if isinstance(outcome, CarrierError):
            result["errors"].append({
                "expectation_id": expectation_id,
                **outcome.as_dict(),
            })
            continue
        placement = map_placement("not_fulfilled", outcome)
        if placement is None:
            continue
        result["placements"].append({
            "expectation_id": expectation_id,
            **placement,
        })
    return result


def attach_row_placements(
    spec: Any,
    row: dict[str, Any],
    *,
    carrier: CapabilityCarrierBase | None = None,
) -> dict[str, Any]:
    """Write capability_carrier onto the row. Never mutates side payloads."""
    if not capability_carrier_enabled(spec):
        return row
    bound = carrier if carrier is not None else bind_capability_carrier(spec)
    if bound is None:
        raise CapabilityCarrierNotBound(
            f"轴2接入未完成：{_project_id(spec) or '<unknown>'} 缺 capability_provider"
        )
    axis1_before = {
        side: ((row.get(side) or {}).get("overall_fulfillment") or {}).get("status")
        if isinstance(row.get(side), Mapping)
        else None
        for side in ("current", "draft")
    }
    row["capability_carrier"] = {
        "current": bound.place(row.get("current")),
        "draft": bound.place(row.get("draft")),
    }
    axis1_after = {
        side: ((row.get(side) or {}).get("overall_fulfillment") or {}).get("status")
        if isinstance(row.get(side), Mapping)
        else None
        for side in ("current", "draft")
    }
    if axis1_before != axis1_after:
        raise RuntimeError("capability_carrier must not rewrite axis-1 JudgeResult")
    return row


_CANNOT_RECOGNITIONS = {
    RECOG_UNSUPPORTED,
    RECOG_MISSING_VALUE,
    RECOG_MISSING_OPERATOR,
    RECOG_UNMAPPED,
    RECOG_BOUNDARY_STATEMENT,
}


def validate_placements(
    row: Mapping[str, Any],
    citation_space: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    block = row.get("capability_carrier")
    if not isinstance(block, Mapping):
        return ["missing capability_carrier"]
    catalog = citation_space
    seen: dict[str, str] = {}
    for side in ("current", "draft"):
        payload = row.get(side) if isinstance(row.get(side), Mapping) else {}
        report = block.get(side) if isinstance(block.get(side), Mapping) else {}
        overall = ((payload or {}).get("overall_fulfillment") or {})
        axis1 = str(overall.get("status") or "").strip().lower() if isinstance(overall, Mapping) else ""
        if axis1 != "not_fulfilled":
            continue
        assessments = {
            str(item.get("expectation_id") or ""): str(item.get("status") or "").strip().lower()
            for item in (payload.get("fulfillment_assessments") or [])
            if isinstance(item, Mapping)
        }
        blocking_nf = []
        for expectation in payload.get("business_expectations") or []:
            if not isinstance(expectation, Mapping) or expectation.get("blocking") is False:
                continue
            expectation_id = str(expectation.get("expectation_id") or "")
            if assessments.get(expectation_id) == "not_fulfilled":
                blocking_nf.append(expectation_id)
        placed = {
            str(item.get("expectation_id") or "")
            for item in (report.get("placements") or [])
            if isinstance(item, Mapping)
        }
        failed = {
            str(item.get("expectation_id") or "")
            for item in (report.get("errors") or [])
            if isinstance(item, Mapping)
        }
        for expectation_id in blocking_nf:
            if expectation_id not in placed and expectation_id not in failed:
                errors.append(f"{side}:{expectation_id} missing placement")
        for item in report.get("placements") or []:
            if not isinstance(item, Mapping):
                continue
            label = f"{side}:{item.get('expectation_id')}"
            placement = item.get("placement")
            if item.get("gap_kind") == GAP_TOOL:
                errors.append(f"{label} 说不清 must not use 工具失败")
            if placement == PLACEMENT_UNCLEAR:
                if not item.get("gap_kind") or not item.get("missing_material"):
                    errors.append(f"{label} 说不清 missing gap/material")
            elif not item.get("citations"):
                errors.append(f"{label} missing citations")
            if placement not in {PLACEMENT_CANNOT, PLACEMENT_WRONG, PLACEMENT_UNCLEAR}:
                errors.append(f"{label} invalid placement")
            if placement == PLACEMENT_CANNOT and item.get("recognition") not in _CANNOT_RECOGNITIONS:
                errors.append(f"{label} 做不了 missing self-recognition")
            if catalog is not None:
                for cite in item.get("citations") or []:
                    if not isinstance(cite, Mapping):
                        continue
                    ref = str(cite.get("ref") or "")
                    if ref and ref != "fields" and ref not in catalog:
                        errors.append(f"{label} citation field {ref} not in catalog")
            reading_key = json.dumps(
                sorted(
                    str(cite.get("ref") or "")
                    for cite in (item.get("citations") or [])
                    if isinstance(cite, Mapping) and cite.get("ref") not in {None, "", "fields"}
                ),
                ensure_ascii=False,
            )
            if reading_key != "[]":
                previous = seen.get(reading_key)
                if previous and previous != placement:
                    errors.append(f"{label} same-dimension placement drifted {previous}->{placement}")
                seen[reading_key] = str(placement or "")
    return errors


def inbox_entries(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        case_key = row.get("case_key")
        block = row.get("capability_carrier") or {}
        if not isinstance(block, Mapping):
            continue
        for side in ("current", "draft"):
            report = block.get(side) or {}
            if not isinstance(report, Mapping):
                continue
            for item in report.get("placements") or []:
                if not isinstance(item, Mapping):
                    continue
                if item.get("placement") not in {PLACEMENT_CANNOT, PLACEMENT_UNCLEAR}:
                    continue
                entries.append({
                    "case_key": case_key,
                    "side": side,
                    "expectation_id": item.get("expectation_id"),
                    "placement": item.get("placement"),
                    "gap_kind": item.get("gap_kind") or "",
                    "missing_material": item.get("missing_material") or "",
                    "citations": item.get("citations") or [],
                    "inbox": (
                        "归属待拍板" if item.get("placement") == PLACEMENT_CANNOT else "缺料"
                    ),
                })
    return entries


def render_inbox(entries: Sequence[Mapping[str, Any]]) -> str:
    lines = ["# 承载性收件箱", ""]
    if not entries:
        lines.append("本轮无 NF×做不了 / 说不清 条目。")
        return "\n".join(lines) + "\n"
    lines.append("| case | side | expectation | 归位 | 收件 | 差在哪儿 | 缺料 |")
    lines.append("|---|---|---|---|---|---|---|")
    for item in entries:
        lines.append(
            "| {case_key} | {side} | {expectation_id} | {placement} | {inbox} | {gap_kind} | {missing_material} |".format(
                **{key: item.get(key) or "-" for key in (
                    "case_key", "side", "expectation_id", "placement",
                    "inbox", "gap_kind", "missing_material",
                )}
            )
        )
    lines.append("")
    lines.append("不自动打回 Investigate。人拍板产生的声明走 Investigate 进资料空间。")
    return "\n".join(lines) + "\n"


def format_placement_cell(report: Mapping[str, Any] | None) -> str:
    if not isinstance(report, Mapping):
        return "-"
    if report.get("applicable") is False:
        return "-"
    parts = []
    for item in report.get("placements") or []:
        if not isinstance(item, Mapping):
            continue
        piece = f"{item.get('expectation_id')}:{item.get('placement')}"
        if item.get("gap_kind"):
            piece += f"/{item['gap_kind']}"
        parts.append(piece)
    return "；".join(parts) if parts else "-"


def _material_citation_refs(item: Mapping[str, Any]) -> str:
    """资料引用回指（仅 material:// 来源；boundary/快照字段引用不进表格单元）。"""
    refs = []
    for cite in item.get("citations") or []:
        if not isinstance(cite, Mapping):
            continue
        source = str(cite.get("source") or "")
        if not source.startswith("material://"):
            continue
        ref = str(cite.get("ref") or "").strip()
        refs.append(f"{source}#{ref}" if ref and ref != "boundary" else source)
    return "、".join(dict.fromkeys(refs))


def _placement_cell(item: Mapping[str, Any]) -> str:
    label = str(item.get("expectation_id") or "").strip()
    extra = str(item.get("reason") or "").strip()
    missing = str(item.get("missing_material") or "").strip()
    if missing:
        extra = f"{extra}；缺{missing}".strip("；")
    citations = _material_citation_refs(item)
    if citations:
        extra = f"{extra}；引 {citations}".strip("；")
    if extra:
        return f"{label}（{extra}）" if label else extra
    return label


def carrier_text(report: Mapping[str, Any] | None) -> str:
    """One column: $做不了 / $做错了 / $说不清 sections. Empty sections omitted."""
    if not isinstance(report, Mapping):
        return ""
    if "placements" not in report and isinstance(report.get("current"), Mapping):
        report = report.get("current") or {}
    if report.get("applicable") is False:
        return ""
    buckets = {PLACEMENT_CANNOT: [], PLACEMENT_WRONG: [], PLACEMENT_UNCLEAR: []}
    for item in report.get("placements") or []:
        if not isinstance(item, Mapping):
            continue
        placement = item.get("placement")
        if placement not in buckets:
            continue
        text = _placement_cell(item)
        if text:
            buckets[placement].append(text)
    blocks = []
    for label in (PLACEMENT_CANNOT, PLACEMENT_WRONG, PLACEMENT_UNCLEAR):
        if not buckets[label]:
            continue
        blocks.append("$" + label + "\n" + "\n".join(buckets[label]))
    failures = []
    for item in report.get("errors") or []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("expectation_id") or "").strip()
        reason = str(item.get("reason") or "归位失败").strip()
        detail = str(item.get("last_error") or "").strip()
        text = f"{label}（{reason}）" if label else reason
        if detail:
            text += f"：{detail}"
        failures.append(text)
    if failures:
        blocks.append("$归位失败\n" + "\n".join(failures))
    return "\n\n".join(blocks)


def collect_report_errors(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Collect placement failures from a side report, row, or loop report."""
    found: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        return found
    errors = payload.get("errors")
    if isinstance(errors, list) and "placements" in payload:
        for item in errors:
            if isinstance(item, Mapping):
                found.append(dict(item))
    block = payload.get("capability_carrier")
    if isinstance(block, Mapping):
        if "placements" in block:
            found.extend(collect_report_errors(block))
        for side in ("current", "draft"):
            found.extend(collect_report_errors(block.get(side) if isinstance(block.get(side), Mapping) else None))
    for row in payload.get("rows") or []:
        if isinstance(row, Mapping):
            found.extend(collect_report_errors(row))
    return found


def format_carrier_errors(errors: Sequence[Mapping[str, Any]]) -> str:
    parts = []
    for item in errors:
        expectation_id = str(item.get("expectation_id") or "").strip()
        stage = str(item.get("stage") or "").strip()
        reason = str(item.get("reason") or "归位失败").strip()
        detail = str(item.get("last_error") or "").strip()
        label = f"{expectation_id} " if expectation_id else ""
        piece = f"{label}{reason}"
        if stage:
            piece += f" [{stage}]"
        if detail:
            piece += f": {detail}"
        parts.append(piece)
    return "; ".join(parts) if parts else "capability_carrier 归位失败"


_placement_request: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "capability_carrier_request", default=None,
)


def placement_request() -> Mapping[str, Any] | None:
    """本次归位所属的 live request。文本形态据此取本 case 的能力边界。"""
    return _placement_request.get()


@contextmanager
def using_placement_request(request: Mapping[str, Any] | None) -> Iterator[None]:
    token = _placement_request.set(request)
    try:
        yield
    finally:
        _placement_request.reset(token)


def live_carrier_report(
    spec: Any,
    judge: Any,
    *,
    carrier: CapabilityCarrierBase | None = None,
    request: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    bound = carrier or bind_capability_carrier(spec, shared=True)
    if bound is None or judge is None:
        return None
    from .schema import to_dict
    payload = judge if isinstance(judge, Mapping) else to_dict(judge)
    with using_placement_request(request):
        return bound.place(payload)
