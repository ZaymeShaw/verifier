# Deprecated UAT Protocol

The standalone UAT protocol is deprecated for this change. `impl/demand/meta-verifier.md` supersedes the earlier UAT-only demand, so this file no longer defines the product capability.

Use `.claude/skills/meta-verifier/protocols/meta_verifier_protocol.md` as the active protocol direction.

## Current boundary

Browser-based page and button checks remain required, but only as meta-verifier evidence collection. They must be driven by:

- a natural-language `/meta-verifier [goal]` request;
- automatic intent routing;
- project artifact discovery;
- checklist generation;
- demand-side persona critique;
- structured meta-verifier findings and reports.

Historical objects such as `UATCase`, `BrowserSession`, `BrowserAction`, `BrowserAssertion`, `UATEvidence`, `UATResult`, and `ProjectUATExtension` must not be treated as the top-level public protocol. Useful browser execution behavior should be migrated into meta-verifier internals.
