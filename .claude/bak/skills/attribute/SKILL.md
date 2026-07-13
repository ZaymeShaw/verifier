---
name: attribute
description: 审查 verifier 归因是否运行证据驱动、链路可定位、不过拟合，并生成可人工提升的离线 attribution draft。
---

# Attribute Skill

## 职责

`/attribute` 是归因质量门禁，不是项目 adapter。

- **审查模式**：检查现有归因链路/输出是否证据驱动、链路可定位、符合最小 `AttributeResult`。
- **draft 模式**：生成或优化 `impl/projects/<project>/draft/attribute.py` 与必要的 `draft/tools/`；draft 必须离线，不能自动进入 production。

不要把项目字段、枚举、业务链路特例或 case 经验沉淀进 skill。

## 通用门禁

任何审查结论或 draft 都必须满足：

1. **当前证据**：只使用当前 `RunTrace`、`JudgeResult`、actual、expected/reference、execution trace、runtime check、project tool/probe 或项目配置；prompt 声明不是证据。
2. **链路定位**：说明问题发生在哪个可观察阶段；证据不足就写缺口，不编造根因。
3. **最小协议**：只围绕 `expectation_attributions`、`suspected_locations`、`root_cause_hypothesis`、`evidence`、`evidence_strength`；不恢复旧字段。
4. **唯一标准**：项目已有 adapter comparison / semantic equivalence / runtime check / production tool 时，draft 只能复用或补充上下文，不能另造冲突 comparator。
5. **不过拟合**：不写 case id、样本序号、当前样本专属数值/文案、历史字段组合。
6. **强度校准**：
   - `strong`：当前 tool/probe/runtime check 明确显示 gap，且 expected/reference 与 actual 都存在。
   - `medium`：有当前证据，但缺关键链路验证。
   - `weak`：只有 judge 文本、部分 trace 或间接配置证据。
   - `none`：expected/reference、actual 或 judge 缺失。
7. **不伪造成功**：not_evaluable、证据缺失、tool/probe failed 不能包装成完整根因或 strong；fulfilled case 不能强行归因失败。
8. **draft 隔离**：不自动修改 production `attribute.py`、正式 tools、core、loader 或 production config；promotion 必须人工确认。

## 审查模式

检查范围按需覆盖：core attribute 协议/normalize/check/frontend/table、项目 `attribute.py`、adapter attribute hooks、project yaml/docs、相关 trace/test/API/run_chain 输出。

输出格式：

```markdown
## Attribute 审查结论

结论：通过 / 基本通过但有风险 / 不通过

### 已满足
- ...

### 问题
1. 问题：...
   - 证据：`file_path:line`
   - 影响：...
   - 修复建议：...

### 需要补验证
- ...

### 是否存在 hacking
- 是 / 否 / 暂未发现；理由：...
```

## draft 模式

进入条件：用户要求生成归因方案、补 draft attribute/tools，或明确提到 `impl/projects/<project>/draft/attribute.py`。

先读取用户指定的 draft config；没有配置时，用 `references/draft_config_template.yaml` 要求用户确认或补齐：project、多行 objective prompt、冻结 mock 数据源、material 资料来源、多行 review prompt、迭代上限。loop 过程中用户可随时用 prompt 调整需求；mock 数据只能随配置或用户明确要求改变。

流程：

1. 识别或读取 draft config：`project_id`、多行 objective、冻结 mock 数据源、material 资料来源、多行 review、迭代上限。
2. 按 `material` 收集归因资料，再确认 case 是 `fulfilled`、`not_fulfilled` 还是 `not_evaluable`。
3. 声明 draft 使用的项目证据源；优先复用 adapter/tool/config/runtime check。
4. 只写离线 draft：
   - `impl/projects/<project>/draft/attribute.py`
   - `impl/projects/<project>/draft/tools/`
5. draft attribute 暴露：`attribute_failure(spec, adapter, trace, judge_result) -> AttributeResult`。
6. 优先复用 `run_project_attribute_protocol` 与 adapter hooks。
7. 验证 draft：compile/import + 局部 probe；可行时跑 targeted `pipeline.run_chain` 或项目 API。
8. grep 检查 case marker；确认 `load_project_attribute()` 不加载 `draft/`。
9. 用配置中冻结的 mock 数据集对比当前 production attribute 与 draft attribute：同一批输入分别跑 current 与 draft，比较证据强度、链路定位、不过拟合、是否伪造 strong。
10. draft 未优于 current 时只优化 draft/tool；不得改 mock 数据，除非用户明确更新配置。
11. 输出一次性归因结论、对比报告、证据强度、缺失信息、promotion checklist。

### draft 自检

- [ ] 复用了项目已有 adapter/tool/config；未复用则说明原因。
- [ ] 只有一个 canonical 语义标准；draft tool 没有覆盖它。
- [ ] 无 case id、样本序号、当前样本专属数值/文案硬编码。
- [ ] fulfilled case 不会被强行归因失败。
- [ ] not_evaluable / missing evidence 不会产生 strong。
- [ ] `AttributeResult` 仍是最小字段。
- [ ] `draft/` 未被 production loader 自动加载。
- [ ] 已做 compile/import/局部 probe 或 targeted run；没做要说明原因。
- [ ] 已用配置中冻结的 mock 数据对比 current 与 draft；draft 没有更优时继续优化 draft 或记录 blocker。

### promotion checklist

- [ ] `draft/attribute.py` 可 import。
- [ ] `attribute_failure()` 返回最小 `AttributeResult`。
- [ ] 代表 case 的 targeted run 或局部函数验证通过。
- [ ] mock 对比报告显示 draft 在证据质量/链路定位/泛化风险上优于或不弱于 current。
- [ ] tool/probe failed 不会伪造 strong。
- [ ] production loader 不加载 `draft/`。
- [ ] 人工确认后才 promotion。

## draft 自循环

默认优化 draft，不优化 skill：

```text
生成/读取 config -> 冻结 mock 数据 -> 生成 draft -> 对比 current/draft -> 用户可补充需求 -> 修 draft/tool -> 再验证 -> draft 优于 current 或记录 blocker
```

只有通用门禁缺失时，才最小化更新 skill/template。项目缺 hook、字段映射不完整、业务链路需要专属 probe、case 数据异常，都不是修改 skill 的理由。mock 数据在 loop 中冻结；只能因用户明确要求或配置变更而更新。

## 模板要求

- `references/draft_config_template.yaml`：draft loop 初始化配置模板，固定 project、多行 objective、冻结 mock 数据、material 资料来源、多行 review 和迭代上限。
- `references/project_yaml_draft_switch_template.yaml`：项目 `project.yaml` 中的 draft attribute 启用开关模板；默认关闭，显式开启才使用 draft。
- `references/draft_attribute_template.py`：调用 `run_project_attribute_protocol`，返回最小 `AttributeResult`，默认复用 adapter context，明确 fulfilled 不强行归因、证据不足倾向 none/weak。
- `references/draft_tool_template.py`：要求声明 input/output、evidence type、canonical standard、boundary、validation。
- `references/draft_comparison_template.py`：对比 current attribute 与 draft attribute 在同一批 mock trace/judge 上的输出差异。
- `references/mock_dataset_template.py`：生成或加载项目 mock attribution cases；具体数据生成脚本落在项目 `draft/`。
- `references/draft_report_template.md`：对比报告模板；具体报告落在项目 `draft/`。

## 分工

- `/Bussiness`：业务期望。
- `/check`：标准化、协议对齐、数据/前后端一致性。
- `/aihacking`：投机取巧与伪通过。
- `/attribute`：归因证据、链路定位、最小协议、离线 draft。
