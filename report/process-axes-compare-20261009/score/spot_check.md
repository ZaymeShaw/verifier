# 抽查一致率（TASK.md §3.2）

- 盲测并集：203 条；抽查：71 条
- 判定字段：verdict / gold_id（抽查只判到这一级，不细分 T/F 子码）

- verdict 一致：60/71 = 0.845
- gold_id 一致：66/71 = 0.93

## 分歧明细

- U23dc4bb8（smoke-customer-profile-fuyunping）分歧字段 ['verdict', 'gold_id']：人工 {"verdict": "真问题", "gold_id": "CP-1"} / 模型 {"verdict": "误报", "gold_id": "none"}
- U2b7b9190（smoke-multi-policy-anjinning）分歧字段 ['verdict']：人工 {"verdict": "无法判断", "gold_id": ""} / 模型 {"verdict": "误报"}
- U2c59d754（smoke-multi-policy-anjinning）分歧字段 ['verdict']：人工 {"verdict": "无法判断", "gold_id": ""} / 模型 {"verdict": "误报"}
- U48fd3b0c（main-D01-same-surname-clarify）分歧字段 ['verdict']：人工 {"verdict": "误报", "gold_id": ""} / 模型 {"verdict": "真问题"}
- U518286a3（smoke-agg-paid-prem-fuyunping）分歧字段 ['verdict']：人工 {"verdict": "真问题", "gold_id": "none"} / 模型 {"verdict": "误报"}
- U6978a773（smoke-multi-policy-anjinning）分歧字段 ['verdict']：人工 {"verdict": "无法判断", "gold_id": ""} / 模型 {"verdict": "误报"}
- U6b0de46d（main-D01-same-surname-clarify）分歧字段 ['verdict']：人工 {"verdict": "无法判断", "gold_id": ""} / 模型 {"verdict": "误报"}
- U856c1545（smoke-customer-profile-fuyunping）分歧字段 ['verdict', 'gold_id']：人工 {"verdict": "真问题", "gold_id": "CP-1"} / 模型 {"verdict": "误报", "gold_id": "none"}
- U90e0b295（smoke-multi-policy-anjinning）分歧字段 ['gold_id']：人工 {"verdict": "真问题", "gold_id": "AN-2"} / 模型 {"gold_id": "AN-1"}
- Ua34da1b3（smoke-customer-profile-fuyunping）分歧字段 ['verdict', 'gold_id']：人工 {"verdict": "真问题", "gold_id": "CP-1"} / 模型 {"verdict": "误报", "gold_id": "none"}
- Uc20f4d05（main-D01-same-surname-clarify）分歧字段 ['verdict']：人工 {"verdict": "误报", "gold_id": ""} / 模型 {"verdict": "真问题"}
- Uca06c96c（smoke-multi-policy-anjinning）分歧字段 ['gold_id']：人工 {"verdict": "真问题", "gold_id": "AN-2"} / 模型 {"gold_id": "AN-1"}
- Uf5c82a38（smoke-multi-policy-anjinning）分歧字段 ['verdict']：人工 {"verdict": "无法判断", "gold_id": ""} / 模型 {"verdict": "真问题"}
