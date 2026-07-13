# Draft Comparison Report

## Scope

- Project: `<project_id>`
- Role: `<attribute / judge / ...>`
- Current implementation: `<impl/projects/<project>/<role>.py or core fallback>`
- Draft implementation: `impl/projects/<project>/draft/<role>.py`
- Mock data source: `<draft config frozen mock dataset>`
- Config: `<draft config path>`

## Result

Conclusion: draft better / draft not better yet / blocked

## Summary table

| Case | Status (current → draft) | Strength / Confidence (current → draft) | Draft improvement | Risk |
| --- | --- | --- | --- | --- |
| `<case_key>` | `<status>` → `<status>` | `<strength>` → `<strength>` | `<evidence / link localization / judgment accuracy delta>` | `<overfit / inflation / missing evidence / faking risk>` |

## Evidence quality

- Current gaps:
  - ...
- Draft improvements:
  - ...
- Remaining blockers:
  - ...

## Link localization (attribute 专属)

- Current stops at: `<module name / stage name>`
- Draft drills down to: `<specific tool / code path / config key>`

## Business expectation extraction (judge 专属)

- Current extraction:
  - ...
- Draft extraction:
  - ...

## Anti-overfit check

- Mock dataset unchanged during loop: pass / fail
- User-requested config changes applied: none / listed below
- Case id / sample index hardcoding: pass / fail
- Current-case-only evidence: pass / fail
- Canonical standard preserved: pass / fail
- Missing evidence does not produce strong / high confidence: pass / fail
- Fulfilled cases not forced into failure: pass / fail
- not_evaluable not wrapped as fulfilled / not_fulfilled: pass / fail

## Decision

Promotion recommendation: yes / no

Required follow-up before promotion:

- [ ] `draft/<role>.py` 可 import，`__init_subclass__` 不报错
- [ ] 当前协议所有 `@abstractmethod` 已实现（对照自省结果）
- [ ] 没有覆盖模板方法或内部方法
- [ ] 签名与 production `ProjectXxx` 一致
- [ ] 代表 case 的 targeted run 或局部函数验证通过
- [ ] mock 对比报告显示 draft 在证据质量/链路定位/泛化风险上优于或不弱于 current
- [ ] tool/probe failed 不会伪造 strong
- [ ] production loader 在 `<role>_draft.enabled=false` 时不加载 draft
- [ ] 人工确认后才 promotion：搬移 `draft/<role>.py` → `<role>.py`，`draft/tools/` → `tools/`，`project.yaml` 中 `<role>_draft.enabled` 设为 `false`
