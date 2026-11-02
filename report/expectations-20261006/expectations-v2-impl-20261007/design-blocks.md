# Design original blocks — implementation handoff

Status: implemented and offline unit-tested (2026-10-07). No model or network calls. No demand/spec changes; no shared-code edits, including `materials.py`.

## Owned files

- `impl/projects/llm_probe/business_trace/design_rules.py`
- `tests/test_design_rule_blocks.py`

Public interfaces (exact caller names):

```python
from impl.projects.llm_probe.business_trace.design_rules import (
    project_design, dossier_blocks, transcript_blocks,
)

# Trace object with project_fields.business_trace / turn_records snapshots.
# Safe for pre-run question ② (candidate methods), NOT demand extraction.
design = project_design(trace)  # {"blocks": [...], "sha256": "..."}

links = [{
    "link_id": "model_capability:c1", "link_type": "model_capability", "turn": "turn1",
    "input": [{"ref": "c1", "field": "exact_request"}],
    "output": [{"ref": "c1", "field": "output"}],
}]
blocks = dossier_blocks(dossier, links, "model_capability")
# Transcript: use its call id (e.g. t1.c2) or response endpoint t1.c2.response.
blocks = transcript_blocks(transcript, transcript_links, "model_capability")
```

Block shape:

```json
{
  "id": "design:<sha256>",
  "ref": "c1",
  "path": "/fields/exact_request/value/messages/0/content",
  "text": "整段输出必须为 JSON。\n取消时例外。",
  "component": "system",
  "scope": "actual_input",
  "link_ids": ["model_capability:c1"]
}
```

`tool` is populated for named tool definitions. `link_ids` is present on dossier/transcript blocks, not the pre-run projection. IDs include source record, path, component, scope, tool name and text; identical text with distinct provenance never merges. One original source reused in multiple evidenced calls can have multiple receiving `link_ids`. Results and membership lists are deterministically ordered.

## Provenance and source boundaries

- `project_design` reads registered definition declarations and only the first gateway call's typed tools/format parameters. It never reads responses, tool results, later calls, or runtime system messages (which can interpolate upstream outputs). Only `instruction_templates[i].template` is read, never filled `instance`. All projection blocks use `observed_at_collection_not_verified_run_version`.
- Dossier exact requests enumerate every input message, every tool, and every format/schema node. Captured OpenInference `llm.tools.*`, `tool_definitions`, and invocation format parameters belong to that same exact call. Output message endpoints can locate their owning call via explicit `output_message_ref`; no first-run guess is used.
- Applicable collected definitions ride along for non-model axes, including nested tool definitions. They remain collection-version reference scope even if their text matches actual input.
- Tool span `tool_description` is `execution` only on a current execution record. A collected copy stays reference-only.
- Context should-deliver run input is `execution` only if destination call ownership has the same recorded `run_id`; otherwise reference-only. Actual destination request is separately `actual_input`. Merely collecting a system definition does not prove that it should have been delivered.
- Transcript membership comes from each call's `input_refs`, resolved through `canonical_ref`, not adjacency. Model rules cannot be borrowed from another call simply because its text appears in the same transcript. Output records are excluded; replayed actual input message records remain available.
- No keywords classify/filter rule content. A whole structural block preserves conditions/relationships; child nodes (including exact string leaves) allow verbatim newline/quote substring checks. Components denote the source family, not a claim that every input message or every schema value is a normative rule.

## Pointer convention and caller responsibilities

Pointers address **expanded values**, with JSON transport envelopes decoded. Thus `/fields/exact_request/value/messages/0/content` refers inside a decoded string request, and `/text/0/function/description` refers inside a decoded transcript tools entry. `/` and `~` in actual keys are JSON-pointer escaped. Root structured texts use deterministic JSON; original string leaves are unchanged.

The output validator should validate quotes against the delivered `block.text`; it must not traverse a raw JSON string without decoding the transport envelope. Block coverage is a receipt of material delivery/review, **not proof that all semantic rules were checked**. Whole sentences, linked conditions, applicability and interpretation remain the adjudicator/reviewer's responsibility.

## Explicit material limitations (not faked as confirmation)

1. Agno provider labels reconstructed message membership as candidate/unverified, even with matching token counts. Without an exact request these messages are not model `actual_input` blocks; non-model axes can receive them as reference-only. This intentionally does not elevate reconstructed membership to exact receipt.
2. Current transcript provider joins multiple system messages into one text entry, losing their individual boundaries. This module retains that entire entry; it cannot honestly reconstruct individual messages by splitting blank lines. Per-message system enumeration needs an upstream provider change, outside this task's ownership. Tools and format JSON do retain structure and are enumerated individually.
3. Existing context link generation can select an arbitrary first run when it cannot identify an owner. This module does not trust that guess: unmatched source input remains reference-only. If the dossier has no ownership evidence, this does not establish a should-deliver contract.
4. `project_design` deliberately excludes runtime system messages, even the first gateway call, because upstream direct/tool processing can have already been interpolated into them. Independently registered system declarations/templates are required for safe pre-run inclusion.
5. `materials.py` was not modified. Block construction reads the original dossier content pool and therefore does not depend on the rendered material shared namespace. Output/projection integration remains coordinator-owned.

## Validation evidence

Command (offline):

```text
/Users/xiaozijian/miniconda3/envs/agno/bin/python -m pytest tests/test_design_rule_blocks.py -q
..................                                                       [100%]
18 passed in 0.05s
```

Also passed module `compileall`.

Tests cover output-independent pre-run SHA; filled-template exclusion; first-call declaration boundary; exact-input provenance; different owners with identical text; tool names; schema field pointers/escaping; original newlines and quotes; collected-vs-execution scope; context real owner vs guessed first run; unverified reconstruction; content interning; span tools/format; transcript own-call canonical membership; missing call ownership; separate conditions; redacted inputs; deterministic dictionary-order independence; output-message owner lookup; collection-only tool descriptions.

Not claimed: full-repository regression, live evaluator validation, semantic completeness, or provider recovery of already-lost system-message boundaries.
