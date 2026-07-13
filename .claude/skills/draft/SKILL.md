---
name: draft
description: 离线优化项目层角色实现（attribute/judge/...），用 frozen mock 数据对比 current vs draft，draft 优于 current 才允许 promotion。不自动改 production 代码。
---

# Draft Skill

## 职责

按 `verifier/spec/draft/draft.md` 落地离线 draft 优化机制。本文件是 spec 的执行入口，不重述 spec 内容——遇到机制细节以 spec 为准。

## spec 对齐

- **机制本体**：`verifier/spec/draft/draft.md`（7 阶段 + 3 硬约束 + 3 case 契约 + decision_rule + promotion 人工确认）
- **角色无关部分（公共层写死）**：7 阶段流程、config 字段骨架、3 条硬约束、3 条 case 契约、decision_rule、promotion 人工确认
- **角色特异部分（角色层填，draft 机制不预判）**：case 具体字段、`_run_<role>`、`_result_summary`、`_case_status`、角色特异门禁、角色特异 tool 边界、角色特异"伪造强度"判定

## 用户操作流程

### 准备

确认目标项目 `<project>` 和要 draft 的角色 `<role>`（attribute / judge）。draft skill 不预先判定扩展点清单——开始前先跑协议自省拿到当前 `ProjectXxx` 方法表。

### 步骤 1：建 draft 目录

在 `impl/projects/<project>/` 下建 `draft/` 子目录（若不存在）。draft 目录**只放 draft 实现本身**，不混 skill 配置、mock 数据、对比报告：

```
impl/projects/<project>/draft/
├── __init__.py
├── <role>.py          # 步骤 5 写：draft 实现
└── tools/             # 步骤 5 写（如需要）
    ├── __init__.py
    └── <tool>.py
```

其他产物的位置：
- **config**：不落盘。用户在对话里给（贴 yaml 内容或指向某个临时位置），skill 在运行时读，不写进项目 draft 目录。
- **mock 数据**：用项目已有的 trace/fixtures/run_chain 输出，`config.mock_source` 字段指向它。不另生成冻结副本——冻结的是"loop 中不改 mock_source 指向的数据"，不是"再生成一份"。
- **对比报告**：运行时产物，按 `config.report_path` 输出（默认 `impl/projects/<project>/draft/<role>_comparison_report.md`）。

### 步骤 2：填 config

config **不落盘**到项目 draft 目录——在对话里给 skill（贴 yaml 内容或指向临时位置），skill 运行时读。字段定义见 `.claude/skills/draft/reference/draft_config_template.yaml`，按下表填：

| 字段 | 必填 | 说明 | 不填的后果 |
|---|---|---|---|
| `project_id` | 是 | 目标项目 id，对应 `impl/projects/<project>/` | 跑不起来，找不到项目 |
| `role` | 是 | 当前 draft 角色：`attribute` / `judge` | 跑不起来，找不到协议 |
| `objective` | 是 | 多行 prompt，说明本轮 draft 要解决什么问题、约束、偏好 | draft 实现无方向，自检无法判定是否达成目标 |
| `mock_source` | 是 | mock 数据来源，指向**项目已有的** trace/fixtures/run_chain 输出（路径如 `tmp/<run_chain 输出>/` 或 `impl/projects/<project>/fixtures/cases.py`）。不另生成冻结副本——冻结的是"loop 中不改 mock_source 指向的数据"，不是"再生成一份" | 没有冻结 case，无法对比 |
| `material` | 是 | 资料来源清单（path + note），用于建立项目理解，不是 case 数据 | draft 实现脱离项目实际，可能另造 comparator |
| `mock_frozen` | 是 | 必须为 `true`。loop 中不改 mock_source 指向的数据，要改必须用户明确更新 config | 改成 false 违反 spec 阶段 2 case 契约 3，无法防伪造 |
| `review` | 是 | 多行 prompt，每行一个评审原则（如"泛化能力""准确性""可用性"） | decision_rule 缺评审依据，promotion 判定主观 |
| `max_iterations` | 是 | 整数，loop 上限。建议 3-5 | 跑死循环 |
| `report_path` | 否 | 对比报告输出路径，默认 `impl/projects/<project>/draft/<role>_comparison_report.md` | 报告落在默认位置 |

字段填完确认 `mock_frozen: true`，否则违反 spec。

### 步骤 3：协议自省

跑自省脚本拿当前协议方法表：

```bash
$(读取 impl/config.yaml 的 python.executable) .claude/skills/draft/scripts/introspect_protocol.py --pretty impl/core/<role>_protocol.py
```

输出 JSON，关注 4 个字段：

- `template_methods`：模板方法（`@final`，**不可覆盖**）
- `internal_methods`：`_` 前缀内部方法（**不可覆盖**）
- `abstract_methods`：`@abstractmethod`（draft **必须实现**）
- `optional_methods`：普通扩展点（可选覆盖）

把这 4 个字段记下来，步骤 5 写 draft 实现时按图施工。

### 步骤 4：加载冻结 mock case

按 config 的 `mock_source` 加载 case 集（**不另生成冻结副本**——直接读已有数据，冻结的是"loop 中不改这份源数据"）。case 字段**从当前 `ProjectXxx` 模板方法签名派生**（见对应角色的 ROLE.md "case 字段" 章节），不预定义。

加载方式按 `mock_source` 指向的数据形态：

- **trace 文件目录**（如 `tmp/<run_chain 输出>/`）：按文件名解析成 `RunTrace` 列表；attribute 角色需要配对 `JudgeResult`（同 trace_id 的 judge 文件）。
- **fixtures 脚本**（如 `impl/projects/<project>/fixtures/cases.py`）：直接 import 调用其返回 case 列表的函数。
- **显式 case 列表**（如 `.json` 或 `.py`）：直接读，按 `case_key` / `trace` / `judge_result` 等字段解析。

加载完成立即建立冻结基线：对 `mock_source` 参与评测的源文件和序列化 case 内容计算 SHA-256 清单；每轮运行前后重算，变化则终止 loop。用户明确更新 config 后才可建立新基线。

每个 case 必须满足 spec 阶段 2 的 3 条契约：

1. 装跑一次 draft 所需全部入参（从模板方法签名派生）。
2. 带"期望"（`expected_check` 字段，用户给，不由 skill 猜）。
3. 冻结——mock_source 指向的源数据 loop 中不改。

如果 mock_source 指向的数据没有 `expected_check` 字段，skill 在加载时提示用户补——case 必须带期望，否则对比无判定依据。

### 步骤 5：写 draft 实现

以当前 `impl/projects/<project>/<role>.py` 为源文件，直接复制到 `impl/projects/<project>/draft/<role>.py`，再只修改实现内容。`.claude/skills/draft/reference/draft_role_template.py` 仅用于理解协议扩展点布局，不能替代当前 production 文件作为生成源。按步骤 3 自省结果检查：

1. 保持 draft 文件与当前 production `<role>.py` 的公开结构完全一致：顶层入口函数、公开类名、构造参数和扩展点签名都不改；draft 只改实现内容，确保 promotion 可直接文件覆盖，不需要再改名或改结构。
2. 实现所有 `abstract_methods`（必须）。
3. 按需覆盖 `optional_methods`（可选，没需求的不写）。
4. 不要碰 `template_methods` 和 `internal_methods`——`__init_subclass__` 会硬报错。
5. 如需 tool：在 `build_context` 返回的 `tools` 里挂项目特异 tool（来自 `draft/tools/`），用现有 `impl/tools/protocol.py` 的 `VerifiableTool` / `ToolResult`，不另造。

角色特异的 tool 边界（如 judge 默认屏蔽内部代码）见对应 ROLE.md。

### 步骤 6：自检

按 spec 阶段 4 的 8 条自检项检查 draft 实现：

- [ ] draft 继承 `ProjectXxx`，未覆盖模板方法/内部方法（`__init_subclass__` 通过）。
- [ ] 当前协议所有 `@abstractmethod` 都实现了（对照步骤 3 自省结果）。
- [ ] 入口签名（模板方法）和正式版一致——loader 切换无感。
- [ ] 无 case id / 样本序号 / 当前样本专属数值硬编码。
- [ ] 不伪造强度（角色特异档位见 ROLE.md）。
- [ ] fulfilled case 不被强行失败。
- [ ] tool（如有）经 `ToolRegistry` + agno 桥接，不经项目 adapter 中转。
- [ ] draft 落在 `draft/`，loader 默认不加载。
- [ ] judge draft 的 `build_context` 如返回 tools，已逐个确认只处理业务输入输出；任何读取项目源码、文件路径、符号表或代码搜索结果的能力均自检失败。
- [ ] 已做 compile/import + 局部 probe 或 targeted run。

任一项不过 → 修 draft，回到自检。

### 步骤 7：跑 current vs draft 对比

用角色层对比脚本跑。case 从步骤 4 加载的 mock_source 来：

```python
# 在对话里跑（不落盘到 draft 目录，避免污染项目结构）
from impl.core.project_loader import load_project_spec
from impl.projects.<project>.<role> import CurrentXxx  # 正式版实现
from impl.projects.<project>.draft.<role> import DraftXxx  # draft 实现
from impl.projects.<project>.fixtures.cases import load_cases  # mock_source 指向的加载器

# 角色层对比脚本
import importlib.util
spec = importlib.util.spec_from_file_location(
    "compare_<role>",
    ".claude/skills/draft/<role>/scripts/compare_<role>.py"
)
compare_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare_mod)

project_spec = load_project_spec("<project>")
adapter = ...  # 项目 adapter
cases = load_cases()  # 按 mock_source 指向的数据加载

current_impl = CurrentXxx(project_spec)
draft_impl = DraftXxx(project_spec)

result = compare_mod.compare_<role>_outputs(project_spec, adapter, cases, current_impl, draft_impl)
print(result["decision_rule"])
for row in result["rows"]:
    print(row["case_key"], row["comparison"], row["current_check"], row["draft_check"])
```

对比逻辑按 spec 阶段 5：用 `expected_check` 判断 current/draft 哪边符合期望，再审查证据质量、链路定位（attribute）、判定准确性（judge）、不过拟合和不伪造。异常直接冒泡并终止本次对比，不生成可用于 promotion 的报告。

### 步骤 8：判定 + loop / promotion

看对比结果：

- **draft 更优**（任一维度优于 current 且不弱于其他，且不伪造、不 overfit）：出对比报告 + promotion checklist，**等用户人工确认**。
- **draft 不更优**：用户用 prompt 调整需求 → 修 draft/tool → 回步骤 6 自检 → 回步骤 7 对比。
- **达 `max_iterations` 仍未更优**：记录 blocker，出报告，不 promotion。

**promotion 必须人工确认**，skill 不自动执行：

1. 直接覆盖 `draft/<role>.py` → `<role>.py`（公开入口、类名和签名已与 production 一致，不做二次改写）。
2. 搬移 `draft/tools/` → `tools/`（production）。
3. `project.yaml` 中 `<role>_draft.enabled` 设为 `false`（或删除）。

### 步骤 9（可选）：一次性结论

promotion 前作为 preview，输出 draft 实现摘要、自检结果、对比报告、缺失信息、promotion checklist。

## 通用门禁（角色无关）

按 spec 阶段 4 自检 + 阶段 5 对比 + 阶段 6 promotion，角色无关部分：

- **协议合规**：继承 `ProjectXxx`，不覆盖模板方法和内部方法（`__init_subclass__` + `_FORBIDDEN_OVERRIDES` 硬约束），实现当前协议所有 `@abstractmethod`（清单由自省给出，不预判）。
- **mock 冻结校验**：加载 case 后、每次迭代运行前后，对 `mock_source` 下参与评测的文件计算 SHA-256 清单；任何摘要变化立即终止 loop。若 `mock_source` 是 Python loader，同时对 loader 文件及其明确返回的序列化 case 内容计算摘要。用户明确更新 config 后才建立新基线。
- **当前证据**：只用当前 `RunTrace` / `JudgeResult` / `AttributeResult` / actual / expected / reference / execution trace / runtime check / project tool/probe；prompt 声明不是证据。
- **唯一标准**：项目已有 adapter comparison / semantic equivalence / runtime check / production tool 时，draft 只能复用或补充上下文，不能另造冲突 comparator。
- **不过拟合**：不写 case id、样本序号、当前样本专属数值/文案、历史字段组合。
- **不伪造**：tool/probe/runtime check failed、expected/reference/actual 缺失不产生高强度结论；fulfilled case 不被强行失败。角色特异档位（attribute 的 strong/medium/weak/none；judge 的 fulfilled/not_fulfilled/not_evaluable）和角色特异"伪造"判定见 ROLE.md。
- **draft 隔离**：`draft/<role>.py` 和 `draft/tools/` 不被 production loader 自动加载；draft 文件保持与 production 相同的公开入口、类名和签名，promotion 经人工确认后直接覆盖 production 文件。
- **异常不吞**：对比脚本异常直接冒泡并终止本次对比，不生成可用于 promotion 的报告。

## 角色特异门禁

角色特异门禁由角色层 ROLE.md 给，不在 SKILL.md 预判：

- **attribute**：见 `attribute/ROLE.md` —— 链路定位、证据强度档位、fulfilled case 不归因失败等。
- **judge**：见 `judge/ROLE.md` —— 业务期望提取、判定状态档位、not_evaluable 不伪造为 fulfilled 等。

## 目录结构

```
.claude/skills/draft/
├── SKILL.md                          # 本文件：执行入口，指向 spec
├── reference/                        # 模板与文档（角色无关）
│   ├── draft_config_template.yaml    # 阶段 0 config 骨架（步骤 2 复制）
│   ├── draft_role_template.py        # 阶段 3 继承式骨架（步骤 5 复制）
│   ├── project_yaml_draft_switch_template.yaml  # 阶段 6 promotion 开关
│   └── draft_report_template.md      # 阶段 5 对比报告模板
├── scripts/                          # 公共可执行脚本
│   └── introspect_protocol.py        # 协议自省脚本
├── attribute/                        # attribute 角色层
│   ├── ROLE.md                       # 角色定位、强度档位、tool 边界、角色特异门禁
│   └── scripts/
│       └── compare_attribute.py      # _run_attribute / _result_summary / _case_status / compare_attribute_outputs
└── judge/                            # judge 角色层
    ├── ROLE.md                       # 角色定位、状态档位、tool 边界、角色特异门禁
    └── scripts/
        └── compare_judge.py          # _run_judge / _result_summary / _case_status / compare_judge_outputs
```

## 分工

- `/Bussiness`：业务期望。
- `/check`：标准化、协议对齐、数据/前后端一致性。
- `/aihacking`：投机取巧与伪通过。
- `/attribute`：当前归因审查 skill（保留，draft skill 不动它）。
- `/draft`：离线 draft 优化与对比，跨角色通用机制。角色相关细节在子目录 `attribute/`、`judge/` 的 ROLE.md + scripts 中。

## 注意

- **不预判扩展点清单**：自省脚本读取当前 `*_protocol.py` 拿方法表，协议演进时重新调用。
- **不预判 case 字段**：case 字段从当前 `ProjectXxx` 模板方法签名 + 扩展点签名派生。
- **不预判 result_summary 字段**：`_result_summary` / `_case_status` 由角色层根据当前 `XxxResult` schema 填。
- **不动 production**：promotion 之前所有改动只在 `draft/` 下。
- **不动现有 attribute skill**：draft skill 独立运作，目标是最终把 attr/judge 的 draft 都融合进来，但当前阶段保留 attribute skill 不动。
- **异常不吞**：对比脚本异常直接冒泡并终止本次对比，不生成可用于 promotion 的报告。
