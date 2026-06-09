# QA Project Boundary Notes

## Boundary purpose

QA's boundary is not whether the evaluated QA system was called live. The key boundary is what evidence the judge is allowed to use for each scenario.

## Evidence boundaries

- `qa_gold_answer`: judge compares actual answer against the golden/reference answer and user question. It should not require external knowledge unless the project standard explicitly allows it.
- `qa_context_faithfulness`: judge evaluates whether actual answer is supported by provided contexts. Unsupported external claims should be penalized.
- `qa_weak_quality`: judge estimates answer usefulness and risk from question and actual answer only. It must not claim accuracy.

## Scenario boundary

Scenario is inferred per sample from available fields unless explicitly supplied. Mixed-scenario datasets are allowed, but aggregate metrics must remain separated by scenario.

## Human review boundary

The system should expose uncertainty rather than pretending all QA evaluation is fully automatic. Low confidence, severe errors, boundary scores, and weak evidence should be routed into a human-review queue.
