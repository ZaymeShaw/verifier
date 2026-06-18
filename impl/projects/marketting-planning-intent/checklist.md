# Checklist

- Intent project uses the shared marketing-planning service but evaluates only `/intent-recognition`.
- Project cases are single-turn and must not require multi-turn/SSE planning behavior.
- Output and reference are aligned as normalized intent labels.
- Batch persistence stores compact case data, not full traces or raw responses.
- Attribution must be grounded in current trace and judge evidence.
