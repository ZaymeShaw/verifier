# Materials Protocol

User-managed materials describe **what** to evaluate (glossaries, capability text, API notes). System assets such as `evaluation.md` and `judge_boundary.md` describe **how** to evaluate and stay code-managed.

This file is the V1 runtime contract plus the V1.5 materialize CLI. Design background: `docs/materials-system-implementation.md`.

## Layering

The materials page is a read model over four layers, split by **writer × mutability**:

| Layer | Writer | Page | Editable | Integrity |
|---|---|---|---|---|
| System assets (`project.yaml assets`, kind context/tool/…) | maintainers, with code | read-only list | no | git |
| Investigation artifacts (`assets` kind investigation, draft + production) | machine (investigation flows) | read-only: manifest summary, overview, file list, `source_revision` | **never** (hash chain rejects manual edits) | hash chain |
| Production materials (slots / free) | user upload, or adopt-materialize (V1.5) | read/write | yes — editing a non-upload material downgrades provenance to `derived` and marks `edited` (页面亮「内容已非原样」) | content-hash seal |
| Project structured stores (e.g. `capability_map`) | user | rendered **only when declared** in `materials.yaml stores` | yes | store schema |

Investigation operations are 查看 / 重新调查 / 采纳 / 丢弃; on a remote host only 查看 exists (re-investigate and adopt need the business source, which never ships to the server). Adopt is the V1.5 `materialize` CLI, not a page button. Trust tiers are displayed, not enforced (`min_trust` gating deferred until there is a second operator).

`/api/materials` returns `{project_id, sections: [...]}` where each section carries `kind` (`slots` / `free` / `investigation` / `system_assets` / `capability_map`), `editable`, and its items. The frontend renders sections purely from this response — project differences are declaration-driven, nothing is hardcoded per project. `/api/material/asset_view` gives the read-only projection of one asset (investigation package: manifest summary + `overview.md` + file list; context/tool: truncated body). Asset projections show the **actually-in-use** package, matching runtime selection: when a role's `draft.enabled` is true and the asset has a `candidate_path`, the candidate package is read; `active_source` (`candidate` | `production`) and `active_path` state which one. Overview items keep both `production_exists` / `candidate_exists` plus `active_source`; `asset_file` with scope `artifact_package` opens files from the same active package.

## Entities

Each material lives at `impl/data/<project>/materials/<id>/`:

- `manifest.json` — identity, title, `sha256` of the body, size, provenance, timestamps
- `content.md` — UTF-8 text only (markdown / txt / yaml / json pasted as text)

`id` is a slot id when the material fills a declared slot; otherwise it is a free material id. Both must match `^[a-z][a-z0-9_-]*$`.

Reference scheme: the only valid token is `{material://<project>/<id>}` — braces are the delimiter, so surrounding text never glues onto the reference. Bare `material://…` is rejected with a format error (it reads as a malformed reference, not plain text). Resolvers expand the token to the sealed body. Consumption modes on a material are combinable:

| Mode | When it applies | Missing / over-budget |
|---|---|---|
| binding | slot `roles` include the current role | required slot missing → refuse the run; total bound chars > 30000 → refuse |
| reference | a `{material://}` token is expanded | missing id → resolution error; bare `material://` → format error; expansion > 50000 chars → error (prompt-load paths) |
| agentic (toolbox) | a `{material://}` token in an **axis-2 boundary** whose body does not fit the 50000-char expand budget | auto-degrades: the token becomes a catalog stub (`[大资料未内联] uri · title · size · sha256`) and the consumer role gets the material toolbox (below), scoped to the referenced materials only. Missing id / bare uri still error — reference validity is not size-exempt |

Capability (axis-1) text stays prompt-load only: over-budget references there are an error, because the judge runs without material tools.

## Material toolbox (agentic retrieval consumption)

Design stance: the LLM does agentic retrieval over deterministic, read-only tools. Pre-built
indexes are accelerators, never dependencies. What must stay uniform is **not one retrieval
algorithm** but three thin behavioral contracts (the load-bearing walls):

1. the axis-2 verdict shape — `J(F, G) → 三态 + 自认 + 引用` (predates this design, judge.md);
2. verifiable citations — a citation carries (source, locator, quote) and a deterministic
   resolver can re-read and check it;
3. tool admission — read-only + receipt-bearing + scope-restricted.

Everything opinionated (which tools, lexical vs embedding, format handlers, prompts, budgets)
is replaceable without touching those walls.

**Incubation status**: the toolbox implementation lives in
`impl/projects/llm_probe/material_tools.py` — it is deliberately **not** core yet. Promotion
criteria: a second project needs it AND the baseline set proves its effect. The catalog
degradation (`expand_material_uris_with_catalog`) and the `tool_trail` field on placements are
protocol pieces and stay in core. `investigation.search_index` / `load_entry`
(`impl/core/investigation_key_index.py`) remain the mature pre-built-index door: when a
project registers indexes they join the toolbox as accelerators; their absence never blocks —
outline computes structure on demand.

### Locator

```text
material://<project>/<id>            whole material
L<start>-L<end>                      line range inside one material (1-based, closed)
```

Line ranges are the universal verification floor — they only assume "text". Structural labels
(yaml `intents/name_exact`, markdown headings) appear as outline entry **labels** and are
always translated to line ranges by the format handler, so the resolver and the citation
verifier speak line ranges only. Non-text materials later (databases, APIs) extend the grammar
with their own resolver namespace; contract 2 only requires "re-readable".

### Tools (incubating in llm_probe; read-only, receipt-bearing, scope-guarded)

| Tool | Contract | Format assumption |
|---|---|---|
| `material_outline(material_id)` | skeleton menu with locators; the just-in-time coarse index | format handlers: yaml (top keys + identity-keyed list items), markdown (heading tree); unknown formats degrade honestly — line-block map plus an explicit note 「该格式尚无结构化切片方案」 |
| `material_search(material_id, query)` | deterministic lexical hits with locators | text only — universal |
| `material_read(material_id, locator)` | exact slice, capped lines | text only — universal |

Format handler governance: handlers recognize **formats, never projects** (no project ids in
handler logic). Project-specific processing belongs to project-declared `VerifiableTool`s via
`project_llm_client(tools=...)` — the toolbox is an optional kit, not a mandatory path.
Deferred extension points (declared, not built): embedding as a channel **inside**
`material_search`; per-material `consumption.tools` declarations in the manifest; user-supplied
tools (needs a sandbox/review contract). Today users steer consumption in plain text: the
material **description** rides the catalog stub into the prompt, and the **boundary** text can
carry retrieval hints — both are prompt-visible instruction channels that cost zero new config.

Every call is recorded as a receipt (tool, arguments, returned locators). Consumers attach the
receipts to their outputs; axis-2 placements carry them as `tool_trail`.

### Low-effort discipline (how a weak model stays accurate)

- **Outline first**: skeleton → pick entry → read. Choosing from a menu beats inventing
  grep queries.
- **Copy, never compute**: locators are returned ready-made; the model copies them into the
  next call and into citations. It never derives positions.
- **Mechanical citation enforcement**: for 做错了/做不了 conclusions, each citation's quote is
  re-read at its locator (whitespace-normalized containment). Mismatch → reject and retry with
  the failure details; retries exhausted → placement failure in `errors`, never a silent pass
  and never laundered into 说不清. This is a **production-time contract**: verification happens
  when the conclusion is produced; archived locator strings are display/audit references and
  are not re-verified retroactively.
- **Honest exit**: search miss ≠ statement absent. Retry with a different query/tool inside
  `tool_call_limit`; only budget exhaustion yields 说不清 + missing_material.

With this shell the consumer runs at `reasoning_effort=low`: correctness is guaranteed by
verification, not model intelligence.

Server verifies **content hash** only. Source hashes (business-repo revision) are declarative metadata and are not checked on a remote eval host.

Provenance `source` is one of `user_upload`, `investigation`, `derived`. Trust display order: local investigation > external investigation > derived > upload. V1 does not sign payloads.

## Slots

Slots are a project contract, not an end-user object. Maintainers declare them in `impl/projects/<project>/materials.yaml` (not `project.yaml`: the project config parser rejects unknown keys).

```yaml
slots:
  - slot_id: field_glossary
    title: 字段口径表
    required: true
    roles: [judge]
    fill: [upload]
```

`fill` may list `upload`, `investigate_http`, `source_bind`. V1 only implements `upload`. Roles are `judge`, `mock`, `attribute`.

The same file may declare `stores:` — project-specific structured material stores the page should render. Allowed values: `capability_map`. A store not declared is not shown; its CRUD APIs stay project-scoped either way.

Users fill slots and create free materials on `materials.html`. They do not create slots. Recurring free materials may be promoted to a slot by a maintainer.

`llm_probe` declares no slots and `stores: [capability_map]` (capability presets are llm_probe-specific — only its code resolves `capability_ref`). `client_search` requires `field_glossary` for judge and declares no stores.

## Lifecycle

- Upload / overwrite via `/api/material/upload` writes content then a sealed manifest. Overwriting a material whose provenance is `investigation` or `derived` with different content downgrades provenance to `{source: derived, edited: true}` (origin preserved in `derived_from` / `detail`); identical content keeps provenance untouched.
- Get via `/api/material/get` returns summary + body after hash check.
- Delete via `/api/material/delete`. Deleting a required slot blocks later runs.
- Overview via `/api/materials` (sections, see Layering). Read-only asset projection via `/api/material/asset_view` (includes `materialize_hint` when the package lists `business_source` evidence).

Investigation artifacts stay in `draft/investigation/` (candidate) and `investigation/` (production). They remain reference-shaped (path + source hash + summary). Adopting them into materials is the V1.5 CLI:

```
bash run.sh cli materialize --project <id> --role {attribute,judge,mock} [--apply] [--candidate|--production] [--slot ID] [--push user@host[:/opt/verifier]]
```

- Runs only on a machine that can read the business repository. Missing source root or a source-hash mismatch refuses the whole export ("请先重新调查").
- Package selection matches runtime: with `draft.enabled` on the role, the candidate investigation package is materialized; otherwise production. `--candidate` / `--production` force one side explicitly (mutually exclusive).
- Default is dry-run (hash check, no writes). `--apply` writes one free material per `business_source` evidence plus an index. Production-sourced ids are `{role}-{ref_id}` + `{role}-investigation-snapshot`; candidate-sourced ids are `{role}-draft-{ref_id}` + `{role}-draft-investigation-snapshot`, so both exports coexist without overwriting each other. Provenance is `{source: investigation, execution: local, source_revision, source_sha256, package_source}`.
- Snapshots are **reference / free materials**. They must not fill a slot whose `roles` is non-empty — concatenated business yaml would blow the 30k judge binding budget. `--slot ID` is allowed only for an undeclared id or a slot with empty `roles`.
- Remote eval reads the inlined body via the materials page / `{material://…}`; it does not open business files. Copying `impl/data/<project>/materials/<id>/` preserves investigation provenance. Re-pasting the same text through `/api/material/upload` becomes `user_upload`.
- Do not rsync the whole `impl/data` tree on deploy (that would wipe the eval host's materials). Copy only the materialized directories — `scripts/sync_materials.sh` does exactly that (`--ids` / `--from-materialize-json` / `--all-free`), and `materialize --apply --push user@host[:/path]` runs it automatically for the ids just written.

V2 (`source_bind` / `investigate_http`) and V3 (queryable) are not part of this runtime.

## Preflight and injection

- `live_run` / `run_chain` / non-empty `batch_run` call `require_materials(project_id)` before work. Missing required slots raise with slot titles and point at the materials page.
- Judge loads `binding_materials_for_role(project_id, "judge")`, injects the bodies into the system prompt, and records `kind: bound_material` evidence with uri + sha256.

Limits: body ≤ 1_000_000 characters; sum of bound bodies for one role ≤ 30_000 characters. Over-budget is an error, not a silent trim.
