# Input / Output Case Integrity Design

## Goal

Ensure every summary row keeps its input, extracted output, reference, judge,
attribution, and trace attached to the same case without changing the existing
one-row frontend layout.

## Confirmed failures

- A request candidate is currently enriched with `output` and `reference`
  before request-schema validation. Projects whose request schema rejects those
  non-request fields can fall through to scenario-based intent generation, so a
  case keeps identity A while executing request B.
- Some persisted fixtures already contain unrelated input and output/reference
  content. A faithful frontend exposes that source-data mismatch.
- The frontend accepts a stored trace immediately when its `case_id` matches the
  row, even if its input content does not match the current case.

## Design

### Runtime request integrity

Build and validate the live request only from request-side case data. Output and
reference remain evaluation-side data and must not cross the request-schema
boundary. When a case contains a valid request-shaped input, use that request
directly; do not replace it with a scenario-generated intent.

This preserves the existing provided-output behavior: output/reference remain
available on the case for delivery and judging, but they are not request fields.

### Frontend merge guard

Keep the current Input / Output / Reference / Judge / Attr / Trace row layout.
Batch event and final-run merges still use stable case identity, but a matching
`case_id` is necessary rather than sufficient: when trace input is available,
its canonical request content must also match the row's canonical request.

On mismatch, do not attach the incoming output, judge, attribution, or trace to
the row. Preserve the row input/reference and expose the row as pending/error so
stale or cross-case evidence cannot appear valid.

### Fixture correction

Correct only source-confirmed mismatched fixtures. Do not invent replacement
answers. Prefer restoring the corresponding input when the output/reference pair
clearly belongs together and is the evaluated artifact; otherwise remove or
quarantine the invalid fixture until authoritative data is available.

## Tests

- A request-shaped case containing output/reference validates and executes its
  original input without calling scenario-based intent generation.
- Trace input, normalized request, and extracted output remain associated with
  the same case under concurrent batch execution.
- Frontend rejects a run with matching `case_id` but different trace input.
- Frontend accepts canonical-equivalent inputs that differ only in identity or
  wrapper fields.
- Corrected fixtures have internally coherent input, output, and reference.
- Existing output/reference formatting and the wide final Trace column remain
  unchanged.

## Non-goals

- No frontend redesign.
- No heuristic semantic classifier in the browser.
- No global rewrite of historical context-store artifacts.
- No fallback that silently substitutes a different request merely to make a
  schema check pass.
