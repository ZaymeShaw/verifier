"""
意图类型定义与映射表 — marketting-planning-intent 项目

此模块提供：
  - IntentType: 意图类型枚举（与外部系统 app/schemas/intent.py 一致）
  - INTENT_MAPPING: raw_intent 数值编码 → 意图名称的映射表
    数据来源：外部系统仓库 app/configs/config_dev.json

用法（runtime_query_tools.py）:
    from intent import INTENT_MAPPING, IntentType
    actual_mapping = INTENT_MAPPING.get("4001", "other")
    is_in_mapping = "4001" in INTENT_MAPPING
"""

from enum import Enum


class IntentType(str, Enum):
    """意图类型枚举 — 与外部系统 app/schemas/intent.py 保持一致"""
    team_portrait = "team_portrait"               # 队伍画像（分布）分析
    customer_portrait = "customer_portrait"       # 客户画像（分布）分析
    nbev_planning = "nbev_planning"               # NBEV达成路径规划分析
    target_value_adjustment = "target_value_adjustment"       # NBEV目标值调整
    achievement_measurement_adjustment = "achievement_measurement_adjustment"  # 达成测算路径调整
    nbev_planning_fallback = "nbev_planning_fallback"         # NBEV达成路径规划范围内的未支持意图
    other = "other"                               # 其他意图 — 完全超出NBEV规划范畴


# raw_intent 数值编码 → 意图名称的映射
# 数据来源：外部仓库 /Users/xiaozijian/WorkSpace/package/marketing-planning/app/configs/config_dev.json
INTENT_MAPPING: dict[str, str] = {
    "1001": "customer_portrait",
    "1002": "team_portrait",
    "1003": "nbev_planning",
    "1004": "target_value_adjustment",
    "1005": "achievement_measurement_adjustment",
    "1006": "nbev_planning_fallback",
    "4001": "other",
}