# Deerflow clarification-to-planning flow

## How to use this trace map

Use this branch only when the Judge gap says that the user supplied relevant planning inputs but deerflow continued to clarify, stopped without planning, or never invoked the selected planning mechanism. Do not use it for transport failures, upload receipt gaps, or a confirmed raw/stored extraction mismatch.

## Operational index

| Node | Current-case material | Decisive check | What it can prove |
|---|---|---|---|
| `USER_TURNS` | `runtime_checks.clarification_sequence[*].user_text` | List facts supplied cumulatively, without treating a Judge reference answer as input | What the verifier actually sent in each turn |
| `CLARIFICATION_CALLS` | extracted `ask_clarification` questions and reply text | Compare each new question with information already supplied | Repeated or redundant clarification behavior |
| `REQUEST_SUFFICIENCY` | user turns plus the Judge acceptance criteria | Identify which required input the final clarification still requested | Whether the observed question addressed a real missing prerequisite; this is not yet its root cause |
| `LEAD_AGENT_POLICY` | checked-out `lead_agent/prompt.py` clarification policy | Read the exact rule that can trigger clarification and its exit condition | A repair candidate in the checked-out revision, not proof that revision produced the historical trace |
| `SKILL_SELECTION` | current-revision skill inventory and runtime receipt | Confirm which planning skill was selected for this run | Business routing only when the run exposes the selection |
| `PLANNING_EXECUTION` | current-message tool/script calls or execution receipt | Verify a concrete planning action and result | Whether planning actually ran |
| `JUDGE_GAP` | not-fulfilled expectations and final business output | Connect the first observed behavior gap to blocked downstream delivery | Scope and impact, not cause by itself |

## Investigation procedure

1. Start from `JUDGE_GAP`; retain only expectations blocked by the same continued-clarification behavior.
2. Read `clarification_sequence` and reconstruct `USER_TURNS → CLARIFICATION_CALLS`. A missing raw Gateway history is an evidence boundary; it does not erase the stored business output and does not create an extraction mismatch.
3. At `REQUEST_SUFFICIENCY`, name the exact prerequisite requested by the final clarification and show whether a prior user turn supplied it. If the question is generic, say that it is generic rather than inventing a missing field.
4. Inspect `LEAD_AGENT_POLICY` only after the behavior is established. Read the authorized source entry `project_doc:source_lead_agent_prompt` and search its exact policy markers (`PRIORITY CHECK`, `Only after all clarifications are resolved`, and `DO NOT skip clarification`). The checked-out prompt strongly prioritizes clarification whenever anything is unclear and contains no deterministic per-domain sufficiency contract. This identifies a plausible repair surface: add an explicit exit condition or domain sufficiency gate.
5. Do not promote that repair surface to a proven current-case cause unless the deployed revision is aligned and a replay, prompt intervention, or equivalent experiment changes the clarification outcome.
6. If runtime skill selection or execution receipts exist, continue through `SKILL_SELECTION → PLANNING_EXECUTION`. Their absence is unresolved evidence, not proof that a named script should have run.
7. During finalization, keep the current clarification sequence and only the source/replay material that distinguishes the selected explanation from competing ones.

## Repair-oriented boundary

The checked-out lead-agent prompt contains broad mandatory clarification rules. A safe long-term fix candidate is to preserve clarification for genuinely missing or risky inputs while adding a positive exit rule: once the current domain's required inputs are present, proceed using stated defaults and expose any remaining assumptions. Whether this change fixes a historical case must still be verified by a deployment-aligned replay.

## Node: `USER_TURNS`

The exact user messages accumulated in the current thread establish what information was supplied, but not how the hidden model interpreted it.

## Node: `CLARIFICATION_CALLS`

The stored current-turn `ask_clarification` calls and reply text establish the observed questions. When raw history was not retained, they remain business outputs but cannot be compared with raw Gateway objects.

## Node: `REQUEST_SUFFICIENCY`

Compare the final question with facts already present in `USER_TURNS` and the current Judge acceptance criteria. This locates redundant clarification without inventing a universal field checklist.

## Node: `LEAD_AGENT_POLICY`

The checked-out lead-agent prompt is a source-aligned repair surface. It becomes current-case causal evidence only after revision alignment and `CAUSE_VERIFICATION`.

## Node: `SKILL_SELECTION`

Use a current runtime receipt to establish the selected business skill. A checked-out skill file alone does not prove selection.

## Node: `PLANNING_EXECUTION`

A current tool or script receipt establishes that planning ran. Its absence in a compact projection may be an evidence gap rather than proof of non-execution.

## Node: `JUDGE_GAP`

The not-fulfilled expectations define the blocked business outcome and downstream impact; they do not identify the implementation cause.

## Node: `CAUSE_VERIFICATION`

A deployment-aligned replay, prompt intervention, or equivalent controlled comparison must change the clarification outcome before `LEAD_AGENT_POLICY` can be promoted from a repair candidate to the proven current-case cause.
