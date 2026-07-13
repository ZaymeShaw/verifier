# Evals Skill 重构方案 — 阶段 1：项目接入

## 背景

verifier 做了大规模架构升级（v2 协议），核心变化：
- 协议层硬约束：每个角色有 `_XxxProtocol`（模板方法，禁止覆盖）+ `ProjectXxx`（扩展点基类）
- adapter 只做中转：新 `ProjectAdapter` 只实现 `_load_*` 方法加载各协议实例，不再承载业务逻辑
- 已有合规检查：`scripts/check_adapter_compliance.py` 检查 adapter 是否符合新规范

evals skill 需要基于新架构重新设计"项目接入"流程。

## 设计原则

1. 只改 `impl/projects/<project>/`（接入时）：不碰 core、protocols、其他项目、前端
2. 唯一入口 `verifier/projects/<project>/project.yaml`：用户先在用户侧目录准备好项目知识索引
3. 新协议优先：新项目直接继承 `ProjectAdapter`（非 `LegacyProjectAdapter`）
4. 接入不碰算法层：只搭基础设施，judge/attribute 用协议默认实现，质量优化通过 attribute skill 的 draft 机制
5. 验收标准：合规检查 + 协议探针 + mock-check + run-chain + check1 回归

## 通用发现规则（贯穿全文）

本方案不写死具体函数/方法名、不写死基类文件名。统一从协议层搜索路径现场发现：
- 角色基类：`impl/core/<role>_protocol.py` 中的 `Project<Role>` 类
- 必须实现项：该类中被 `@abstractmethod` 标记的方法
- adapter 基类：在 `impl/core/` 下查找中转站形态的 `ProjectAdapter` 类（只有 `_load_*` 的那个，非 LegacyProjectAdapter），不写死文件名（`adapter_v2.py` 是迁移期临时命名，迁完会改回 `adapter.py`）
- adapter 加载方法命名规范：`_load_<role>`，每个对应一个 `Project<Role>` 实例
- live_schema 导出命名规范：`REQUEST_SCHEMA` / `EXTRACT_OUTPUT_SCHEMA` / `SCENARIO_ENUM` / `check`

协议升级（新增抽象方法、新增角色、基类文件改名）时，按搜索路径现场读取即可覆盖，方案文件无需同步修改。

## 目录结构

```
.claude/skills/evals/
├── SKILL.md
├── scripts/
│   ├── scaffold_project.py            # 动态生成项目骨架
│   └── verify_protocol_compliance.py  # 协议符合性探针
└── references/
    └── onboarding_acceptance.md       # 接入验收清单
```

不设 `references/templates/` 静态 .py 骨架目录——骨架由 scaffold 脚本现场生成，永远跟协议走。

## 各部分职责

**SKILL.md（正文）**
- 定位：evals 是 verifier 项目级 skill，核心职责是新项目接入
- 接入主流程 Step 0-10
- 通用发现规则（如上）
- 项目侧引用清单：区分"引用工程"vs"skill 自带"两类
- 门禁命令清单：每步跑哪个命令、什么算过

**scripts/scaffold_project.py（skill 自带）**
- 动态生成项目骨架，接入时用
- 流程：扫描 `impl/core/*_protocol.py` 发现所有 `Project<Role>` 类 → 读 `@abstractmethod` 拿必须实现项 → 现场生成 `<role>.py` stub → 动态发现 adapter 基类生成 adapter.py（`_load_*` 命名规范）→ 生成 live_schema.py + schema 骨架
- 协议变了生成内容自动变，不维护静态模板

**scripts/verify_protocol_compliance.py（skill 自带）**
- 协议符合性探针，门禁时用
- 流程：扫描发现所有 `Project<Role>` 类 → 确认项目实现了对应 `<role>.py` 和 `_load_<role>` → import 各 `<role>.py` 实例化，检查是否报 `TypeError: Can't instantiate abstract class`
- 自动从协议基类 `@abstractmethod` 现场读取要求，协议加新方法/新角色自动卡住项目

**references/onboarding_acceptance.md**
- 接入验收清单，可执行命令（硬门禁）
- 引用工程命令 + skill 自带脚本，跑过才算接入完成

## SKILL.md 引用清单（区分两类）

**引用工程（不复制不重写，口径以工程为准）**：
- `scripts/check_adapter_compliance.py` — adapter 合规检查
- `bash run.sh cli mock-check` — mock 数据 schema 校验
- `bash run.sh cli run-chain` — 单链跑通

**skill 自带（skill 维护）**：
- `scaffold_project.py` — 动态生成骨架
- `verify_protocol_compliance.py` — 协议符合性探针

## 不变量（先冻结，后续构建基于此）

**不变量：live_schema**
- 文件：`impl/projects/<project>/live_schema.py` + `schema/__init__.py`
- 按命名规范导出 REQUEST_SCHEMA、EXTRACT_OUTPUT_SCHEMA、SCENARIO_ENUM、check
- 是 mock 数据生成、live/judge/attr 校验的全部基础

> 注：ready 不是不变量，它是 project.yaml 的 `common.ready` 字段，用户填 project.yaml 时自然就带上了。`output` 在 ready 走 provided 模式，`reference` 在 ready judge 直接采信。

## 构建顺序

```
Step 0: 信息收集 — 读取 verifier/projects/<project>/project.yaml，确认 ready、api、场景
    ↓
Step 1: 跑 scaffold — bash run.sh python .claude/skills/evals/scripts/scaffold_project.py --project <id>
        （动态生成 live/mock/tools/judge/attribute/adapter/live_schema/schema 骨架）
    ↓
Step 2: 冻结 live_schema — 填充 schema dataclass + SCENARIO_ENUM + check（不变量，先冻结）
    ↓
Step 3: 填充 live.py — 参考 QA
Step 4: 填充 mock.py — 参考 QA
Step 5: 填充 tools.py — 可用默认实现
Step 6: 填充 judge.py — 实现 build_context
Step 7: 填充 attribute.py — 实现 build_context
Step 8: 填充 adapter.py — 确认 _load_* 齐全（scaffold 已生成）
    ↓
Step 9: 验证 — check_adapter_compliance + verify_protocol_compliance + mock-check + run-chain
    ↓
Step 10: mock 固化 — 生成 mock_cases.json 到 impl/data/<project>/
    ↓
Step 11: 纳入回归 — 更新 check1.py 配置
```

## 各步骤详情（每步给搜索路径 + 参考，不写死方法名）

- **Step 0 信息收集**：输入 project.yaml，理解业务场景/API/ready
- **Step 1 跑 scaffold**：一键生成全部骨架，协议变了生成内容自动变
- **Step 2 冻结 live_schema**：定义 dataclass + 按命名规范导出 + 创建 LiveSchemaCheck；参考 `impl/projects/QA/live_schema.py`
- **Step 3-8 填充各角色**：每步给搜索路径（`impl/core/<role>_protocol.py` → `Project<Role>` 的 `@abstractmethod`）+ 参考项目 QA
- **Step 9 验证**：跑四项门禁命令
- **Step 10 mock 固化**：遍历 SCENARIO_ENUM 生成 case 写入 `impl/data/<project>/mock_cases.json`
- **Step 11 纳入回归**：更新 `impl/checklist/check1.py` 的 CONFIG

## 关键边界

- 不修改 core 和 protocols：所有改动在 `impl/projects/<project>/` 内
- 新项目用 ProjectAdapter：不用 LegacyProjectAdapter（存量项目过渡用的）
- 不碰 algorithm 层质量：judge/attribute 只搭基础设施，质量优化通过 attribute skill 的 draft
- 不碰其他项目：只改当前接入的项目目录
- project.yaml 是唯一事实源：用户提供，skill 不自动生成
- 项目级 skill，和 verifier 强耦合，引用而非自建；工程有的不重复，工程缺的自己补
- skill 不自带工程已有能力的校验逻辑，不产生两套口径
- 项目脚本变更时，skill 的门禁命令跟着调整
- 不写死方法名和基类文件名，靠命名规范 + 搜索路径动态发现

## 文件清单

### 新建（skill 侧）
- `.claude/skills/evals/SKILL.md`（重写）
- `.claude/skills/evals/scripts/scaffold_project.py`
- `.claude/skills/evals/scripts/verify_protocol_compliance.py`
- `.claude/skills/evals/references/onboarding_acceptance.md`

### 保留不动
- `impl/core/`、`impl/protocols/`、`spec/`
- `.claude/skills/evals/agents/specialized/*`（专项审查，这次不重构）
- `.claude/skills/evals/agents/analyzer.md`（benchmark 无关遗留物，可后续清理）

## 验证方式

1. 现有项目不受影响：`bash run.sh cli projects` 确认所有项目仍可识别
2. 合规检查：`bash run.sh python scripts/check_adapter_compliance.py`
3. scaffold 验证：用模拟新项目跑 scaffold，确认生成骨架且能被 verify 通过
4. 协议探针：`bash run.sh python .claude/skills/evals/scripts/verify_protocol_compliance.py --project QA`（现有项目应通过）
5. 端到端：用模拟新项目跑完整接入流程，验证 mock-check 和 run-chain 通过