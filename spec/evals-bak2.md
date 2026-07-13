# Evals Skill 重构方案 — 阶段 1：项目接入

## 背景

verifier 做了大规模架构升级（v2 协议），核心变化：
- 协议层硬约束：每个角色有 `_XxxProtocol`（模板方法，禁止覆盖）+ `ProjectXxx`（扩展点基类）
- adapter 只做中转：新 `ProjectAdapter` 只实现 `_load_*` 方法加载各协议实例，不再承载业务逻辑
- 已有模板：`templates/new_project/` 提供了 adapter/judge/attribute 模板
- 已有合规检查：`scripts/check_adapter_compliance.py` 检查 adapter 是否符合新规范

evals skill 需要基于新架构重新设计"项目接入"流程。

## 设计原则

1. 只改 `impl/projects/<project>/`：不碰 core、protocols、其他项目、前端
2. 唯一入口 `verifier/projects/<project>/project.yaml`：用户先在用户侧目录准备好项目知识索引（业务资料、API 信息、启动方式等）
3. 新协议优先：新项目直接继承 `ProjectAdapter`（非 `LegacyProjectAdapter`）
4. 接入不碰算法层：只搭基础设施，judge/attribute 用协议默认实现，后续通过 attribute skill 的 draft 机制优化
5. 验收标准：mock-check 通过 + 单链跑通 + 纳入 check1 回归

## 通用发现规则（贯穿全文）

本方案不写死具体函数/方法名。每个角色文件要实现什么，统一从协议层搜索路径现场发现：

- 角色基类位置：`impl/core/<role>_protocol.py` 中的 `Project<Role>` 类
- 必须实现项：该类中被 `@abstractmethod` 标记的方法
- adapter 加载方法：`impl/core/adapter_v2.py` 中 `ProjectAdapter` 的 `@abstractmethod`，命名规范为 `_load_<role>`，每个对应一个 `Project<Role>` 实例
- live_schema 导出：按命名规范（`REQUEST_SCHEMA` / `EXTRACT_OUTPUT_SCHEMA` / `SCENARIO_ENUM` / `check`）

协议升级（新增抽象方法、新增角色）时，按搜索路径现场读取即可覆盖，方案文件无需同步修改。

## 新架构下的项目文件清单

| 文件 | 继承自 | 必须实现的来源（搜索路径） | 参考（最简样板） |
|------|--------|---------------------------|------------------|
| `adapter.py` | `ProjectAdapter` | `impl/core/adapter_v2.py` 中 `ProjectAdapter` 的 `@abstractmethod`（`_load_*` 命名规范） | `templates/new_project/adapter.py`（改用 ProjectAdapter） |
| `live.py` | `ProjectLive` | `impl/core/live_protocol.py` 中 `ProjectLive` 的 `@abstractmethod` | `impl/projects/QA/live.py` |
| `mock.py` | `ProjectMock` | `impl/core/mock_protocol.py` 中 `ProjectMock` 的 `@abstractmethod` | `impl/projects/QA/mock.py` |
| `judge.py` | `ProjectJudge` | `impl/core/judge_protocol.py` 中 `ProjectJudge` 的 `@abstractmethod` | `impl/projects/QA/judge.py` |
| `attribute.py` | `ProjectAttribute` | `impl/core/attribute_protocol.py` 中 `ProjectAttribute` 的 `@abstractmethod` | `impl/projects/QA/attribute.py` |
| `tools.py` | `ProjectTools` | `impl/core/tools_protocol.py` 中 `ProjectTools` 的 `@abstractmethod` | `impl/projects/QA/tools.py` |
| `live_schema.py` | — | 按命名规范导出 | `impl/projects/QA/live_schema.py` |
| `schema/__init__.py` | — | dataclass 定义 | `impl/projects/QA/schema/__init__.py` |

配置文件：`project.yaml`（实现侧配置：api、frontend_extensions、implementation_standard 等）

文档（可选）：`application.md` / `evaluation.md` / `mock.md` / `judge_boundary.md` / `attribution.md` / `checklist.md`

## 不变量（先冻结，后续构建基于此）

**不变量 1：live_schema**
- 文件：`impl/projects/<project>/live_schema.py` + `schema/__init__.py`
- 按命名规范导出 REQUEST_SCHEMA（dataclass）、EXTRACT_OUTPUT_SCHEMA（dataclass）、SCENARIO_ENUM（list[str]）、check（LiveSchemaCheck 实例）
- 是 mock 数据生成、live/judge/attr 校验的全部基础


## 构建顺序

```
Step 0: 信息收集 — 读取 verifier/projects/<project>/project.yaml，确认 ready、api、场景
↓
Step 1: 冻结 live_schema — schema/__init__.py + live_schema.py（按命名规范导出）
↓ (schema 是后续所有代码的输入类型来源)
Step 2: live.py — ProjectLive 子类
↓
Step 3: mock.py — ProjectMock 子类
↓
Step 4: tools.py — ProjectTools 子类（可按协议默认实现）
↓
Step 5: judge.py — ProjectJudge 子类
↓
Step 6: attribute.py — ProjectAttribute 子类
↓
Step 7: adapter.py — ProjectAdapter 子类（按 _load_* 命名规范）
↓
Step 8: 验证 — check_adapter_compliance + mock-check + run-chain 单链
↓
Step 9: mock 固化 — 生成 mock_cases.json 到 impl/data/<project>/
↓
Step 10: 纳入回归 — 更新 check1.py 配置
```

## 各步骤详情

**Step 0: 信息收集**
- 输入：`verifier/projects/<project>/project.yaml`
- 操作：理解业务场景、API 配置、ready 声明
- 产出：项目信息摘要
- 验收：能正确读取 project.yaml 的关键字段

**Step 1: 冻结 live_schema**
- 输入：project.yaml 的 `common.api` + 业务需求文档
- 操作：定义 dataclass + 按命名规范导出 + 创建 LiveSchemaCheck
- 产出：`schema/__init__.py` + `live_schema.py`
- 验收：导出齐全，`LiveSchemaCheck` 可实例化
- 参考：`impl/projects/QA/live_schema.py`、`impl/projects/QA/schema/__init__.py`

**Step 2: live.py**
- 搜索路径：`impl/core/live_protocol.py` → `ProjectLive` 的 `@abstractmethod`
- 参考：`impl/projects/QA/live.py`
- 注：纯离线评估项目（ready 含 output）参考 QA，无需真实 API 调用

**Step 3: mock.py**
- 搜索路径：`impl/core/mock_protocol.py` → `ProjectMock` 的 `@abstractmethod`
- 参考：`impl/projects/QA/mock.py`（最简）

**Step 4: tools.py**
- 搜索路径：`impl/core/tools_protocol.py` → `ProjectTools` 的 `@abstractmethod`
- 参考：`impl/projects/QA/tools.py`
- 注：接入阶段可按协议默认实现

**Step 5: judge.py**
- 搜索路径：`impl/core/judge_protocol.py` → `ProjectJudge` 的 `@abstractmethod`
- 参考：`impl/projects/QA/judge.py`、`templates/new_project/judge.py`

**Step 6: attribute.py**
- 搜索路径：`impl/core/attribute_protocol.py` → `ProjectAttribute` 的 `@abstractmethod`
- 参考：`impl/projects/QA/attribute.py`、`templates/new_project/attribute.py`

**Step 7: adapter.py**
- 搜索路径：`impl/core/adapter_v2.py` → `ProjectAdapter` 的 `@abstractmethod`（`_load_*` 命名规范）
- 参考：`templates/new_project/adapter.py`（改用 ProjectAdapter）
- 验收：`scripts/check_adapter_compliance.py --project <id>` 通过，实例化不报错

**Step 8: 验证**
```bash
bash run.sh python scripts/check_adapter_compliance.py --project <id>
bash run.sh cli mock-check --project <id>
bash run.sh cli run-chain --project <id> --mock --input '<REQUEST_SCHEMA 形状的 JSON>'
```
- 验收：三项全部通过

**Step 9: mock 固化**
- 操作：遍历 SCENARIO_ENUM，调 mock_build_intent 生成 case，写入 `impl/data/<project>/mock_cases.json`
- 验收：mock_cases.json 存在且 mock-check 通过

**Step 10: 纳入回归**
- 操作：更新 `impl/checklist/check1.py` 的 CONFIG，加入新项目
- 验收：check1 能识别新项目

## 模板补全

`templates/new_project/` 当前缺 live.py / mock.py / tools.py / live_schema.py / schema/。接入流程在 skill 的 `references/` 下补全这些骨架（按命名规范，不写死业务），让接入时可直接拷贝填充。不直接落盘到 `templates/`（保持 templates 由工程维护）。

## evals SKILL.md 重构

新结构：

```
.claude/skills/evals/
├── SKILL.md                          # 总入口，按阶段路由
├── agents/
│   ├── specialized/
│   │   ├── attribute-analyzer.md     # 保留
│   │   └── check.md                  # 保留
│   └── stages/
│       └── project-onboarding.md     # 新增，阶段 1：项目接入
└── references/
└── onboarding_checklist.md       # 新增，接入验收清单
```

SKILL.md 核心内容：evals 是业务测评系统生命周期管理 skill。Claude 根据用户意图判断阶段，加载对应 agent 文档。

阶段路由：
- "新增项目"/"接入项目"/"onboard" → `agents/stages/project-onboarding.md`
- "归因优化"/"draft"/"attribute" → `agents/specialized/attribute-analyzer.md`
- "代码审查"/"标准化"/"check" → `agents/specialized/check.md`
- "回归测试"/"check1" → 执行 check1 流程

agents/stages/project-onboarding.md 核心内容：执行 pipeline（Claude 按序执行，每步完成后汇报用户确认再进入下一步）：信息收集 → 冻结 schema → 构建 live/mock/tools/judge/attribute/adapter → 验证 → mock 固化 → 纳入回归 → 输出总结。每个步骤附带：输入 / 操作 / 产出 / 验收 / 搜索路径 / 参考（QA 的实现路径）。

## 关键边界

- 不修改 core 和 protocols：所有改动在 `impl/projects/<project>/` 内
- 新项目用 ProjectAdapter：不用 LegacyProjectAdapter（那是存量项目过渡用的）
- 不碰 algorithm 层质量：judge/attribute 只搭基础设施，质量优化通过 attribute skill 的 draft
- 不碰其他项目：只改当前接入的项目目录
- project.yaml 是唯一事实源：用户提供，skill 不自动生成

## 文件清单

新建：
- `.claude/skills/evals/agents/stages/project-onboarding.md`
- `.claude/skills/evals/references/onboarding_checklist.md`

修改：
- `.claude/skills/evals/SKILL.md`：重构为生命周期管理总入口

保留不动：
- `impl/core/`、`impl/protocols/`、`templates/`、`scripts/`
- `.claude/skills/evals/agents/specialized/*`
- `.claude/skills/evals/agents/analyzer.md`（benchmark 分析器，与 verifier 业务无关，可后续清理）

## 验证方式

1. 现有项目不受影响：`bash run.sh cli projects` 确认所有项目仍可识别
2. 合规检查：`bash run.sh python scripts/check_adapter_compliance.py` 确认现有项目不报新违规
3. 端到端：用一个模拟新项目，从 project.yaml 开始跑完整流程，验证 mock-check 和 run-chain 通过





------------


你说得对,光写个 SKILL.md 文字流程,确实约束不住——Claude 每次执行都靠"读文档自己理解",容易漂移、容易漏步骤、协议变了也不会自动发现。要让它**切实稳定作用**,得有能被机器/流程校验的"硬约束产物"。

结合之前讨论的"搜索路径 + 命名规范",真正能产生约束的是这几类东西:

## 能产生约束的产物

**1. 合规校验脚本(已有的复用)**
`scripts/check_adapter_compliance.py` 已经能检查 adapter 是否符合新协议规范(禁止业务方法、只允许 `_load_*`)。接入流程把它当硬门禁,不通过就卡住。这已经是现成的、能自动发现违规的约束,不用重造。

**2. 协议符合性探针(自动发现必须实现项)**
一个脚本,import 项目的 `<role>.py`,实例化继承类,看是否还报 `TypeError: Can't instantiate abstract class`。这一步直接从协议基类的 `@abstractmethod` 现场读取当前要求,协议加了新方法就自动卡住新项目——这就是你要的"协议演进自动感知",而且是用运行时校验实现,不靠文档维护。

**3. 接入验收配置**
一份声明"接入到此项目算完成"的最小验收清单,挂在项目侧或 skill references 下,内容是几条**可执行的检查命令**:
- `check_adapter_compliance --project <id>` 通过
- 各角色实例化不报 abstract 错
- `mock-check` 通过
- `run-chain` 单链通过

这些是命令,不是描述性文字——跑过才算数。

**4. 模板骨架(复用 templates/new_project/)**
`templates/new_project/` 已有 adapter/judge/attribute 骨架。接入时拷贝填充,保证结构对齐。缺的 live/mock/tools/live_schema 骨架补到 references 下。

## 所以目录该长这样

```
.claude/skills/evals/
├── SKILL.md                          # 接入主流程 + 约束说明
└── references/
├── onboarding_acceptance.md      # 可执行验收命令清单(硬门禁)
├── templates/                    # 缺失的骨架(live/mock/tools/live_schema)
│   ├── live.py
│   ├── mock.py
│   ├── tools.py
│   └── live_schema.py
└── probe.py                      # 协议符合性探针(实例化校验)
```

核心思路:**约束不靠"文档叮嘱 Claude",靠"可执行的校验脚本 + 骨架模板"**。Claude 按流程填,填完跑校验,校验是硬的、自动的、协议演进时自动失效的。`scripts/check_adapter_compliance.py` 这种已有的就复用,不重造。

这个方向对吗?如果对,SKILL.md 正文重点就是:接入步骤 + 每步对应的约束命令。






-----------



基于"verifier 项目级 skill"定位，完整目录构建方案如下：

## 目录结构

```
.claude/skills/evals/
├── SKILL.md
├── scripts/
│   └── verify_protocol_compliance.py
└── references/
├── templates/
│   ├── live.py
│   ├── mock.py
│   ├── tools.py
│   └── live_schema.py
└── onboarding_acceptance.md
```

## 各部分职责

**SKILL.md（正文）**
- 定位说明：evals 是 verifier 项目级 skill，核心职责是新项目接入
- 接入主流程 Step 0-10：信息收集 → 冻结 live_schema → 按角色构建 → adapter → 验证 → mock 固化 → 纳入回归
- 通用发现规则：角色文件要实现什么，从 `impl/core/<role>_protocol.py` 的 `Project<Role>` 类 `@abstractmethod` 现场发现，协议演进自动覆盖，不写死方法名
- 项目侧引用清单：明确区分两类依赖（见下）
- 门禁命令清单：每步跑哪个命令、什么算过

**scripts/**
- skill 自有的脚本：工程里没有、但接入流程需要的
- 核心是 `verify_protocol_compliance.py`（协议符合性探针）：import 项目各 `<role>.py`，实例化继承类，检查是否还报 `TypeError: Can't instantiate abstract class`。自动从协议基类 `@abstractmethod` 现场读取要求，协议加了新方法就自动卡住新项目
- 这些脚本是 skill 的一部分，不是工程产物

**references/templates/**
- 只放工程 `templates/new_project/` 没覆盖的骨架：live.py / mock.py / tools.py / live_schema.py
- 按命名规范，不写死业务，接入时拷贝填充
- 说明：工程模板的补充非替代，工程补齐后退役

**references/onboarding_acceptance.md**
- 接入验收清单，内容是可执行命令（硬门禁）
- 既引用工程命令，也引用 skill 自带脚本
- 跑过才算接入完成

## SKILL.md 引用清单要区分两类

- **引用工程（不复制不重写，口径以工程为准）**：
- `scripts/check_adapter_compliance.py` — adapter 合规检查
- `bash run.sh cli mock-check` — mock 数据 schema 校验
- `bash run.sh cli run-chain` — 单链跑通
- `templates/new_project/` — adapter/judge/attribute 骨架
- **skill 自带（skill 维护）**：
- `verify_protocol_compliance.py` — 协议符合性探针（工程现有脚本不覆盖的能力空白）

## 不进 skill 目录的东西

- 工程已有的审查脚本 → 工程侧 `scripts/`，skill 只引用
- 工程已有的模板 → 工程侧 `templates/new_project/`，skill 只引用
- core/protocols → 不碰

## 关键边界

- 项目级 skill，和 verifier 强耦合，引用而非自建
- 工程有的不重复，工程缺的自己补——两个原则同时满足
- 唯一耦合点是 SKILL.md 的"项目侧引用清单"——写清楚引用了什么、谁维护、口径谁说了算
- skill 不自带工程已有能力的校验逻辑，不会和项目脚本产生两套口径
- 项目脚本变更时，skill 的门禁命令跟着调整





---------------


按 verifier/spec/evals.md 实现 evals skill。spec 已定稿，核心思想：约束靠可执行脚本 + 骨架模板，不靠文档叮嘱。

设计原则

1. 只改 impl/projects/<project>/（接入时），skill 本身落在 .claude/skills/evals/
2. 唯一入口 verifier/projects/<project>/project.yaml
3. 新项目直接继承 ProjectAdapter（非 LegacyProjectAdapter）
4. 不写死方法名，通过命名规范 + @abstractmethod 动态发现协议要求，协议演进自动覆盖
5. 接入不碰算法层质量，judge/attribute 只搭基础设施，质量优化通过 attribute skill 的 draft
6. 验收标准：合规检查 + 协议探针 + mock-check + run-chain + check1 回归

通用发现规则（贯穿全文）

不写死具体函数/方法名，从协议层搜索路径现场发现：
- 角色基类：impl/core/<role>_protocol.py 中的 Project<Role> 类
- 必须实现项：该类中 @abstractmethod 标记的方法（用 inspect 取 __abstractmethods__）
- adapter 加载方法：impl/core/adapter_v2.py 中 ProjectAdapter 的 @abstractmethod，命名规范 _load_<role>
- live_schema 导出：按命名规范（REQUEST_SCHEMA / EXTRACT_OUTPUT_SCHEMA / SCENARIO_ENUM / check）

协议升级（新增抽象方法、新增角色）时，按搜索路径现场读取即可覆盖，方案无需同步修改。

目录结构（最终版，工程侧统一）

经确认，脚本和骨架都统一在工程侧（口径统一），skill 目录精简：

工程侧（口径统一在工程）：
scripts/
├── check_adapter_compliance.py        # 已有
└── verify_protocol_compliance.py      # 新增：协议符合性探针（实例化+角色发现）
templates/new_project/
├── adapter.py / judge.py / attribute.py   # 已有
└── live.py / mock.py / tools.py / live_schema.py / schema/  # 新增：补全骨架

skill 侧（只放流程文档）：
.claude/skills/evals/
├── SKILL.md
└── references/
    └── onboarding_acceptance.md       # 接入验收清单（引用工程命令+脚本）

各部分职责

SKILL.md（正文）

- 定位：evals 是 verifier 项目级 skill，核心职责是新项目接入
- 接入主流程 Step 0-10：信息收集 → 冻结 live_schema → 按角色构建 → adapter → 验证 → mock 固化 → 纳入回归
- 通用发现规则（如上）
- 项目侧引用清单：区分"引用工程"vs"skill 自带"两类依赖
- 门禁命令清单：每步跑哪个命令、什么算过

scripts/verify_protocol_compliance.py（工程侧新增）

- 协议符合性探针，范围 = 实例化校验 + 角色发现：
a. 扫描 impl/core/*_protocol.py，发现所有 Project<Role> 类（动态感知新增角色）
b. 对每个角色，确认项目实现了对应 <role>.py 文件 + adapter 实现了 _load_<role> 方法
c. import 项目各 <role>.py，实例化继承类，检查是否报 TypeError: Can't instantiate abstract class
- 自动从协议基类 @abstractmethod 现场读取要求，协议加新方法/新角色自动卡住新项目
- 和 check_adapter_compliance.py 同级，口径统一在工程侧

templates/new_project/（工程侧补全骨架）

- 补齐现有模板缺的：live.py / mock.py / tools.py / live_schema.py / schema/init.py
- 和现有 adapter.py / judge.py / attribute.py 同级
- 按命名规范，不写死业务，接入时拷贝填充
- 新增 adapter.md：统一说明各骨架文件的设计规范/用法，对齐 spec/adapter.md 的协议分层原则（现有 templates/new_project/ 只有简短
README.md，缺统一说明文档）。adapter.md 说明：模板包含哪些文件、每个文件继承哪个协议基类、占位符替换规则、合规检查要求

references/onboarding_acceptance.md

- 接入验收清单，内容是可执行命令（硬门禁）
- 引用工程命令 + skill 自带脚本
- 跑过才算接入完成

SKILL.md 引用清单（区分两类）

引用工程（不复制不重写，口径以工程为准）：
- scripts/check_adapter_compliance.py — adapter 合规检查
- bash run.sh cli mock-check — mock 数据 schema 校验
- bash run.sh cli run-chain — 单链跑通
- templates/new_project/ — adapter/judge/attribute 骨架

skill 自带（skill 维护）：
- scripts/verify_protocol_compliance.py — 协议符合性探针

构建顺序

Step 0: 信息收集 — 读 verifier/projects/<project>/project.yaml
Step 1: 冻结 live_schema — schema/__init__.py + live_schema.py（按命名规范导出）
Step 2: live.py — ProjectLive 子类
Step 3: mock.py — ProjectMock 子类
Step 4: tools.py — ProjectTools 子类（可按协议默认实现）
Step 5: judge.py — ProjectJudge 子类
Step 6: attribute.py — ProjectAttribute 子类
Step 7: adapter.py — ProjectAdapter 子类（按 _load_* 命名规范）
Step 8: 验证 — check_adapter_compliance + verify_protocol_compliance + mock-check + run-chain
Step 9: mock 固化 — 生成 mock_cases.json 到 impl/data/<project>/
Step 10: 纳入回归 — 更新 check1.py 配置

每步附带：输入 / 操作 / 产出 / 验收 / 搜索路径 / 参考（QA 的实现路径）。

关键边界

- 项目级 skill，和 verifier 强耦合，引用而非自建
- 工程有的不重复，工程缺的自己补——两个原则同时满足
- 唯一耦合点是 SKILL.md 的"项目侧引用清单"——写清楚引用了什么、谁维护、口径谁说了算
- skill 不自带工程已有能力的校验逻辑，不产生两套口径
- 项目脚本变更时，skill 的门禁命令跟着调整
- 不修改 core 和 protocols、不碰其他项目、project.yaml 是唯一事实源（用户提供）

文件清单

工程侧新增

- scripts/verify_protocol_compliance.py：协议符合性探针（实例化+角色发现）
- templates/new_project/live.py、mock.py、tools.py、live_schema.py、schema/__init__.py：补全骨架
- templates/new_project/adapter.md：统一说明文档（对齐 spec/adapter.md，统一下模板用法）

skill 侧

- .claude/skills/evals/SKILL.md（重写）
- .claude/skills/evals/references/onboarding_acceptance.md（新增，引用工程命令+脚本）

保留不动

- impl/core/、impl/protocols/、spec/
- .claude/skills/evals/agents/specialized/*、agents/analyzer.md

验证方式

1. 现有项目不受影响：bash run.sh cli projects
2. 合规检查：bash run.sh python scripts/check_adapter_compliance.py
3. 协议探针：bash run.sh python .claude/skills/evals/scripts/verify_protocol_compliance.py --project QA（用现有项目验证探针可用）
4. 端到端：用模拟新项目跑完整接入流程