# Check Report — 2026-06-18

Scope: code changes from this session (attribute.py, mp adapter, mp-intent adapter) + related stale code paths.

---

## 1. Code Review (this session's changes)

### attribute.py — 3 edits

| Edit | Location | Verdict | Notes |
|------|----------|---------|-------|
| `_parse_failed` detector | ~line 486 | **OK** | Catches prose-only LLM output, sets `error: attribute_parse_failed`. Clean guard. |
| System prompt JSON directive | ~line 379 | **OK** | Hard-format instruction to prevent prose output. Complements `_parse_failed` fallback. |
| `normalize_attribute_trace_result` new branch | lines 217-235 | **OK** | `has_valid_llm_attribution` trusts LLM output when `expectation_attributions` + `causal_category` are valid. Sets `evidence_quality: medium` when location evidence missing, `high` when present. Prevents over-strict downgrade to `next_verification_step`. |

**Overfitting risk assessment**:
- `has_valid_llm_attribution` condition is **not overfit**: it requires `expectation_attributions` (non-empty list) AND `causal_category` (non-empty, not `needs_human_review`) AND category in taxonomy. Three independent checks, all generic.
- `evidence_quality: medium/high` is informational only — not consumed by downstream logic or frontend currently. Safe addition.

### mp adapter & mp-intent adapter — `_prioritized_ext_repo_files`

| Check | Verdict | Notes |
|-------|---------|-------|
| Priority sort correctness | **OK** | Verified: 53 files returned, all 4 critical files (intent_recognition.py, field_clarification.py, clarification_prompt.py, intent_prompt.py) in top 6 positions |
| `priority_prefixes` hardcoding | **Acceptable** | Prefixes are mp-specific (`app/workflow/...`) but the function lives in mp adapters, not shared code. No cross-project leakage. |
| DRY violation (duplicated in 2 adapters) | **Low risk** | Both adapters share same ext_repo. Could extract to shared utility but current duplication is small (~25 lines). |
| `limit=100` cap | **OK** | Current ext_repo has 64 .py files, 53 after filtering. Cap is generous. |

---

## 2. Frontend/Backend Consistency

| Field | Backend writes | Frontend reads | Status |
|-------|---------------|----------------|--------|
| `expectation_attributions` | attribute.py | live.html:172, summary.html:398, frontend_view.py:159 | **OK** |
| `incomplete_reason` | attribute.py | live.html:177,197, summary.html:394,400 | **OK** |
| `causal_category` | attribute.py | live.html:205, summary.html:400 | **OK** |
| `analysis_quality.passed` | attribute.py | **Not rendered** | **OK** — internal quality gate, not user-facing |
| `analysis_quality.status` | attribute.py | **Not rendered** | **OK** — internal |
| `evidence_quality` (NEW) | attribute.py:233 | **Not rendered** | **OK** — informational, no frontend contract change |

**Verdict**: No frontend breakage. The new `evidence_quality` field is additive and not consumed by frontend.

---

## 3. Overfitting / Generalization Check

| Concern | Assessment |
|---------|------------|
| `_prioritized_ext_repo_files` prefix list is mp-specific | **Acceptable** — function is in mp adapter, not shared |
| `has_valid_llm_attribution` too lax — accepts any LLM output with attributions | **Not lax** — requires causal_category in taxonomy (validated against `_taxonomy(spec)`) |
| `_parse_failed` detector may flag valid partial output | **Not likely** — only triggers when ALL of error, expectation_attributions, causal_category, failure_category are empty AND raw_text is present |
| `extract_json` multi-fence iteration may return wrong JSON | **Low risk** — iterates ``` fences in order, takes first valid JSON parse. Standard pattern. |

---

## 4. Stale Code Paths

| Path | Status | Action needed |
|------|--------|---------------|
| `impl/knowledge/*/agno_memory.json/agno_sessions.json` | **Empty / deprecated** (`db=None` since Agno refactor) | `check1.py` and `monitor_tokens.py` still read this path — **stale, needs update** (deferred per user: check1.py has other updates) |
| `impl/core/knowledge_base.py:18` `from agno.knowledge.embedder import Embedder` | **Works** with current agno 1.7.6 (temporarily broke when I tried `agno.embedder.base`, reverted) | No action needed |
| `impl/checklist/monitor_tokens.py` `get_token_stats()` | **Defunct** — reads deprecated `agno_sessions.json` | Should be updated to read `result.{judge,attribute}.raw_model_output.raw_model_response.metrics` (deferred) |
| `impl/checklist/check1.py:271` session_file path | **Defunct** | Same as above (deferred) |

---

## 5. Issues Found

### Issue 1 (stale path, deferred): `agno_sessions.json` no longer populated

- `check1.py:271`, `monitor_tokens.py:20` still reference `agno_memory.json/agno_sessions.json`
- Correct token source: `result.{judge,attribute}.raw_model_output.raw_model_response.metrics`
- **Status**: Deferred (user confirmed check1.py has other updates)

### Issue 2 (minor DRY): `_prioritized_ext_repo_files` duplicated

- Same staticmethod in both `marketting-planning/adapter.py` and `marketting-planning-intent/adapter.py`
- **Risk**: Low (shared ext_repo, unlikely to diverge)
- **Recommendation**: Could extract to shared base class or utility, but not urgent

### Issue 3 (potential): `evidence_quality` field not surfaced to user

- New `evidence_quality: medium|high` is written to `analysis_quality` but never shown in frontend
- **Risk**: Low — users see `incomplete_reason` and `causal_category` instead
- **Recommendation**: Consider adding to frontend_view if user feedback requests it

---

## 6. Verification (pending)

Smoke test for mp-target-unit-error-1 could not run due to agno import issue (`agno.db` module not found in system python). The project likely requires a specific conda/pip environment not active in the current shell. **Syntax checks pass** for all 3 modified files.

Recommend: run `check1.py` in the proper environment to verify the 3 mp fallback cases now produce real attributions.
