# 20260610 QA 批量 uncertain 审核报告

## 背景

`review.md` 新增反馈：QA project 中点击批量归因时大量 case 变成 `uncertain`。按 `check.md` 要求，本次检查不仅看前端展示结果，也检查产生结果的机制：样本规范化、trace、judge、attribute、batch 和 check 链路是否一致。

## 复现

执行 QA mock batch：

```bash
python - <<'PY'
from impl.core import pipeline
res = pipeline.batch_run('QA', pipeline.mock_cases('QA'), mock=True, concurrency=2)
print([r['judge']['verdict'] for r in res.runs])
print([r['judge']['quality_flags'] for r in res.runs])
PY
```

修复前观察到 mock QA 样例全部为 `uncertain`，`quality_flags` 包含 `llm_call_failed`。进一步检查 `raw_model_output`，根因是 LLM judge 调用返回 `HTTP Error 402: Payment Required`。这不是 QA 样本本身全都不可评估，而是外部 LLM 调用失败被统一降级为 uncertain。

## 根因

1. QA 是“已产出答案评估”场景，mock/上传样本通常已经包含 `actual_answer`、`golden_answer` 或 `contexts`。
2. 当 LLM judge 不可用时，通用 judge fallback 只能返回 `uncertain`，导致 QA 批量看起来大面积不确定。
3. attribute LLM fallback 原本缺少 `trace_analysis`、`suspected_locations`、`verification_steps` 等协议字段，check agent 会继续报告协议缺口。

## 已执行修改

1. `impl/projects/QA/adapter.py`
   - 增加 `normalize_judge_result()`，仅在 `llm_call_failed` 时启用 QA 项目内的确定性兜底。
   - `qa_gold_answer`：根据 actual 与 golden answer 的字符覆盖率给出保守 verdict/score。
   - `qa_context_faithfulness`：根据 actual 与 contexts 的文本重叠做上下文忠实度兜底。
   - `qa_weak_quality`：按弱质量场景只做基础可用性估计，并保留 `estimated_quality_only`。
   - 兜底结果明确标记 `quality_flags=["llm_call_failed", "deterministic_fallback"]`，避免伪装成 LLM 深度评估。

2. `impl/core/attribute.py`
   - attribute LLM 调用失败时补齐协议字段：`evidence_chain`、`trace_analysis`、`suspected_locations`、`root_cause_hypothesis`、`verification_steps`、`patch_direction`。
   - 明确说明这是 LLM 调用失败兜底，不作为最终业务根因。

## 修复后验证

执行：

```bash
python - <<'PY'
from impl.core import pipeline
import json
res = pipeline.batch_run('QA', pipeline.mock_cases('QA'), mock=True, concurrency=2)
print(json.dumps({
  'total': res.total,
  'statuses': [r.get('judge',{}).get('verdict') for r in res.runs],
  'scores': [r.get('judge',{}).get('score') for r in res.runs],
  'check_passed': res.check.get('passed'),
  'check_issues': res.check.get('issues'),
}, ensure_ascii=False, indent=2))
PY
```

结果：

```json
{
  "total": 3,
  "statuses": ["incorrect", "correct", "correct"],
  "scores": [0.4, 1.0, 0.9],
  "check_passed": true,
  "check_issues": []
}
```

## check.md 审核 checklist

- [x] 机制源头检查：确认大量 uncertain 的源头是 LLM judge 402，而不是前端展示误差。
- [x] 协议对齐：QA fallback 仍通过 `normalize_judge_result()` 接入统一 `judge -> attribute -> cluster -> check` 链路，没有新增并行 batch 逻辑。
- [x] 项目边界清晰：QA 特定兜底放在 `impl/projects/QA/adapter.py`，没有污染 generic core。
- [x] 避免过拟合：兜底按 QA scenario 和样本字段判断，不绑定某个固定 case。
- [x] 不伪装深度评估：LLM 失败兜底会保留 `llm_call_failed` / `deterministic_fallback` 标记。
- [x] check agent 通过：QA mock batch 后 `check_passed=true`。

## 注意

该修复解决的是 LLM 不可用时 QA 批量全部 uncertain 的体验问题。恢复 LLM 余额/可用性后，仍会优先使用真正的 LLM judge；确定性兜底只在 `llm_call_failed` 时启用。
