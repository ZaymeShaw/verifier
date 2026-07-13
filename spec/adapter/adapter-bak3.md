# Adapter 瘦身与协议分层设计

> 本文档是方法论准则，不是实现规范。具体的基类方法签名、扩展点清单可能随实现演进，
> 但**分层原则、约束机制、迁移思路**应作为长期准则被遵守。

---

## 一、核心问题

项目 adapter 承载了过多业务逻辑（judge/attribute 上下文、工具注册、结果后处理、状态机扩展等），膨胀成上帝对象；协议层约束软，项目可以继续把逻辑塞回 adapter，绕过分层。

## 二、目标

- **adapter 只做中转**：加载并暴露各专项模块，不承载业务逻辑。
- **协议层硬约束**：项目只能实现允许的扩展点，流程逻辑锁在协议层，禁止覆盖。
- **角色拆干净**：live / mock / judge / attribute 各有独立协议与项目实现；tools 是横切的工具能力集合，有独立协议，但项目侧贡献 tool 实例进统一 Registry，不走项目 adapter 中转。
- **新项目快速适配**：有模板、有类型约束，复制即改。
- **draft 切换顺畅**：通过 adapter 统一加载，配置驱动。

---

## 三、四层架构

```
抽象层（数据结构）：impl/core/schema/
  定义数据形状（RunTrace / JudgeResult / AttributeResult 等），不承载行为。

协议层（主流程）：impl/core/<role>_protocol.py 中的 _XxxProtocol 类
  主流程的具体实现。
  需要工具时从通用层取，需要项目定制时调用扩展点。
  项目不能修改流程的执行顺序。

操作层（扩展点）：impl/core/<role>_protocol.py 中的 ProjectXxx 类
  告诉项目哪些地方可以定制。
  提供默认实现，项目可以选择性覆盖。

通用层（工具函数）：impl/core/<role>.py
  可复用的纯工具函数。
  协议层过度迁移过程的中转站，提供偏通用的、可复用的函数。
  主流程需要时调用，项目不应直接依赖。

项目层：impl/projects/<project>/<role>.py
  实现操作层定义的扩展点。
  只在扩展点中填入项目特定的业务逻辑。
```

**核心机制**：
- **协议层** = 主流程的实现，就是业务流程的具体执行逻辑
- **操作层** = 告诉项目哪些地方可以定制，提供默认实现
- **通用层** = 工具函数库，主流程需要时调用
- **项目层** = 只在扩展点中填入逻辑

**调用链路**：
```
pipeline.py
  ↓ 调用
adapter.<role>().<template_method>()
  ↓ 调用协议层主流程
_XxxProtocol.<template_method>()
  ↓ 需要工具时
<role>.py::<utility_function>()
  ↓ 需要项目定制时
ProjectXxx.<extension_point>()
  ↓ 调用项目实现
impl/projects/<project>/<role>.py::<XxxImplementation>.<extension_point>()
```

---

## 四、协议设计原则

### 1. 两个基类

每个角色在协议文件中定义**两个类**：

| 基类 | 命名 | 项目关系 | 内容 |
|------|------|---------|------|
| 协议层 | `_XxxProtocol`（下划线前缀） | **项目不直接继承** | 主流程实现 + 内部方法（`_` 前缀） |
| 操作层 | `ProjectXxx` | **项目继承这个** | 扩展点（`@abstractmethod` 必须实现 + 普通方法可选覆盖） |

项目继承操作层，协议层对项目不可见。

### 2. 三类方法

| 方法类型 | 命名约定 | 项目能做什么 | 强制手段 |
|---------|---------|-------------|---------|
| 模板方法 | 普通方法名 | **不能覆盖** | `@final` + `__init_subclass__` 检查 |
| 内部方法 | `_` 前缀 | **不能覆盖** | 同上 |
| 扩展点（必须） | `@abstractmethod` | **必须实现** | Python 强制 |
| 扩展点（可选） | 普通方法 | 可选覆盖 | 无 |

### 3. 示例（以 Judge 为例）

```python
# impl/core/judge_protocol.py
class _JudgeProtocol(ABC):
    """协议层：主流程的实现。"""
    @final
    def judge_trace(self, trace, expected_intent=None) -> JudgeResult:
        context = self.build_context(trace)                    # 扩展点
        raw = self._run_llm_judge(trace, context)              # 内部方法，调用通用层
        validated = self._validate_judge_output(raw)           # 内部方法
        return self._normalize_result(trace, validated)        # 扩展点

    def _run_llm_judge(self, trace, context): ...              # 内部方法
    def _validate_judge_output(self, data): ...                # 内部方法

class ProjectJudge(_JudgeProtocol, ABC):
    """操作层：告诉项目哪些地方可以定制。"""
    @abstractmethod
    def build_context(self, trace) -> dict: ...                # 必须实现
    def normalize_result(self, trace, result) -> JudgeResult:  # 可选覆盖
        return result
```

---

## 五、五个角色

> 角色定位先于实现。五个角色不是并列的同类模块，而是**视角分立**：
> - **live**：被测业务系统在评测系统中的具现化（**非评测者，是"靶子"**）。输入输出对齐 live_schema。
> - **mock**：**扮演用户**、产用户侧输入（外部/用户视角）。模拟用户意图与下一步输入。
> - **judge**：**业务角度**评估系统输出是否满足意图（外部/业务视角）。只看业务系统输入输出。
> - **attribute**：系统不及预期时，从**代码链路**做内部归因审视（内部/技术视角）。会看业务代码，judge 只看输入输出。
> - **tools**：横切的**工具能力集合**，服务于各 agent 阶段（judge/attribute/mock/check 等），凡派得上用场的工具性能力都算 tool。**不绑定特定角色**。
>
> mock、judge 都对外，但 mock 在输入侧扮演用户、judge 在输出侧做业务评估；attribute 对内；tools 横切服务于这几个阶段。这条主线先立，下面的表才是实现展开。

| 角色 | 协议文件 | 协议层 | 操作层 | 必须实现的扩展点 |
|------|---------|--------|--------|-----------------|
| 投递与执行 | `live_protocol.py` | `_LiveProtocol` | `ProjectLive` | `build_request` |
| mock 策略 | `mock_protocol.py` | `_MockProtocol` | `ProjectMock` | 无 |
| 判定 | `judge_protocol.py` | `_JudgeProtocol` | `ProjectJudge` | `build_context` |
| 归因 | `attribute_protocol.py` | `_AttributeProtocol` | `ProjectAttribute` | `build_context` |
| 工具 | `tools_protocol.py` | `_ToolsProtocol` | `ProjectTools` | `get_verifiable_tools` |

**职责边界**：
- **ProjectLive** 被测业务系统的具现化（非评测者）。模板方法 `deliver()` 锁定投递流程。
- **ProjectMock** 扮演用户、产用户侧输入（外部/用户视角）。扮演用户是通用能力（不管哪个项目，用户都是说自然语言、看回什么、再追问）；项目差异通过 spec 传递，不在 ProjectMock 里适配。固定两步：①用户基础意图构建 ②根据意图 + live 上下文构建每轮 live 交互输入。
- **ProjectJudge** 业务角度评估系统输出是否满足意图（外部/业务视角）。只看业务系统输入输出，不看代码。模板方法 `judge_trace()` 锁定的是**入口签名 + 产出契约 + LLM 调用/校验这段通用机制**，不锁判定逻辑本身（业务预期提取、评估边界、fulfillment 评估是项目层 `judge.py` 的主体）。
- **ProjectAttribute**：系统不及预期时从代码链路做内部归因审视（内部/技术视角），看业务系统代码链路定位根因。区别于 judge 只看输入输出，attribute 会看业务代码。模板方法 `attribute_failure()` 锁定的是**入口签名 + 产出契约 + agno 桥接/校验这段通用机制**，不锁归因推理过程（调哪些 tool、反思回合怎么设计由项目层 `attribute.py` 或 Skill 产出的 draft 决定）。
- **ProjectTools** 服务于各 agent 阶段（judge/attribute/mock/check 等）的工具能力集合，凡派得上用场的工具性能力都算 tool。横切能力，不绑特定阶段。通用层只做 VerifiableTool 协议（`tool_id` + `description` + `parameters` + `execute_fn`）+ ToolResult + ToolRegistry + ToolOrchestrator + agno 桥接，不预设分类、不绑阶段；项目层在 `impl/projects/<project>/tools/` 下贡献自己的 tool 实例，通过 `get_verifiable_tools()` 注册进统一 Registry，做什么 tool、怎么实现由项目定。

> 具体的可选扩展点清单见各协议基类实现，本表只列必须实现项。新增扩展点时遵循"协议层先定义、项目层再使用"的原则。

---

## 六、Adapter 中转站

```python
# impl/core/adapter.py
class ProjectAdapter(ABC):
    """统一中转站：只加载并暴露各专项模块。"""
    def live(self) -> ProjectLive: ...
    def mock(self) -> ProjectMock: ...
    def judge(self) -> ProjectJudge: ...
    def attribute(self) -> ProjectAttribute: ...

    @abstractmethod
    def _load_live(self) -> ProjectLive: ...
    @abstractmethod
    def _load_mock(self) -> ProjectMock: ...
    @abstractmethod
    def _load_judge(self) -> ProjectJudge: ...
    @abstractmethod
    def _load_attribute(self) -> ProjectAttribute: ...
```

> tools 不走项目 adapter 中转：项目 `impl/projects/<project>/tools/` 下的 tool 实例，通过 `get_verifiable_tools()` 直接注册进统一 ToolRegistry，由 ToolOrchestrator + agno 桥接统一调度。adapter 不暴露 `tools()` / `_load_tools()`。

**原则**：
- `ProjectAdapter` **只有访问器 + `_load_*` 抽象方法**，没有任何业务方法。
- draft 切换：`attribute()` 根据 `project.yaml` 配置决定加载正式还是 draft 实现（`_load_*_draft` 方法）。
- pipeline 调用全部走 `adapter.xxx().method()`，不直接访问 `build_request` / `normalize_*` 等。
- tool 调用走 `ToolRegistry` / `ToolOrchestrator`，不经 `adapter.tools()`。

---

## 七、硬约束机制

### 1. 运行时检查

每个协议层基类用 `__init_subclass__` 检查子类是否覆盖了禁止方法：

```python
class _JudgeProtocol(ABC):
    _FORBIDDEN_OVERRIDES = frozenset({...})  # 模板方法 + 内部方法名集合
    def __init_subclass__(cls, **kwargs):
        # 子类 __dict__ 命中 _FORBIDDEN_OVERRIDES → raise TypeError
        ...
```

**准则**：`_FORBIDDEN_OVERRIDES` = 该角色的模板方法 + 所有 `_` 前缀内部方法。新增模板方法时同步加入此集合。

### 2. `@final` 静态标注

模板方法用 `typing.final` 装饰，mypy/pyright 静态检查时警告覆盖。

### 3. adapter 合规静态检查

提供 `check_adapter_compliance` 脚本，扫描项目 adapter.py：
- 不应出现业务方法名（`build_*` 除 `_load_*`、`normalize_*`、`get_verifiable_tools`、`state_*`、`run_interactive` 等）。
- 行数应保持精简。
- 违反 → 阻断提交。

> 具体禁止方法名清单随协议演进维护，原则是"adapter 只做加载"。

---

## 八、迁移方法论

迁移遵循**先建骨架、再逐项切换、保留兼容期**的思路：

1. **定义协议骨架**：先在 `*_protocol.py` 中定义各角色的协议层 + 操作层基类，写测试验证约束机制。此阶段不动现有代码。

2. **改造中转层**：把 `ProjectAdapter` 改为中转站形态，pipeline 改为 `adapter.xxx().method()` 调用。引入兼容层（如 `LegacyProjectAdapter`）让未迁移项目继续运行，不强制一次到位。

3. **逐项目迁移**：从简单项目开始，每个项目把 adapter 业务逻辑按职责搬到对应专项模块，adapter 瘦身为中转站，跑测试确认无回归后再迁下一个。

4. **固化**：提供项目模板 + 合规检查脚本，集成到 CI，更新文档。

**回退原则**：每个阶段独立可回退。迁移期间新旧协议可并存，迁完一个删一个的 legacy 代码。

---

## 九、准则总结

1. **adapter 是中转站，不是实现者**。任何业务逻辑出现在 adapter 里都应警惕。
2. **协议层是主流程，操作层是扩展点**。项目只能在扩展点中填入逻辑，不能改流程。
3. **`_` 前缀 = 不可覆盖**。协议层内部方法项目不应触碰。
4. **运行时检查兜底**。命名约定 + `@final` 是软约束，`__init_subclass__` 是硬兜底。
5. **新增角色/扩展点时，先协议后项目**。协议层定义清楚，项目层才能使用。
6. **draft 与正式实现结构一致**。通过 adapter 配置切换，不引入第二种实现形态，draft切换/加载通过协议标准化。
7. **通用层是工具函数库**。协议层过度迁移过程的中转站，提供偏通用的、可复用的函数。

---

## 十、文件路径参考

以 Judge 为例，每个角色涉及三个文件：

```
impl/core/judge_protocol.py   → 协议层（主流程）+ 操作层（扩展点）
impl/core/judge.py            → 通用层（工具函数）
impl/projects/<project>/judge.py → 项目层（实现扩展点）
```

### 完整的文件映射表

| 角色 | 协议层 + 操作层 | 通用层 | 项目层 |
|------|----------------|--------|--------|
| Live | `impl/core/live_protocol.py` | `impl/core/live.py` | `impl/projects/<project>/live.py` |
| Mock | `impl/core/mock_protocol.py` | `impl/core/mock.py` | `impl/projects/<project>/mock.py` |
| Judge | `impl/core/judge_protocol.py` | `impl/core/judge.py` | `impl/projects/<project>/judge.py` |
| Attribute | `impl/core/attribute_protocol.py` | `impl/core/attribute.py` | `impl/projects/<project>/attribute.py` |
| Tools | `impl/core/tools_protocol.py` | `impl/core/tools.py` + `tool_registry.py` + `tool_orchestrator.py` | `impl/projects/<project>/tools/`（项目 tool 实例，经 `get_verifiable_tools()` 注册进统一 ToolRegistry，**无项目 adapter 中转**） |
| Adapter | `impl/core/adapter.py` | — | `impl/projects/<project>/adapter.py` |

### 四层职责与调用关系

```
┌─────────────────────────────────────────────────────────────┐
│ impl/core/schema/                                           │
│ 抽象层（数据结构）                                          │
│ - 定义数据形状                                              │
│ - 不承载行为                                                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ impl/core/<role>.py                                         │
│ 通用层（工具函数）                                          │
│ - 可复用的纯工具函数                                        │
│ - 协议层过度迁移过程的中转站                                │
│ - 主流程需要时调用                                          │
│ - 项目不应直接依赖                                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ impl/core/<role>_protocol.py                                │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ _XxxProtocol（协议层 = 主流程）                         │ │
│ │ - 主流程的具体实现                                      │ │
│ │ - 需要工具时从通用层取                                  │ │
│ │ - 需要项目定制时调用扩展点                              │ │
│ │ - 项目不能修改流程的执行顺序                            │ │
│ └─────────────────────────────────────────────────────────┘ │
│                            ↓ 继承                           │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ProjectXxx（操作层 = 扩展点）                           │ │
│ │ - 告诉项目哪些地方可以定制                              │ │
│ │ - @abstractmethod（必须实现）                           │ │
│ │ - 普通方法（可选覆盖）                                  │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↓ 项目继承
┌─────────────────────────────────────────────────────────────┐
│ impl/projects/<project>/<role>.py                           │
│ 项目层                                                      │
│ - 实现操作层定义的扩展点                                    │ │
│ - 只在扩展点中填入项目特定的业务逻辑                        │
│ - 不包含通用逻辑                                            │
└─────────────────────────────────────────────────────────────┘
```

### 调用链路示例（Judge）

```
pipeline.py:
  adapter.judge().judge_trace(trace)
         ↓
impl/core/judge_protocol.py (_JudgeProtocol.judge_trace):
  # 协议层：主流程的具体实现
  1. context = self.build_context(trace)        → 调用扩展点
  2. raw = self._run_llm_judge(trace, context)  → 内部方法，调用通用层
  3. validated = self._validate_judge_output(raw) → 内部方法
  4. return self._normalize_result(trace, validated) → 调用扩展点
         ↓
impl/core/judge.py (_run_llm_judge):
  # 通用层：工具函数
  - 实际的 LLM 调用逻辑
  - 通用 prompt 构建
  - 结果解析
         ↓
impl/projects/<project>/judge.py (XxxJudge.build_context):
  # 项目层：只在扩展点中填入逻辑
  - 项目特有的 context 构建逻辑
  - 项目特有的 normalize_result 逻辑
```

### 职责划分原则

1. **协议层**（`_XxxProtocol`）：主流程的具体实现，需要工具时从通用层取，需要项目定制时调用扩展点
2. **操作层**（`ProjectXxx`）：告诉项目哪些地方可以定制，提供默认实现
3. **通用层**（`<role>.py`）：工具函数库，可复用的纯工具函数，协议层过度迁移过程的中转站
4. **项目层**（`projects/<project>/<role>.py`）：只在扩展点中填入项目特有的业务逻辑

项目只应实现操作层定义的扩展点，不应直接调用通用层的函数（除非有明确的理由）。

---

## 十一、相关文档

- `spec/info-volume.md` — 通用层 vs 项目层职责边界
- `spec/tool2.md` — VerifiableTool 协议
- `spec/mock.md` — MockAgent 协议
- `spec/live.md` — Live 模块设计
- `impl/project_implementation_standard-template.md` — 项目实现标准模板