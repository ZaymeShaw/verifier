# Design blocks follow-up

## Changes

Modified only the authorized implementation/test files:

- `impl/projects/llm_probe/business_trace/design_rules.py`
- `impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py`
- `impl/projects/llm_probe/business_trace/materials.py`
- `tests/test_design_rule_blocks.py`

`_Blocks.add` no longer recursively emits scalar/key blocks. Each request message and each tool definition is one whole unit. Format inventories retain a whole parent declaration (including required, conditions, combinators and other constraints), plus structural schema fields; no description/type/enum-element scalar blocks. Collected tool-definition record fields are combined into one definition block. JSON is deterministic; string units remain raw. Public entrypoint names and return shapes are unchanged, with optional role metadata on message blocks.

`quote_text(block, path='')` returns original block text for the empty path, otherwise uses `dossier.resolve_node_path(json.loads(block['text']), path)` and returns raw strings or deterministic JSON. This uses the existing dossier path convention, not a newly introduced resolver. In particular, the current resolver does not decode JSON-pointer escapes in subpaths; quoting a whole field block and then `/description` works for schema fields whose names contain slash/tilde. Block source paths still use the module's existing escaped pointer notation.

Transcript canonical system records now retain their original `messages` list alongside unchanged renderer `text`. Ordinary request message records retain the complete original `message` alongside renderer text. Canonical references resolve to this metadata; there is no fallback that reconstructs messages by splitting text. Inventories enumerate each original system message separately, preserve blank lines, and include original role metadata. Received tool result DATA remains candidate source component `system`, with `role=tool`, not a claimed normative instruction. Receiving-call ownership continues to come from explicit `input_refs`.

Materials allocate the delivered shared namespace as `shared#N`, converting both internal interner references and shared-pool keys when constructing the view. Original dossier `content#N` IDs remain distinct. `_share` still recursively transforms values; pool keys are explicitly transformed at view creation. No readable-set broadening and no shared output/common/projection edits.

## Offline validation

No live/model/network calls were made.

Interpreter: `/Users/xiaozijian/miniconda3/envs/agno/bin/python`.

- `-m pytest tests/test_design_rule_blocks.py -q`: **21 passed**.
- Combined run of design blocks, business-trace llmtracing and axis-material tests before the three added tests: **49 passed, 3 failed**.
- Reran business-trace llmtracing and axis-material tests excluding the three failures: **31 passed, 3 deselected**.

Observed failures (not silently fixed outside ownership):

1. `test_llmtracing_runs_transcript_path_not_dossier`: test's patched `prepare=lambda *a` rejects the caller's `tools=` keyword.
2. `test_transcript_axis_does_not_salvage_unanswered_obligations`: same `prepare` keyword mismatch.
3. `test_axis_consumes_each_prepared_batch_once_and_retries_only_the_bad_batch`: expected three client invocations, observed four.

New/updated coverage verifies exact message/tool unit counts, raw quotes via subpaths, nested actual format fields with parent conditions, canonical per-system-message boundaries, tool DATA roles, rendering continuity, explicit ownership, and duplicate original/shared namespaces.

## Frozen full-live dossier inventory (enumeration only)

Source: `report/expectations-20261006/unit-format-full-live-20261007/result.json`, `axes.results[type_id=trace_analysis].output.dossier`. No provider recollection and no evaluator calls. Counts below use `build_links(dossier, axis_id=axis)['links']` and `dossier_blocks`.

| Axis | Links | Unique blocks | system | tools | format | Frozen material batch counts | Total delivered across batches |
|---|---:|---:|---:|---:|---:|---|---:|
| context_memory | 9 | 47 | 9 | 37 | 1 | [47] | 47 |
| intent_understanding | 1 | 29 | 3 | 25 | 1 | [29] | 29 |
| planning_routing | 2 | 15 | 1 | 13 | 1 | [15, 15] | 30 |
| tool_execution | 1 | 15 | 1 | 13 | 1 | [15] | 15 |
| knowledge_data | 1 | 15 | 1 | 13 | 1 | [15] | 15 |
| model_capability | 2 | 30 | 6 | 24 | 0 | [30] | 30 |

Batch counts separately enumerate the frozen `selections[axis].materials[*].links`; repeated collection blocks can therefore appear in multiple deliveries. These are structural inventory costs, not semantic coverage or axis passing claims. Live status has not been evaluated.
