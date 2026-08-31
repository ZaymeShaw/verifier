from __future__ import annotations

from impl.projects.client_search.judge import authority_mode_prompt_clauses


def test_enabled_branch_has_no_closed_mode_wording() -> None:
    clauses = authority_mode_prompt_clauses(True)
    blob = "".join(clauses.values())
    assert "Authority 关闭时" not in blob
    assert "resolved" in blob


def test_closed_branch_keeps_legal_ne_and_drops_total_ban() -> None:
    clauses = authority_mode_prompt_clauses(False)
    blob = "".join(clauses.values())
    assert "输入坏" in blob
    assert "完全无关" in blob
    assert "只判 fulfilled/not_fulfilled" not in blob
    assert "Authority 关闭时" not in blob
