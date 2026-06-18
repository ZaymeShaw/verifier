# marketting-planning-intent 意图定义

## 意图标签全集（7 个）

来源：下游服务 `app/schemas/intent.py` 的 `IntentType` 枚举。

| intent | 中文名称 | 业务含义 | 典型 query 示例 |
|--------|---------|---------|---------------|
| `other` | 其他意图 | 完全超出 NBEV 达成路径规划范畴的问题，如闲聊、写代码、非保险领域问题。系统最大概率返回此标签。 | "帮我写一首诗"、"组织架构怎么调整"、"今天天气怎么样" |
| `customer_portrait` | 客户画像分析 | 用户想了解客户的分布、画像、客温客价等信息，包括客户数量、结构、特征分析。 | "帮我做高净值客户增长计划"、"看看客户年龄分布" |
| `nbev_planning` | NBEV达成路径规划分析 | 用户想进行 NBEV 达成路径的规划、测算或分析，从队伍、客户、产品维度分析如何达成 NBEV 目标。需要提取 target_value（目标值，单位万）和 path_types（路径类型：队伍/客户/产品）。 | "明年NBEV怎么提升"、"我想提高保费规模" |
| `nbev_planning_fallback` | NBEV规划兜底 | 仍属于 NBEV 目标值达成路径规划范畴，但当前智能体暂不支持的能力，例如直接修改达成路径测算中的各种数值、AI 研判分析结果等。 | "优化产品组合"、"增加新客户数" |
| `achievement_measurement_adjustment` | 达成测算调整 | 用户已经完成某些路径的达成测算后，想重新测算新的路径或调整已有测算。 | "重新测算客户路径"、"规划产品达成路径"、"再看队伍达成路径" |
| `team_portrait` | 队伍画像分析 | 用户想了解队伍（代理人/团队）的分布、结构、产能、绩效等信息。 | "看看队伍产能分布"、"分析代理人结构" |
| `target_value_adjustment` | NBEV目标值调整 | 用户想修改或调整 NBEV 目标值，而非从零开始规划达成路径。 | "调整NBEV目标到500万"、"修改保费目标" |

## API 输出结构

### 请求

```json
{
  "session_id": "eval-xxx",
  "trace_id": "eval-xxx",
  "org_id": "eval-org",
  "user_text": "我想提高保费规模",
  "extra_input_params": {
    "agent_args": {
      "conversation_id": "eval-xxx",
      "message": {"content": "我想提高保费规模", "content_type": "text"}
    },
    "args": {"extensions": {}, "contexts": []}
  }
}
```

### 响应（原始）

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "robot_text": "NBEV达成路径规划分析",
    "end_flag": 1,
    "extra_output_params": {
      "intent": "1003",
      "intent_name": "NBEV达成路径规划分析",
      "card_result": {
        "event": "reasoning_message_content",
        "extensions": {
          "nlu_info": {
            "subIntent": "NBEV达成路径规划分析",
            "intent": "nbev_planning",
            "confidence": 0.9,
            "target_value": null,
            "path_types": null
          }
        }
      }
    }
  }
}
```

### 提取后（verifier adapter `extract_output`）

```json
{
  "intent": "nbev_planning",
  "confidence": 0.9,
  "raw_intent": "1003",
  "slots": {
    "subIntent": "NBEV达成路径规划分析",
    "target_value": null,
    "path_types": null
  },
  "entities": [],
  "ambiguous": false,
  "fallback": false,
  "errors": []
}
```

字段说明：

- `intent`: nlu_info.intent，标准化意图标签（7 个之一）
- `confidence`: nlu_info.confidence，0-1 置信度
- `raw_intent`: extra_output_params.intent，下游原始意图 ID（如 1003、4001 等）
- `slots`: nlu_info 中除 intent/confidence/subIntent 外的其他字段（如 target_value、path_types）
- `fallback`: 是否为 fallback/unknown 意图
- `ambiguous`: nlu_info 中的歧义标记
- `errors`: 错误信息

## Judge 评估参考

1. **核心任务**：判断单轮意图识别结果是否满足下游 dispatch 的需求
2. **评估边界**：仅评估意图标签正确性和置信度，不评估多轮规划、SSE 卡片生成
3. **重建意图**：judge 必须根据 query 文本重建用户真实意图，不要直接复用下游给出的 intent
4. **业务视角**：从业务角度评估，如 query "我想提高保费规模" 的用户意图是提升 NBEV，期望 intent 应为 `nbev_planning`
5. **置信度阈值**：关键业务意图（nbev_planning、customer_portrait）建议 min_confidence ≥ 0.7

## Mock 数据说明

mock 数据的 `reference` 字段格式：

```json
{
  "intent": "nbev_planning",
  "min_confidence": 0.7,
  "required_slots": ["target_value"],
  "allow_fallback": false
}
```

- `intent`: 期望的意图标签
- `min_confidence`: 最低置信度阈值
- `required_slots`: 必须提取的槽位列表
- `allow_fallback`: 是否允许 fallback 意图

注：mock 数据的 `output` 字段已按 rule.md 要求清空，运行时通过调用下游 API 获取真实输出。
