"""llm_probe 作为 G 的供给方（judge.md §5 / provider-contract §4.2）。

探针探测得到的能力断言带出处与信任档位入 G：
- provider 只交值不交结论——观察条目是"目标返回 4xx 明确拒绝"这类值，
  三态结论由 J 下，观察里出现结论键即拒；
- 出处回溯到具体一次探测（trace_id + 请求现场），档位缺省 current_behavior
 （探到的是当下行为），永不 normative_rule；
- 新鲜度定格于探测时刻，无治理 revision，过期即重探。

llm_probe 同时是一个被测项目（有自己的 d/e/g，judge.py/live.py 承担）；
两个身份互不混同——本模块只做供给方身份，不触碰其轴1判定。
"""
from __future__ import annotations

from typing import Any, Mapping

from impl.core.capability_carrier import (
    AXIS1_PAYLOAD_KEYS,
    PROBE_ALLOWED_TIERS,
    TIER_CURRENT_BEHAVIOR,
    VERDICT_PAYLOAD_KEYS,
    ProbeClaimsRejected,
    probe_provenance,
)

_STAMP_OVERRIDE_KEYS = ("trust_tier", "provenance", "source", "staleness")


def _probe_site(request: Mapping[str, Any] | None) -> str:
    req = request if isinstance(request, Mapping) else {}
    method = str(req.get("method") or "").strip().upper()
    url = str(req.get("url") or "").strip()
    return " ".join(part for part in (method, url) if part)


def probe_claims(
    observations: Mapping[str, Any],
    *,
    run_id: str,
    request: Mapping[str, Any] | None = None,
    probed_at: str = "",
) -> dict[str, dict[str, Any]]:
    """把一次探测的字段观察转成已戳记断言（字段名→断言）。

    observations 的每个条目是探测得到的能力值（operators / enums /
    is_supported / description 等），不是结论；本函数只负责戳记：
    provenance=该次探测，source/warrant=请求现场（担保链可回溯），
    trust_tier 缺省 current_behavior（声明 inlive_boundary 须自带登记
    warrant），staleness=探测时刻（缺省回落 run_id）。
    """
    if not isinstance(observations, Mapping):
        raise ProbeClaimsRejected("探针观察必须是 字段名→观察 的映射")
    provenance = probe_provenance(run_id)
    site = _probe_site(request)
    warrant = f"{provenance}@{site}" if site else provenance
    staleness = str(probed_at or "").strip() or str(run_id).strip()
    out: dict[str, dict[str, Any]] = {}
    for name, entry in observations.items():
        field = str(name).strip()
        if not field:
            raise ProbeClaimsRejected("探针观察含空字段名")
        if not isinstance(entry, Mapping):
            raise ProbeClaimsRejected(f"{field}: 探针观察条目必须是映射")
        hit = sorted({str(key) for key in entry} & (AXIS1_PAYLOAD_KEYS | VERDICT_PAYLOAD_KEYS))
        if hit:
            raise ProbeClaimsRejected(
                f"{field}: 探针观察携带期望/结论载荷键 {hit}；"
                "provider 只交值不交结论（judge.md §5 判别式）"
            )
        declared = str(entry.get("trust_tier") or "").strip()
        tier = declared or TIER_CURRENT_BEHAVIOR
        if tier not in PROBE_ALLOWED_TIERS:
            raise ProbeClaimsRejected(
                f"{field}: 探针证据档位只能是 {sorted(PROBE_ALLOWED_TIERS)}，"
                f"得到 {tier!r}（探到的是当下行为，永不 normative_rule）"
            )
        item = {key: value for key, value in entry.items() if key not in _STAMP_OVERRIDE_KEYS}
        if tier != TIER_CURRENT_BEHAVIOR and not str(item.get("warrant") or "").strip():
            raise ProbeClaimsRejected(
                f"{field}: {tier} 档需信任模型登记担保（warrant）；"
                "探针自身只担保到 current_behavior"
            )
        item.setdefault("warrant", warrant)
        item["trust_tier"] = tier
        item["provenance"] = provenance
        # 担保链引用（citations 的 source）指向担保材料：缺省即探测现场，
        # inlive_boundary 则指向其登记担保。
        item["source"] = str(item["warrant"])
        item["staleness"] = staleness
        out[field] = item
    return out


def probe_claims_from_trace(
    trace: Any,
    observations: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """从一次探针 RunTrace 取回溯戳记（trace_id / 请求现场 / 探测时刻）。"""
    payload = trace if isinstance(trace, Mapping) else vars(trace) if hasattr(trace, "__dict__") else {}
    request = payload.get("normalized_request")
    return probe_claims(
        observations,
        run_id=str(payload.get("trace_id") or "").strip(),
        request=request if isinstance(request, Mapping) else None,
        probed_at=str(payload.get("created_at") or "").strip(),
    )
