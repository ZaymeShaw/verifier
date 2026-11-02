"""Authority Agent 公共协议 schema（宿主无关）。

运行时协议见 spec/alg/authority.md 与 spec/grill/authority.md。这里只暴露
AuthorityRequest / AuthorityClaim / AuthorityResolution；AuthorityEnvironment
是 Core 私有组合对象，不属于公共协议。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


AuthorityDecisionStatus = Literal["resolved", "unresolved"]
AuthorityClaimStatus = Literal["supported", "contradicted", "ungoverned", "gap_only"]
AuthorityStatus = Literal[
    "resolved",
    "unresolved",
    "supported",
    "contradicted",
    "ungoverned",
    "gap_only",
]


@dataclass(frozen=True)
class AuthorityClaim:
    """Judge 希望 Authority 担保的一条规范性断言。

    subject 是项目自定义锚点；协议不假设字段、接口、条款或流程节点等具体形态，
    只要求同一项目内可稳定序列化、可确定性比较。
    """

    claim_statement: str
    subject: Any
    conclusion_kind: str
    intended_use: str


@dataclass(frozen=True)
class AuthorityRequest:
    """一次 Authority 调用的通用输入。

    decision_question 必须自包含业务条件：一个完整业务规则、定义、契约或来源选择
    问题，包含所有可能改变答案、且未被 Environment 固定的业务条件。不承担资料空间
    或权限控制；有效资料空间始终由代码绑定的 AuthorityEnvironment 决定。

    claim 为空时沿用 resolved/unresolved 提问模式；claim 非空时进入担保模式，
    Authority 先独立裁决问题，再将独立结论与 claim 比对。
    """

    decision_question: str
    claim: Optional[AuthorityClaim] = None


@dataclass(frozen=True)
class AuthorityIndependentResolution:
    """担保模式中、看到 claim 之前形成的独立裁决，用于审计防锚定。"""

    status: AuthorityDecisionStatus
    statement: str
    reason: str
    basis_evidence_ref_ids: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthorityResolution:
    """一次 Authority 调用的通用结果。

    提问模式 status 为 resolved/unresolved；担保模式为 supported/contradicted/
    ungoverned/gap_only，并在 independent_resolution 中保存盲查阶段结论。
    """

    status: AuthorityStatus
    statement: str
    reason: str
    basis_evidence_ref_ids: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    independent_resolution: Optional[AuthorityIndependentResolution] = None
