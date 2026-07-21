# Deerflow Gateway message and business-skill flow

## How to use this trace map

Start with one not-fulfilled expectation and the exact current turn records. First decide whether the disputed field is supplied by the business Gateway or derived by verifier. `stage` is derived locally by verifier; the Gateway message API does not return that contract field. Therefore a wrong stored stage is not evidence of a business routing failure until the latest raw business AI message has been selected and replayed.

For reply, tool, script, or stage gaps, compare each turn's latest non-middleware AI message with its stored `extracted_output`. If they differ, follow only the extraction branch and stop before blaming business skill selection. If they match but a required NBEV action is absent from the same current message, follow the skill branch using the deployed-revision boundary. A historical message trace can reproduce a verifier regression, but cannot prove which source revision or hidden model branch produced the original business message.

## Operational index

| Node | Current-case input/output | Decisive check | Supported conclusion and boundary |
|---|---|---|---|
| `REQUEST` | current user turn, session and expected business outcome | Compare the exact submitted turn with `normalized_request` | Establishes verifier intent to send, not Gateway receipt |
| `THREAD_CREATE` | thread creation request and returned thread id | Inspect transport status only when the thread is absent or wrong | Establishes thread boundary, not agent reasoning |
| `RUN_WAIT` | one new user message and run response | Check HTTP/result status and run id | Establishes run completion; does not identify the final display message |
| `MESSAGE_HISTORY` | thread-wide displayable message array | Use the exact array stored in the current turn's raw response | Establishes all visible messages, including older runs |
| `LATEST_BUSINESS_AI` | one latest non-middleware AI message | Run `deerflow.message_history_replay` or inspect the identical selection rule | Establishes the only message eligible for current reply/tools |
| `REPLY_EXTRACTION` | selected AI content to `reply_text` | Compare raw selected content and stored extracted reply | A mismatch locates a verifier extraction defect |
| `TOOL_EXTRACTION` | selected AI tool calls to normalized tools | Compare names/args from the same message | A stale or cross-message tool mismatch locates verifier extraction |
| `SCRIPT_DETECTION` | normalized current-message bash calls | Check recognized script paths/names after tool extraction agrees | Establishes verifier observation of scripts, not hidden execution |
| `STAGE_DERIVATION` | current reply, tools and scripts to local stage | Replay `_stage_inference` on raw-selected values | Establishes verifier-derived metadata only; Gateway has no stage field |
| `BUSINESS_SKILL_SELECTION` | raw business AI message and tool calls | Inspect current-revision agent/skill evidence only after extraction agrees | May narrow business routing; hidden model decisions remain unresolved without a trace |
| `NBEV_SKILL` | checked-out `skills/custom/nbev_planning_v2/SKILL.md` | Align request, deployment revision and selected skill | Establishes declared business procedure, not that it ran |
| `NBEV_SCRIPT` | current-message bash/script call or business execution receipt | Verify a concrete script invocation/result | Establishes observed script use; absence in extracted stale tools is not decisive |
| `JUDGE_GAP` | not-fulfilled expectations and actual output | Separate business-output gaps from verifier-derived field gaps | Defines investigation scope, not cause |

## Investigation procedure

1. At `JUDGE_GAP`, keep only not-fulfilled expectations and group them only when one observed defect affects them together.
2. Classify every disputed field: raw business content/tool calls come from `LATEST_BUSINESS_AI`; `stage`, `scripts_called`, and compact final output are verifier derivations.
3. For derived-field gaps, walk `MESSAGE_HISTORY` → `LATEST_BUSINESS_AI` → extraction nodes and replay the exact message array. The first raw/stored mismatch is the relevant defect; downstream stage mismatch is propagation, not a second root cause.
4. If reply and tools agree with raw, then and only then investigate `BUSINESS_SKILL_SELECTION` → `NBEV_SKILL` → `NBEV_SCRIPT` for a genuine business behavior gap.
5. Align the business repository revision, deployment and current request. If only a historical trace or checked-out document is available, state the precise boundary in `unresolved_reason`.
6. During finalization, retain only ContextUnits that connect the current expectation to the selected branch and decisive replay.

## Node: `REQUEST`

The current user turn, session and reference define the requested behavior. They cannot show which agent branch ran.

## Node: `THREAD_CREATE`

The verifier creates or resumes a Gateway thread. Thread transport failures are boundary failures, not evidence about planning logic.

## Node: `RUN_WAIT`

`wait_run` sends the current user message and waits for the run. Completion does not itself select the display message later used by verifier.

## Node: `MESSAGE_HISTORY`

`list_thread_messages` returns displayable messages across the thread. Because the array is thread-wide, current-turn extraction must not combine a new reply with an older tool call.

## Node: `LATEST_BUSINESS_AI`

The current verifier selects the latest non-middleware AI message and extracts both reply and tools from that one object. This is the key boundary for stale-message regressions.

## Node: `REPLY_EXTRACTION`

Raw selected content is normalized into `reply_text`. Whitespace-only normalization is not a material defect.

## Node: `TOOL_EXTRACTION`

Only tool calls attached to the selected current AI message are eligible. A historical trace where stored tools come from an older message is deterministic evidence of the old verifier defect.

## Node: `SCRIPT_DETECTION`

The verifier recognizes configured NBEV script names from current-message tool arguments. It cannot prove hidden execution that the Gateway did not expose.

## Node: `STAGE_DERIVATION`

The verifier infers a stage from current reply/tools/scripts. It is presentation/evaluation metadata, not a Gateway-provided business state contract.

## Node: `BUSINESS_SKILL_SELECTION`

When extraction is faithful and business behavior still misses the expectation, investigate the actual agent and skill path. Do not infer this path merely from a missing compact field.

## Node: `NBEV_SKILL`

The checked-out NBEV skill documents the expected planning workflow. Source presence is background until revision and runtime selection are aligned.

## Node: `NBEV_SCRIPT`

A concrete current-message call or execution receipt can establish script use. A reference answer that invents a different tool name cannot.

## Node: `JUDGE_GAP`

The Judge gap initiates the investigation. Expectations about locally derived `stage` must not be misdescribed as proof that the business system failed to route.

## Known evidence boundary

The Gateway service was unavailable during this investigation, so no new deployment-aligned run was captured. Repository reports from 2026-07-18 preserve real message histories and reproduce the verifier extraction defect, but their deployed business revision is not exposed. The checked-out business source proves current source structure only. Hidden model/skill selection remains unresolved unless a current trace or equivalent execution receipt is obtained.
