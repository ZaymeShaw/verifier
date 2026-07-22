# DeerFlow Open-World Mock User Design

## Objective

Improve the DeerFlow Draft Mock so dynamically generated cases resemble the broad population of people who may actually use the business tool. Generation must not collapse into a small intent enumeration or repeatedly paraphrase one NBEV-planning sentence.

Success means that, under the same project contract, Draft produces legal and plausible user utterances with materially lower repetition and broader user situations than frozen Production. Longer text, more fields, or more scenario labels are not improvements by themselves.

## User model

The candidate models a distribution of possible users, not one canonical persona.

Only a few hard boundaries are stable:

- the speaker could plausibly use the DeerFlow business tool;
- an open-world case expresses work the business assistant can meaningfully help with, rather than a pure product-support incident such as reporting that the page is spinning, cannot open, or failed to submit;
- the speaker talks from user-visible knowledge and does not claim repository, prompt, API, trace, identifier, or implementation access;
- the resulting request obeys the DeerFlow request schema;
- an explicitly supplied user goal remains the fact contract and is not enriched with invented details.

Everything else may vary naturally, including role, seniority, business familiarity, product familiarity, wording, patience, urgency, information completeness, current work stage, prior use, uncertainty, corrections, and willingness to continue. These are illustrative variation dimensions, not a finite taxonomy or a required combination matrix.

Open population coverage must not produce generic or context-free utterances. Each generated case should instantiate one coherent, concrete moment for one plausible user: what they are working on, why they need it now, what they already know, what result or decision they need, and which details or constraints matter in that moment. Concrete time periods, targets, business objects, comparisons, partial progress, preferences, and wording may vary substantially when the caller has not fixed them. The generated details must fit together as one believable situation rather than being independently randomized fields.

Because open-world mode has no caller-owned fact contract, that coherent situation may contain synthetic but realistic specifics such as a planning period, target amount, current progress, comparison group, selected business perspective, previous-plan state, or decision deadline. Generated specifics must not use real institution names, real people, identifiable customer data, or imply access to facts outside the sampled user's own visible work situation.

Generality is evaluated across the population; specificity is evaluated within each individual case. High variation should come from meaningfully different situations and needs, not merely synonyms, random numbers, or swapping one fixed entity name for another.

The investigation ContextUnit describes this population, the tool's user-visible purpose, and the hard knowledge boundary. It must not prescribe a preferred voice or exhaustive list of intents.

The product-support boundary is semantic, not a phrase blacklist. It does not restrict the breadth of business requests, terminology, user roles, language habits, completeness, or multi-turn behavior. A caller may still explicitly request the `service_unavailable` evaluation scenario; that directed boundary case is separate from the open-world business-user pool.

## Generation modes

### Open-world generation

When the caller does not provide a concrete intent, Draft performs one intent-generation LLM call that jointly invents a plausible current user situation and returns:

```text
user_context → user_intent → query
```

A locally generated diversity seed is included only to prevent identical prompts from producing identical results at temperature zero. The seed has no business meaning, is never copied into the utterance, and cannot become a fact source. The model remains free to choose any plausible user need within the broad user-visible product boundary.

In this open mode, the model may introduce concrete facts needed to make its sampled situation realistic because there is no caller-supplied fact contract. It should vary those facts naturally and avoid repeatedly falling back to the same month, amount, organizational role, task stage, business object, or sentence structure. It need not mention every possible detail: omission, uncertainty, shorthand, and contextual references are also realistic forms of specificity.

Existing scenario labels may be retained as optional evaluation constraints when a caller explicitly asks for one. They are not the source vocabulary for open-world generation and do not define the total space of possible user questions.

### Constrained generation

When a caller supplies a concrete intent or explicit evaluation scenario, Draft preserves it. It may vary user context and natural expression only where doing so does not invent, remove, narrow, or contradict facts. This keeps targeted regression cases usable without turning them into the general generation algorithm.

This fact-preservation rule applies to constrained generation only: it must not add a month, amount, organization, product type, relationship, prior action, or other fact that the caller did not supply. It also must not be misapplied to open generation in a way that forces all open cases to remain vague.

### Multi-turn continuation

Later turns preserve the same sampled user and goal while reacting to visible system output. The user may supply missing information, ask for clarification, correct the system, change a preference, narrow or expand a request, report confusion, abandon the attempt, or stop after the goal is met. Continuation is not forced through a fixed stage sequence.

## Runtime boundaries

The change remains inside the DeerFlow Draft Mock assets:

- revise the Mock investigation artifact into a population-level user contract;
- register the concise contract as the mandatory Draft Mock ContextUnit;
- keep `draft/mock.py` thin and use the existing ProjectMock/MockAgent protocol;
- add only the smallest candidate-side mechanism needed to pass a diversity seed into the existing single intent-generation call;
- keep Production frozen and do not change public MockCase, live-request, or Draft protocols.

Request-shape mapping should remain deterministic where the DeerFlow chat request can be constructed directly from the generated query. It must not add another LLM call merely to wrap the query in `input.messages`.

## Validation

The validator enforces only hard properties:

- required Mock and live-request structure is present;
- the user message is non-empty;
- the message does not contain system-internal language or leaked identifiers;
- a constrained request preserves its supplied facts;
- multi-turn output remains coherent with visible conversation state.

It must not require fixed words such as `NBEV`, `规划`, `队伍`, `客户`, or `产品` for every positive sample. It must not enumerate known bad phrases or judge one style as the preferred user voice. Semantic breadth and naturalness remain Draft Loop review concerns rather than regex truth.

Pure product-support incidents are excluded through the open-generation responsibility description, not by adding strings such as `转圈`, `打不开`, or `提交失败` to Validator rules. This avoids rejecting legitimate business requests that happen to use similar words in another context and avoids a second classifier/repair LLM call.

## Draft Loop evaluation

Freeze Production, objective, review criteria, and iteration inputs before comparison. Do not expose promotion-only unseen cases to the optimization executor.

Compare Production and Draft on:

- schema legality and constrained-intent fidelity;
- exact and near-duplicate rate across repeated open-world generations;
- breadth of user situations and speech styles without treating category count as the goal;
- realism and situational specificity without rewarding mandatory slot filling or longer text;
- within-case concreteness and coherence, while avoiding repeated default facts across cases;
- absence of implementation language and invented privileged knowledge;
- multi-turn coherence and non-repetition;
- LLM call count and token cost.

Draft is better only if it materially reduces repetition and produces a broader set of plausible user utterances without regressions in legality, fact fidelity, knowledge boundary, or multi-turn coherence. One intent-generation call per case is the cost target. Infrastructure failures remain blockers and are not quality results.

## Non-goals

- No exhaustive intent, persona, task, or wording enumeration.
- No static-fixture preference for dynamic DeerFlow generation.
- No public protocol or frontend redesign.
- No product-support keyword blacklist or closed business-intent allowlist.
- No automatic promotion.
- No claim that a finite generated batch represents literally every possible utterance.
