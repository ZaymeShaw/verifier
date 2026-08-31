"""enhanced_rules key-index 资产（P4 落地）。

761 条增强规则按 field 切成 106 个可寻址条目；Judge 按 trace 涉及的字段
按键命中（key_live），不再把全量 40 万字符或截断清单注入上下文。

对应 spec/grill/staleness_public_facility.md §3.8：大材料必须检索化。
key_live 是 g-provider 合同（spec/math-abstract/provider-contract.md §4.1）
的实例：Judge 侧经 provide_enhanced_rules_for_fields 消费五项输出，
不再直接触碰检索函数。
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from impl.core.project_loader import load_project
from impl.core.provider_contract import (
    LANE_G,
    TRUST_NORMATIVE_RULE,
    ProviderDeclaration,
    ProvidedValue,
)

_RETRIEVE_LIMIT = 20

ENHANCED_RULES_PROVIDER_ID = "client_search.enhanced_rules.key_live"


@lru_cache(maxsize=8)
def _enhanced_rules_source_path(spec_id: str) -> Path:
    spec = load_project(spec_id)
    return Path(spec.source_path("enhanced_rules"))


@lru_cache(maxsize=8)
def _load_enhanced_rules_document(spec_id: str) -> Mapping[str, Any]:
    path = _enhanced_rules_source_path(spec_id)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _enhanced_rules_source_sha256(spec_id: str) -> str:
    path = _enhanced_rules_source_path(spec_id)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_enhanced_rules_key_index(spec_id: str = "client_search") -> dict[str, list[dict[str, Any]]]:
    """field -> 该字段的规则列表（稳定按键，runtime 拿新的就是）。"""
    doc = _load_enhanced_rules_document(spec_id)
    index: dict[str, list[dict[str, Any]]] = {}
    for rule in doc.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        field = str(rule.get("field") or "").strip()
        if not field:
            continue
        index.setdefault(field, []).append(rule)
    return index


def retrieve_enhanced_rules_for_fields(
    fields: Iterable[str],
    spec_id: str = "client_search",
    limit: int = _RETRIEVE_LIMIT,
) -> dict[str, Any]:
    """按键命中：返回 trace 涉及字段的规则定位键（不是 operator/pattern 正文）。

    merge_to_llm=false 的生成配方不注入。rules 仅含 name/field 定位键；
    negation_words 总是携带（共享小词表）。
    """
    index = build_enhanced_rules_key_index(spec_id)
    wanted = {str(field).strip() for field in fields if str(field).strip()}
    rules: list[dict[str, Any]] = []
    for field in sorted(wanted):
        for rule in index.get(field) or []:
            if not isinstance(rule, dict):
                continue
            if rule.get("merge_to_llm") is False:
                continue
            locator = {
                key: rule[key]
                for key in ("name", "field")
                if key in rule and str(rule.get(key) or "").strip()
            }
            if locator:
                rules.append(locator)
    compact: dict[str, Any] = {}
    if rules:
        compact["rules"] = rules[:limit]
    doc = _load_enhanced_rules_document(spec_id)
    negation = doc.get("negation_words")
    if isinstance(negation, list):
        compact["negation_words"] = negation
    return compact


def enhanced_rules_provider_declaration(
    spec_id: str = "client_search",
) -> ProviderDeclaration:
    """装载期声明（provider-contract.md §2.1 / §4.1）。

    引用空间 = key-index 的稳定 key 集合（field 名 + 规则定位键 name）。
    装载失败（源文件缺失/解析异常）在此即上抛：接入未完成，fail-fast。
    """
    index = build_enhanced_rules_key_index(spec_id)
    space: set[str] = set()
    for field, rules in index.items():
        space.add(field)
        for rule in rules:
            name = str(rule.get("name") or "").strip()
            if name:
                space.add(name)
    return ProviderDeclaration(
        provider_id=ENHANCED_RULES_PROVIDER_ID,
        lane=LANE_G,
        citation_space=frozenset(space),
        failure_semantics={
            "load": "源文件装载失败 / index 构建异常 → 装载期 error，fail-fast，run 不启动",
            "runtime": "检索设施故障 → 运行期 error，fail-closed，不得伪装成「说不清」",
            "value_missing": "field 在索引中无条目 → 合法的「缺维度」证据，正常入料，不是失败",
        },
    )


def provide_enhanced_rules_for_fields(
    fields: Iterable[str],
    spec_id: str = "client_search",
    limit: int = _RETRIEVE_LIMIT,
) -> ProvidedValue:
    """运行期输出（provider-contract.md §2.2 / §4.1）：值 + 三件套 + 锚点。

    value 与 retrieve_enhanced_rules_for_fields 逐字节一致（零行为漂移）；
    合同元数据只随值携带，不改变 Judge prompt 注入内容。
    """
    wanted = sorted({str(field).strip() for field in fields if str(field).strip()})
    value = retrieve_enhanced_rules_for_fields(wanted, spec_id=spec_id, limit=limit)
    anchors: set[str] = set()
    for rule in value.get("rules") or []:
        for key in ("field", "name"):
            anchor = str(rule.get(key) or "").strip()
            if anchor:
                anchors.add(anchor)
    return ProvidedValue(
        value=value,
        provenance={
            "source": "project.yaml:enhanced_rules（受治理源 YAML）",
            "source_path": str(_enhanced_rules_source_path(spec_id)),
            "key_index": "impl/projects/client_search/enhanced_rules_key_index.py",
            "requested_fields": wanted,
        },
        trust_tier=TRUST_NORMATIVE_RULE,
        staleness={
            "consumption_mode": "key_live",
            "source_sha256": _enhanced_rules_source_sha256(spec_id),
            "drift_policy": "重钉 hash + 审计，不阻断不重查（staleness_public_facility.md）",
        },
        citation_anchors=tuple(sorted(anchors)),
    )
