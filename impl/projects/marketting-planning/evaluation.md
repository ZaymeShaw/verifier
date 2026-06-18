# marketting-planning evaluation

## 评估对象

评估当前营销规划 agent 在系统责任边界内是否完成用户意图。reference 不是唯一标准答案文本，而是与 output summary 对齐的条件契约。

## 输出摘要形状

`extracted_output` 应保持轻量：

```json
{
  "stage": "intent|clarification|planning|non_agent|fallback|unknown",
  "event_summary": {"names": [], "counts": {}, "final_event": "", "completed": false},
  "card_summary": [{"path_type": "", "card_code": "", "card_name": "", "fallback": false}],
  "session_summary": {"session_id": "", "required_fields": [], "accumulated_fields": {}, "missing_fields": []},
  "fallback": {"used": false, "allowed": false, "reason": ""},
  "errors": []
}
```

## 参考契约

reference 可包含：

- `expected_stage`
- `required_events`
- `required_path_types`
- `forbidden_path_types`
- `required_cards`
- `forbidden_cards`
- `allow_fallback`
- `session_requirements`
- `semantic_requirements`

输入无 reference 时，judge 可以生成同形状参考契约；前端必须标记为 judge-generated。
