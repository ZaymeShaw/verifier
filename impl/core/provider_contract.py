"""d/e/g provider 接入合同的最小代码形状（spec/math-abstract/provider-contract.md）。

只固化合同的两个可校验面：

- 装载期声明（§2.1）：供哪一路、引用空间、失败面。缺一即接入未完成，
  构造时 fail-fast（ProviderContractError）。
- 运行期输出（§2.2）：value + 三件套（provenance / trust tier / staleness）
  + citation 锚点。J 只消费这五项，不关心值怎么来的。

失败语义（§3）的三态互斥由 provider 实现处遵守：装载失败/设施故障上抛为
error（fail-closed），"资料里没有"是合法的值缺失输出，不进本模块。
本模块不承载任何判定逻辑，也不认识具体项目。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .capability_carrier import (
    TIER_CALLER_STATED,
    TIER_CURRENT_BEHAVIOR,
    TIER_EXTERNAL_FACT,
    TIER_INLIVE_BOUNDARY,
    TIER_NORMATIVE_RULE,
    TRUST_TIERS,
)

LANE_D = "d"
LANE_E = "e"
LANE_G = "g"
_LANES = frozenset({LANE_D, LANE_E, LANE_G})

# 档位常量的单一真相源在 capability_carrier（judge.md §6：档位随担保强度定）。
# 此处仅做别名再导出，避免两套常量各自漂移；caller_stated 是合法低档
#（judge.md §7.3：caller-stated 是 G 的低信任叠加层供给方）。
TRUST_NORMATIVE_RULE = TIER_NORMATIVE_RULE
TRUST_EXTERNAL_FACT = TIER_EXTERNAL_FACT
TRUST_INLIVE_BOUNDARY = TIER_INLIVE_BOUNDARY
TRUST_CURRENT_BEHAVIOR = TIER_CURRENT_BEHAVIOR
TRUST_CALLER_STATED = TIER_CALLER_STATED
_TRUST_TIERS = frozenset(TRUST_TIERS)

# 声明的失败面必须覆盖三态（§3）：装载期失败 / 运行期失败 / 合法值缺失。
FAILURE_STAGE_LOAD = "load"
FAILURE_STAGE_RUNTIME = "runtime"
FAILURE_STAGE_VALUE_MISSING = "value_missing"
REQUIRED_FAILURE_STAGES = frozenset({
    FAILURE_STAGE_LOAD,
    FAILURE_STAGE_RUNTIME,
    FAILURE_STAGE_VALUE_MISSING,
})


class ProviderContractError(ValueError):
    """装载期声明缺失或不完整：接入未完成，fail-fast，不进运行期。"""


@dataclass(frozen=True)
class ProviderDeclaration:
    """§2.1 装载期声明（可校验的一等对象）。"""

    provider_id: str
    lane: str
    citation_space: frozenset[str]
    failure_semantics: Mapping[str, str]

    def __post_init__(self) -> None:
        if not str(self.provider_id or "").strip():
            raise ProviderContractError("provider 声明缺 provider_id")
        if self.lane not in _LANES:
            raise ProviderContractError(
                f"provider {self.provider_id}: 供哪一路必须是 d/e/g 之一，得到 {self.lane!r}"
            )
        if not self.citation_space:
            raise ProviderContractError(
                f"provider {self.provider_id}: 引用空间为空，J 的 citations 无处可落"
            )
        missing = REQUIRED_FAILURE_STAGES - set(self.failure_semantics or {})
        if missing:
            raise ProviderContractError(
                f"provider {self.provider_id}: 失败面未覆盖 {sorted(missing)}"
            )
        object.__setattr__(
            self, "failure_semantics", MappingProxyType(dict(self.failure_semantics))
        )


@dataclass(frozen=True)
class ProvidedValue:
    """§2.2 运行期输出：值 + 三件套 + 引用锚点。

    值缺失（§3 第三行）也是本形状的合法实例：value 里没有该维度、
    citation_anchors 为空，本身就是"缺维度"证据，不是失败。
    """

    value: Any
    provenance: Mapping[str, Any]
    trust_tier: str
    staleness: Mapping[str, Any]
    citation_anchors: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.trust_tier not in _TRUST_TIERS:
            raise ProviderContractError(
                f"未知 trust tier {self.trust_tier!r}，须为 {sorted(_TRUST_TIERS)} 之一"
            )
        if not self.provenance:
            raise ProviderContractError("运行期输出缺 provenance（出处）")
        if not self.staleness:
            raise ProviderContractError("运行期输出缺 staleness（新鲜度）")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))
        object.__setattr__(self, "staleness", MappingProxyType(dict(self.staleness)))
        object.__setattr__(self, "citation_anchors", tuple(self.citation_anchors))


def anchors_outside_citation_space(
    declaration: ProviderDeclaration, provided: ProvidedValue
) -> tuple[str, ...]:
    """返回落在已声明引用空间之外的锚点（应为空；供审计/测试用）。"""
    return tuple(
        anchor
        for anchor in provided.citation_anchors
        if anchor not in declaration.citation_space
    )
