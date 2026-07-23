---
doc_type: requirements
schema_version: 1
---

# 客户搜索配置需求

- 业务目标：依据当前业务字段、枚举和映射规则生成语义正确的客户搜索条件。
- 范围：字段选择、枚举值、操作符、查询逻辑及可执行的语义等价关系。
- 非目标：不把某台开发机的目录、历史标准答案或下游数据库不可控限制作为运行配置。
- 核心场景：自然语言条件解析、字段枚举匹配、组合查询和能力边界判断。

# 项目代码

`${CLIENT_SEARCH_REPO}`

# 重要配置文件

配置文件：
`${CLIENT_SEARCH_REPO}/src/main/python/config/enhanced_rules_args.yaml`
`${CLIENT_SEARCH_REPO}/src/main/python/config/field_definitions_args.yaml`
`${CLIENT_SEARCH_REPO}/src/main/python/config/field_enums_args.yaml`
`${CLIENT_SEARCH_REPO}/src/main/python/config/intent_summary_labels_args.yaml`
`${CLIENT_SEARCH_REPO}/src/main/python/config/value_mappings_args.yaml`

字段定义信息：
`${CLIENT_SEARCH_REPO}/src/main/python/config/field_definitions_args.yaml`：下游字段定义
`${CLIENT_SEARCH_REPO}/src/main/python/config/field_enums_args.yaml`：下游字段枚举值
