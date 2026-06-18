# Finding Format

每条 finding 输出格式：

```yaml
finding_id: <自动生成>
category: functional_defect | algorithm_capability_problem | design_architecture_defect | unmet_user_need | reproduction_record
severity: high | medium | low
user_impact: <用户角度的实际后果>
evidence_status: confirmed | partially_supported | hypothesis | unverified_reviewer_critique
evidence_refs: [<evidence_id 列表>]
source_checklist_item: <关联的 checklist item id，可选>
reproduction_steps: <复现步骤>
actual_result: <系统实际表现>
expected_result: <期望表现>
suspected_areas: [<代码/配置/协议 疑似区域>]
recommendation: <建议修复方向>
```

## Category 定义

| Category | 含义 |
|---|---|
| `functional_defect` | 按钮无效、页面报错、结果不出现、状态丢失、导航失败 |
| `algorithm_capability_problem` | 输出不对、不可行动、过于泛化、判断错误、归因不准 |
| `design_architecture_defect` | 流程割裂、数据不一致、职责不清、持久化脆弱、协议边界模糊 |
| `unmet_user_need` | 用户目标整体无法完成，无论单个功能是否正常 |
| `reproduction_record` | 已复现/无法复现的问题记录，附带复现链路 |

## 反模式（禁止）

- 不要写"系统整体可用""基本通过""无重大问题"
- 不要在没有证据的情况下标 confirmed
- 不要把子进程的 critique 直接当 confirmed finding
- 没发现问题时不要写"通过"，要写探了什么、为什么没确认、还有什么假设值得查
