## ADDED Requirements

### Requirement: Attribution is grounded in current-case trace
The system SHALL attribute incorrect outputs using current-case evidence from input, output, reference, judge result, execution trace, project docs, code/config, or verified local chain tests.

#### Scenario: Incorrect output needs attribution
- **WHEN** judge returns a non-correct or uncertain verdict
- **THEN** attribution identifies the earliest supported divergence point or explicitly reports that evidence is insufficient

#### Scenario: Attribution names concrete failure evidence
- **WHEN** attribution reports a root cause
- **THEN** it cites specific current-case evidence such as mismatched fields, failed trace nodes, code/config locations, prompt/config errors, API errors, parse failures, or local chain-test observations

#### Scenario: Attribution avoids vague module-only causes
- **WHEN** attribution cannot connect a failure to concrete evidence
- **THEN** it does not present a vague module-level explanation as a completed root cause

### Requirement: Attribution output is actionable for developers
The system SHALL produce attribution summaries that tell developers what is wrong, where it occurs, what was expected, what happened, and what to change or verify next.

#### Scenario: Root cause is supported
- **WHEN** attribution has enough evidence for a root cause
- **THEN** it includes suspected location, expected behavior, actual behavior, evidence chain, and patch direction

#### Scenario: Root cause is not supported
- **WHEN** attribution lacks enough evidence to determine the root cause
- **THEN** it returns an incomplete attribution status with the next concrete verification step rather than inventing a fix

#### Scenario: Mapping risk is present
- **WHEN** attribution depends on field, enum, config, or label mapping
- **THEN** it verifies the mapping source before using it as root-cause evidence
