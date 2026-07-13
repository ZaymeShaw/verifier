Evals Skill 重构方案 — 阶段 1：项目接入

背景

verifier 做了大规模架构升级（v2 协议），核心变化：
- 协议层硬约束：每个角色有 _XxxProtocol（模板方法，禁止覆盖）+ ProjectXxx（扩展点基类）
- adapter 只做中转：新 ProjectAdapter 只实现 _load_* 方法加载各协议实例，不再承载业务逻辑
- 已有模板：templates/new_project/ 提供了 adapter/judge/attribute 模板
- 已有合规检查：scripts/check_adapter_compliance.py 检查 adapter 是否符合新规范

evals skill 需要基于新架构重新设计"项目接入"流程。

设计原则

1. 只改 impl/projects/<project>/：不碰 core、protocols、其他项目、前端
2. 唯一入口 verifier/projects/<project>/project.yaml：用户先在用户侧目录准备好项目知识索引（业务资料、API 信息、启动方式等）
3. 新协议优先：新项目直接继承 ProjectAdapter（非 LegacyProjectAdapter），实现五个 _load_* 方法
4. 接入不碰算法层：只搭基础设施，judge/attribute 用协议默认实现，后续通过 attribute skill 的 draft 机制优化
5. 验收标准：mock-check 通过 + 单链跑通 + 纳入 check1 回归

新架构下的项目文件清单

必须实现（协议要求）

┌────────────────────┬──────────────────┬───────────────────────────────────────────────────────────────┬───────────────────────────────────────────────┐
│        文件        │       继承       │                           必须实现                            │                   可选覆盖                    │
├────────────────────┼──────────────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ adapter.py         │ ProjectAdapter   │ _load_judge, _load_attribute, _load_live, _load_mock,         │ —                                             │
│                    │                  │ _load_tools                                                   │                                               │
├────────────────────┼──────────────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ live.py            │ ProjectLive      │ build_request                                                 │ deliver_real, extract_output,                 │
│                    │                  │                                                               │ normalize_result                              │
├────────────────────┼──────────────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ mock.py            │ ProjectMock      │ scenarios()                                                   │ intent_labels(), normalize_case()             │
├────────────────────┼──────────────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ judge.py           │ ProjectJudge     │ build_context                                                 │ build_intent_frame, normalize_result          │
├────────────────────┼──────────────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ attribute.py       │ ProjectAttribute │ build_context                                                 │ probes(), normalize_result                    │
├────────────────────┼──────────────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ tools.py           │ ProjectTools     │ 无（全是可选）                                                │ verifiable_tools, protocol_tools,             │
│                    │                  │                                                               │ runtime_checks                                │
├────────────────────┼──────────────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ live_schema.py     │ —                │ REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, SCENARIO_ENUM, check   │ INTENT_LABELS, READY                          │
├────────────────────┼──────────────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ schema/__init__.py │ —                │ dataclass 定义（QAInput, QAExtractOutput 等）                 │ —                                             │
└────────────────────┴──────────────────┴───────────────────────────────────────────────────────────────┴───────────────────────────────────────────────┘

配置文件

┌──────────────┬────────────────────────────────────────────────────────────────────┐
│     文件     │                                作用                                │
├──────────────┼────────────────────────────────────────────────────────────────────┤
│ project.yaml │ 实现侧配置（api、frontend_extensions、implementation_standard 等） │
└──────────────┴────────────────────────────────────────────────────────────────────┘

文档（可选）

application.md / evaluation.md / mock.md / judge_boundary.md / attribution.md / checklist.md

不变量（先冻结，后续构建基于此）

不变量 1：live_schema

- 文件：impl/projects/<project>/live_schema.py + schema/__init__.py
- 必须导出：REQUEST_SCHEMA（dataclass）、EXTRACT_OUTPUT_SCHEMA（dataclass）、SCENARIO_ENUM（list[str]）、check（LiveSchemaCheck 实例）
- 是 mock 数据生成、live/judge/attr 校验的全部基础

不变量 2：ready 声明

- 在 project.yaml 的 common.ready 字段声明（枚举值 ["output", "reference"]）
- output 在 ready：case 已携带 output，live 走 provided 模式
- output 不在 ready：需要真实调用 API
- reference 在 ready：case 已携带参考答案，judge 直接采信
- reference 不在 ready：judge 需要自己生成 expected

构建顺序

顺序由依赖关系决定：

Step 0: 信息收集 — 读取 verifier/projects/<project>/project.yaml，确认 ready、api、场景
    ↓
Step 1: 冻结 live_schema — schema/__init__.py（dataclass）+ live_schema.py（导出 + check）
    ↓ (schema 是后续所有代码的输入类型来源)
Step 2: live.py — ProjectLive 子类，实现 build_request + extract_output
    ↓
Step 3: mock.py — ProjectMock 子类，实现 scenarios()
    ↓
Step 4: tools.py — ProjectTools 子类（可用默认空实现）
    ↓
Step 5: judge.py — ProjectJudge 子类，实现 build_context
    ↓
Step 6: attribute.py — ProjectAttribute 子类，实现 build_context
    ↓
Step 7: adapter.py — ProjectAdapter 子类，实现五个 _load_*
    ↓
Step 8: 验证 — check_adapter_compliance + mock-check + run-chain 单链
    ↓
Step 9: mock 固化 — 生成 mock_cases.json 到 impl/data/<project>/
    ↓
Step 10: 纳入回归 — 更新 check1.py 配置

各步骤详情

Step 1: 冻结 live_schema
- 从 project.yaml 的 common.api 理解 API 输入输出形状
- 从 projects/<project>/ 需求文档理解业务语义，抽取出 SCENARIO_ENUM
- 定义 dataclass（REQUEST_SCHEMA / EXTRACT_OUTPUT_SCHEMA）
- 创建 LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)
- 参考：impl/projects/QA/live_schema.py、impl/projects/QA/schema/__init__.py（QA 是最简样板）

Step 2: live.py
- 继承 ProjectLive，实现 build_request(case) → dict
- 按需实现 extract_output、normalize_result、deliver_real
- 纯离线评估项目（ready 含 output）可只实现 deliver_provided
- 参考：impl/projects/QA/live.py

Step 3: mock.py
- 继承 ProjectMock，实现 scenarios() 返回 SCENARIO_ENUM
- 可选 intent_labels()、normalize_case()
- 参考：impl/projects/QA/mock.py（37 行最简）

Step 4: tools.py
- 继承 ProjectTools，接入阶段用空实现（verifiable_tools() 返回 []）
- 参考：impl/projects/QA/tools.py

Step 5: judge.py
- 继承 ProjectJudge，实现 build_context(trace) → dict
- 可选 build_intent_frame、normalize_result
- 参考：impl/projects/QA/judge.py、templates/new_project/judge.py

Step 6: attribute.py
- 继承 ProjectAttribute，实现 build_context(trace, judge_result) → dict
- 可选 normalize_result
- 参考：impl/projects/QA/attribute.py、templates/new_project/attribute.py

Step 7: adapter.py
- 继承 ProjectAdapter（非 LegacyProjectAdapter），实现五个 _load_* 方法
- 不含任何业务方法（合规检查会拦截 build_*/normalize_* 等）
- 参考：templates/new_project/adapter.py（但该模板继承的是 LegacyProjectAdapter，新项目应改为 ProjectAdapter）

Step 8: 验证
bash run.sh python scripts/check_adapter_compliance.py --project <id>
bash run.sh cli mock-check --project <id>
bash run.sh cli run-chain --project <id> --mock --input '<REQUEST_SCHEMA 形状的 JSON>'

Step 9: mock 固化
- 遍历 SCENARIO_ENUM，调 mock_build_intent 生成 case
- 写入 impl/data/<project>/mock_cases.json

Step 10: 纳入回归
- 更新 impl/checklist/check1.py 的 CONFIG，加入新项目

模板补全

templates/new_project/ 当前缺 live.py / mock.py / tools.py / live_schema.py / schema/。接入流程应补充这些模板（作为
references），让接入时可直接拷贝填充。skill 里用 references 引用，不直接落盘到 templates（保持 templates 由工程维护）。

evals SKILL.md 重构

新结构

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

SKILL.md 核心内容

evals 是业务测评系统生命周期管理 skill。Claude 根据用户意图判断阶段，加载对应 agent 文档。

阶段路由：
- "新增项目"/"接入项目"/"onboard" → agents/stages/project-onboarding.md
- "归因优化"/"draft"/"attribute" → agents/specialized/attribute-analyzer.md
- "代码审查"/"标准化"/"check" → agents/specialized/check.md
- "回归测试"/"check1" → 执行 check1 流程

agents/stages/project-onboarding.md 核心内容

执行 pipeline（Claude 按序执行，每步完成后汇报用户确认再进入下一步）：
1. 信息收集
2. 冻结 schema
3. 构建 live.py
4. 构建 mock.py
5. 构建 tools.py
6. 构建 judge.py
7. 构建 attribute.py
8. 构建 adapter.py
9. 验证
10. mock 固化
11. 纳入回归
12. 输出总结

每个步骤附带：输入 / 操作 / 产出 / 验收 / 参考（现有最简项目 QA 的实现路径）。

关键边界

- 不修改 core 和 protocols：所有改动在 impl/projects/<project>/ 内
- 新项目用 ProjectAdapter：不用 LegacyProjectAdapter（那是存量项目过渡用的）
- 不碰 algorithm 层质量：judge/attribute 只实现 build_context，质量优化通过 attribute skill 的 draft
- 不碰其他项目：只改当前接入的项目目录
- project.yaml 是唯一事实源：用户提供，skill 不自动生成

文件清单

新建

- .claude/skills/evals/agents/stages/project-onboarding.md
- .claude/skills/evals/references/onboarding_checklist.md

修改

- .claude/skills/evals/SKILL.md：重构为生命周期管理总入口

保留不动

- impl/core/、impl/protocols/、templates/、scripts/
- .claude/skills/evals/agents/specialized/*
- .claude/skills/evals/agents/analyzer.md（benchmark 分析器，与 verifier 业务无关，可后续清理）

验证方式

1. 现有项目不受影响：bash run.sh cli projects 确认 4 个项目仍可识别
2. 合规检查：bash run.sh python scripts/check_adapter_compliance.py 确认现有项目不报新违规
3. 端到端：用一个模拟新项目，从 project.yaml 开始跑完 Step 1-10，验证 mock-check 和 run-chain 通过




---------------




背景

verifier 做了大规模架构升级（v2 协议），核心变化：
- 协议层硬约束：每个角色有 _XxxProtocol（模板方法，禁止覆盖）+ ProjectXxx（扩展点基类）
- adapter 只做中转：新 ProjectAdapter 只实现 _load_* 方法加载各协议实例，不再承载业务逻辑
- 已有模板：templates/new_project/ 提供了 adapter/judge/attribute 模板
- 已有合规检查：scripts/check_adapter_compliance.py 检查 adapter 是否符合新规范

evals skill 需要基于新架构重新设计"项目接入"流程。

设计原则

1. 只改 impl/projects/<project>/：不碰 core、protocols、其他项目、前端
2. 唯一入口 verifier/projects/<project>/project.yaml：用户先在用户侧目录准备好项目知识索引
3. 新协议优先：新项目直接继承 ProjectAdapter（非 LegacyProjectAdapter）
4. 动态发现协议要求：不写死方法名，通过命名规范 + @abstractmethod 动态发现当前协议要求
5. 接入不碰算法层：只搭基础设施，质量优化通过 attribute skill 的 draft 机制
6. 验收标准：mock-check 通过 + 单链跑通 + 纳入 check1 回归

命名规范（动态发现依据）

协议层采用稳定的命名规范，skill 执行时通过这些规范动态发现要求：

1. 协议基类命名规范

- 模式：Project<Role> 在 impl/core/<role>_protocol.py 中定义
- 示例：ProjectLive / ProjectMock / ProjectJudge / ProjectAttribute / ProjectTools
- 发现方式：扫描 impl/core/*_protocol.py，匹配 ^class Project\w+\(

2. 必须实现的扩展点命名规范

- 模式：@abstractmethod 标记的方法
- 发现方式：用 inspect 获取 ProjectXxx 类的 __abstractmethods__ 属性
- 注意：协议升级时可能新增 @abstractmethod，skill 自动感知

3. adapter 加载方法命名规范

- 模式：_load_<role> 对应 Project<Role> 类
- 示例：_load_live 加载 ProjectLive 实例
- 发现方式：遍历角色名，拼接 _load_<role> 方法名

4. live_schema 导出命名规范

- 固定命名：REQUEST_SCHEMA / EXTRACT_OUTPUT_SCHEMA / SCENARIO_ENUM / check
- 可选命名：INTENT_LABELS / READY
- 发现方式：import 模块后 getattr 检查这些属性是否存在

不变量（先冻结，后续构建基于此）

不变量 1：live_schema

- 文件：impl/projects/<project>/live_schema.py + schema/__init__.py
- 契约：定义项目输入输出形状，是 mock/live/judge/attr 的 schema 校验基础
- 必须导出：按命名规范（REQUEST_SCHEMA / EXTRACT_OUTPUT_SCHEMA / SCENARIO_ENUM / check）

不变量 2：ready 声明

- 位置：project.yaml 的 common.ready 字段（枚举值 ["output", "reference"]）
- 契约：决定数据流路径（output 在 ready 走 provided 模式，reference 在 ready judge 直接采信）

构建顺序

Step 0: 信息收集 — 读取 verifier/projects/<project>/project.yaml
    ↓
Step 1: 冻结 live_schema — schema/__init__.py + live_schema.py（按命名规范导出）
    ↓
Step 2-N: 按角色构建 — 遍历 ProjectXxx 协议基类，动态发现必须实现的扩展点
    ↓
Step N+1: adapter.py — 继承 ProjectAdapter，实现所有 _load_* 方法
    ↓
Step N+2: 验证 — check_adapter_compliance + mock-check + run-chain
    ↓
Step N+3: mock 固化 — 生成 mock_cases.json
    ↓
Step N+4: 纳入回归 — 更新 check1.py 配置

各步骤写"契约意图 + 验收状态 + 动态发现方式"，不写死方法名。

evals SKILL.md 重构

新结构

.claude/skills/evals/
├── SKILL.md                          # 总入口，按阶段路由
├── agents/
│   ├── specialized/
│   │   ├── attribute-analyzer.md     # 保留
│   │   └── check.md                  # 保留
│   └── stages/
│       └── project-onboarding.md     # 新增
└── references/
    └── onboarding_checklist.md       # 新增

阶段路由

- "新增项目"/"接入项目"/"onboard" → agents/stages/project-onboarding.md
- "归因优化"/"draft"/"attribute" → agents/specialized/attribute-analyzer.md
- "代码审查"/"标准化"/"check" → agents/specialized/check.md
- "回归测试"/"check1" → 执行 check1 流程

关键边界

- 不修改 core 和 protocols：所有改动在 impl/projects/<project>/ 内
- 新项目用 ProjectAdapter：不用 LegacyProjectAdapter
- project.yaml 是唯一事实源：用户提供，skill 不自动生成

文件清单

新建

- .claude/skills/evals/agents/stages/project-onboarding.md
- .claude/skills/evals/references/onboarding_checklist.md

修改

- .claude/skills/evals/SKILL.md

保留不动

- impl/core/、impl/protocols/、templates/、scripts/
- .claude/skills/evals/agents/specialized/*

验证方式

1. 现有项目不受影响：bash run.sh cli projects
2. 合规检查：bash run.sh python scripts/check_adapter_compliance.py
3. 端到端：用模拟新项目跑完整流程