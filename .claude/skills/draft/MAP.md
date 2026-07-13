# Draft Skill 文件映射

执行者按需查找工具、模板和脚本。SKILL.md 只讲目标和思考方式。

## 公共

| 路径 | 用途 | 何时用 |
|---|---|---|
| `reference/draft_config_template.yaml` | config 骨架与字段说明 | 用户构造 config 时 |
| `reference/project_yaml_draft_switch_template.yaml` | project.yaml 灰度开关模板 | 配置 `<role>_draft.enabled` 时 |
| `reference/draft_report_template.md` | 结论报告模板 | 出具最终结论时 |
| `scripts/introspect_protocol.py` | 协议自省 | 写 draft 前查 `abstract_methods` |
| `scripts/check_draft.py` | draft 校验 | 验证可编译、可加载、协议完整、灰度可实例化 |

## Attribute

| 路径 | 用途 |
|---|---|
| `attribute/ROLE.md` | 角色定位、证据强度档位、工具边界 |
| `attribute/knowledge.md` | 链路地图、gap 模式、probe 库、被否决假设、泛化边界 |
| `attribute/scripts/compare_attribute.py` | current/draft 同数据运行器，保留原始 `AttributeResult` |

## Judge

| 路径 | 用途 |
|---|---|
| `judge/ROLE.md` | 角色定位、状态档位、工具边界 |
| `judge/knowledge.md` | 链路地图、gap 模式、probe 库、被否决假设、泛化边界 |
| `judge/scripts/compare_judge.py` | current/draft 同数据运行器，保留原始 `JudgeResult` |

## 项目侧产物

| 路径 | 用途 |
|---|---|
| `impl/projects/<project>/draft/<role>.py` | draft 实现，结构与 production 一致 |
| `impl/projects/<project>/draft/tools/` | draft 特异工具，遵守 `VerifiableTool` 协议 |
| `impl/projects/<project>/draft/probes/` | draft 特异 probe |
| `impl/projects/<project>/draft/context_builders/` | draft 特异上下文构建器 |
| `impl/projects/<project>/project.yaml` 的 `<role>_draft` | 灰度加载开关，promotion 后关闭 |

## 调用关系

```text
config.mock_source → 加载固定 case
introspect_protocol.py → draft 必须实现的 abstract_methods
draft/<role>.py → check_draft.py 校验
draft/<role>.py → compare_<role>.py 同数据运行
ROLE.md + knowledge.md → 探索/固化/积累参考
project.yaml <role>_draft → loader 灰度加载
```
