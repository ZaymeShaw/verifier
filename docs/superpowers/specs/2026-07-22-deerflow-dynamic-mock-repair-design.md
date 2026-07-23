# DeerFlow Dynamic Mock Repair Design

## Objective

Improve DeerFlow's dynamic multi-turn Mock behavior without changing the Mock protocol, making intent mandatory, preferring fixtures, or encoding known test sentences. A generated Mock user must pursue the NBEV business goal naturally and must not expose internal implementation vocabulary.

## Confirmed problems

1. The in-flight multi-turn accumulator historically exposes `extract_output`, while persisted Trace turn records expose `extracted_output`. Direct replay of a Trace-shaped turn therefore loses prior business feedback unless the DeerFlow project boundary accepts both names. The in-flight path itself is not broken and must remain compatible.
2. The generic next-turn prompt asks the model to advance the goal but does not distinguish user-visible business concepts from internal skill, script, file, API, or evaluation concepts. A real Draft run therefore emitted `nbev_planning_v2` as user speech.
3. A successful NBEV planning answer can be classified as `non_agent` merely because its natural-language reply contains refusal-like words such as “无法”. This confuses inability to satisfy one planning dimension with an out-of-domain response.
4. Intent remains optional by contract. A supplied intent is evidence; absent intent may be inferred from the initial request. This repair must not introduce a requirement that single-turn callers provide intent or a duplicated top-level query.

## Design

### Runtime feedback repair

At the DeerFlow project boundary, read persisted `extracted_output` first and accept in-flight `extract_output` as an explicit compatibility fallback. Pass the recovered stage, missing fields, extracted business output, and thread identity to the existing next-turn flow. Do not rename the shared in-flight accumulator or add a schema/protocol field.

### Draft-only user-language policy

Keep Production frozen for comparison. The DeerFlow Draft role will add a bounded policy to dynamic next-turn generation:

- speak as an authenticated NBEV business user;
- use business concepts already present in the goal, conversation, or user-visible assistant reply;
- do not request internal skills, scripts, files, paths, APIs, prompts, evaluation machinery, or implementation steps;
- respond naturally to clarification and continue the same goal;
- do not force all three dimensions when the goal only selected one.

The policy describes semantic ownership rather than enumerating known bad tokens. The existing investigation-derived ContextUnit remains supporting business context; raw repository material is not injected into the runtime prompt.

### Stage inference correction

Preserve the existing stage enum and ordering. A non-empty reply that contains planning structure, NBEV tool evidence, or a business planning result remains `planning` even when it explains that one dimension cannot reach the target. Refusal language is `non_agent` only when no planning evidence is present. This is a local derivation correction, not a Live protocol change.

### Intent behavior

Do not add validation that requires intent. When a concrete intent exists, preserve it as the fact source. When it does not, infer it from the initial user-visible request. Do not re-infer merely because optional `query` is empty if a usable `user_intent` is already present.

## Verification

1. Unit test canonical and legacy prior-turn output recovery.
2. Unit test that Draft policy is present only in Draft behavior and is semantic rather than a known-sample blacklist.
3. Unit test a planning reply containing “无法达到目标” remains `planning`, while a genuinely unrelated refusal remains `non_agent`.
4. Run focused DeerFlow Mock and Live tests.
5. Run the same frozen frontend MockCase through Production and Draft `run_chain` using the approved DeepSeek/DashScope destinations.
6. Treat Draft as improved only if it preserves the goal, advances from visible feedback, avoids internal implementation language, completes normally, and shows no visible regression against Production.

## Non-goals

- No Mock/Live schema redesign.
- No mandatory intent or query field.
- No fixture-first runtime selection.
- No promotion to Production without a separate user decision.
- No hard-coded expected sentence, month, amount, dimension sequence, or tool name.
