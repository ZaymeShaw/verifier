# Adapter 瘦身与协议分层设计

> 本文档是方法论准则，不是实现规范。具体的基类方法签名、扩展点清单可能随实现演进，
> 但**分层原则、约束机制、迁移思路**应作为长期准则被遵守。

---

## 一、核心问题

项目 adapter 承载了过多业务逻辑（judge/attribute 上下文、工具注册、结果后处理、状态机扩展等），膨胀成上帝对象；协议层约束软，项目可以继续把逻辑塞回 adapter，绕过分层。

## 二、目标

- **adapter 只做中转**：加载并暴露各专项模块，不承载业务逻辑。
- **协议层硬约束**：项目只能实现允许的扩展点，流程逻辑锁在协议层，禁止覆盖。
- **角色拆干净**：live / mock / judge / attribute / tools 各有独立协议与项目实现。
- **新项目快速适配**：有模板、有类型约束，复制即改。
- **draft 切换顺畅**：通过 adapter 统一加载，配置驱动。

---

## 三、五层架构

```
抽象层（数据结构）：impl/core/schema/
  定义数据形状（RunTrace / JudgeResult / AttributeResult 等），不承载行为。

通用层（通用函数）：impl/core/<role>.py
  放可复用的通用函数。
  被协议层的内部方法调用，项目不应直接依赖这些函数。
  例如：judge.py 中的 judge_trace() 函数、live.py 中的 _validate_request() 函数。

协议层（不可变逻辑）：impl/core/<role>_protocol.py 中的 _XxxProtocol 类
  定义模板方法（流程骨架），final，项目不可覆盖。
  定义内部方法（_前缀），项目不可覆盖。
  协议层是流程的"骨架"，项目不能修改流程的执行顺序。

操作层（可自定义逻辑）：impl/core/<role>_protocol.py 中的 ProjectXxx 类
  定义扩展点（@abstractmethod 必须实现 + 普通方法可选覆盖）。
  项目继承这个类，实现允许定制的地方。
  操作层是流程的"扩展点"，项目可以在这些地方填入自己的逻辑。

项目层：impl/projects/<project>/<role>.py
  实现 ProjectXxx 子类，只看到扩展点。
  项目层的代码应该只包含项目特有的业务逻辑，不包含通用逻辑。
```

**核心机制**：
- **协议层**定义"不能改的流程"（模板方法 + 内部方法）。协议层和操作层在同一个文件中，协议层通过继承关系调用操作层的扩展点
- **操作层**定义"可以定制的地方"（扩展点）
- **通用层**提供"可复用的工具"（通用函数）
- 项目只能填空，不能改流程

**调用链路**：
```
pipeline.py
  ↓ 调用
adapter.<role>().<template_method>()
  ↓ 调用协议层模板方法
_XxxProtocol.<template_method>()
  ↓ 调用内部方法
_XxxProtocol.<_internal_method>()
  ↓ 调用通用函数
<role>.py::<utility_function>()
  ↓ 调用扩展点
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
| 协议层 | `_XxxProtocol`（下划线前缀） | **项目不直接继承** | 模板方法 + 内部方法（`_` 前缀） |
| 操作层 | `ProjectXxx` | **项目继承这个** | 扩展点（`@abstractmethod` 必须实现 + 普通方法可选覆盖） |

项目继承操作层，协议层对项目不可见。操作层通过委托链调用项目扩展点。

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
    """协议层：定义 judge 流程骨架，项目不能覆盖。"""
    @final
    def judge_trace(self, trace, expected_intent=None) -> JudgeResult:
        context = self.build_context(trace)                    # 扩展点
        raw = self._run_llm_judge(trace, context)              # 硬逻辑
        validated = self._validate_judge_output(raw)           # 硬约束
        return self._normalize_result(trace, validated)        # 扩展点

    def _run_llm_judge(self, trace, context): ...              # 内部方法
    def _validate_judge_output(self, data): ...                # 硬约束

class ProjectJudge(_JudgeProtocol, ABC):
    """操作层：项目继承，实现扩展点。"""
    @abstractmethod
    def build_context(self, trace) -> dict: ...                # 必须实现
    def normalize_result(self, trace, result) -> JudgeResult:  # 可选覆盖
        return result
```

---

## 五、五个角色

| 角色 | 协议文件 | 协议层 | 操作层 | 必须实现的扩展点 |
|------|---------|--------|--------|-----------------|
| 投递与执行 | `live_protocol.py` | `_LiveProtocol` | `ProjectLive` | `build_request` |
| mock 策略 | `mock_protocol.py` | `_MockProtocol` | `ProjectMock` | 无 |
| 判定 | `judge_protocol.py` | `_JudgeProtocol` | `ProjectJudge` | `build_context` |
| 归因 | `attribute_protocol.py` | `_AttributeProtocol` | `ProjectAttribute` | `build_context` |
| 工具 | `tools_protocol.py` | `_ToolsProtocol` | `ProjectTools` | 无 |

**职责边界**：
- **ProjectLive**：build_request + deliver（real/provided）+ extract_output + application_boundary。模板方法 `deliver()` 锁定投递流程。
- **ProjectMock**：场景、模板、case 归一化、下一轮策略。通用 LLM 生成仍由 core mock_agent 承载，ProjectMock 只提供项目约束。
- **ProjectJudge**：build_context + normalize_result。模板方法 `judge_trace()` 锁定 LLM 调用 + 校验流程。
- **ProjectAttribute**：build_context + probes + normalize_result。模板方法 `attribute_failure()` 锁定探针调度 + LLM 调用 + 校验流程。
- **ProjectTools**：verifiable_tools + protocol_tools + runtime_checks。

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
    def tools(self) -> ProjectTools: ...

    @abstractmethod
    def _load_live(self) -> ProjectLive: ...
    @abstractmethod
    def _load_mock(self) -> ProjectMock: ...
    @abstractmethod
    def _load_judge(self) -> ProjectJudge: ...
    @abstractmethod
    def _load_attribute(self) -> ProjectAttribute: ...
    @abstractmethod
    def _load_tools(self) -> ProjectTools: ...
```

**原则**：
- `ProjectAdapter` **只有访问器 + `_load_*` 抽象方法**，没有任何业务方法。
- draft 切换：`attribute()` / `tools()` 根据 `project.yaml` 配置决定加载正式还是 draft 实现（`_load_*_draft` 方法）。
- pipeline 调用全部走 `adapter.xxx().method()`，不直接访问 `build_request` / `normalize_*` 等。

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
2. **协议层锁流程，操作层定扩展点**。项目只能填空，不能改流程。
3. **`_` 前缀 = 不可覆盖**。协议层内部方法项目不应触碰。
4. **运行时检查兜底**。命名约定 + `@final` 是软约束，`__init_subclass__` 是硬兜底。
5. **新增角色/扩展点时，先协议后项目**。协议层定义清楚，项目层才能使用。
6. **draft 与正式实现结构一致**。通过 adapter 配置切换，不引入第二种实现形态。

---

## 十一、文件路径参考

以 Judge 为例，每个角色涉及三个文件：

```
impl/core/judge_protocol.py   → 协议层 + 扩展点基类
impl/core/judge.py            → 通用函数（LLM 调用、校验等）
impl/projects/<project>/judge.py → 项目实现
```

### 完整的文件映射表

| 角色 | 协议层 + 扩展点基类 | 通用函数 | 项目实现 |
|------|-------------------|---------|---------|
| Live | `impl/core/live_protocol.py` | `impl/core/live.py` | `impl/projects/<project>/live.py` |
| Mock | `impl/core/mock_protocol.py` | `impl/core/mock.py` | `impl/projects/<project>/mock.py` |
| Judge | `impl/core/judge_protocol.py` | `impl/core/judge.py` | `impl/projects/<project>/judge.py` |
| Attribute | `impl/core/attribute_protocol.py` | `impl/core/attribute.py` | `impl/projects/<project>/attribute.py` |
| Tools | `impl/core/tools_protocol.py` | `impl/core/tools.py` | `impl/projects/<project>/tools.py` |
| Adapter | `impl/core/adapter.py` | — | `impl/projects/<project>/adapter.py` |

### 五层职责与调用关系

```
┌─────────────────────────────────────────────────────────────┐
│ impl/core/schema/                                           │
│ 抽象层（数据结构）                                          │
│ - 定义数据形状（RunTrace / JudgeResult / AttributeResult 等）│
│ - 不承载行为                                                 │
└─────────────────────────────────────────────────────────────┘
                            ↓ 被依赖
┌─────────────────────────────────────────────────────────────┐
│ impl/core/<role>.py                                         │
│ 通用层（通用函数）                                          │
│ - 可复用的通用函数。这些函数通常是无状态的，只依赖输入参数，不依赖上下文     │
│ - 被协议层的内部方法调用                                     │
│ - 项目不应直接依赖这些函数                                   │
└─────────────────────────────────────────────────────────────┘
                            ↓ 被调用
┌─────────────────────────────────────────────────────────────┐
│ impl/core/<role>_protocol.py                                │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ _XxxProtocol（协议层）                                  │ │
│ │ - 模板方法（@final，不可覆盖）                           │ │
│ │ - 内部方法（_前缀，不可覆盖）                           │ │
│ │ - 定义流程骨架，项目不能修改执行顺序                     │ │
│ └─────────────────────────────────────────────────────────┘ │
│                            ↓ 继承                           │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ProjectXxx（操作层）                                    │ │
│ │ - @abstractmethod（必须实现）                           │ │
│ │ - 普通方法（可选覆盖）                                  │ │
│ │ - 定义扩展点，项目可以在这些地方填入自己的逻辑           │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↓ 项目继承
┌─────────────────────────────────────────────────────────────┐
│ impl/projects/<project>/<role>.py                           │
│ 项目层                                                       │
│ - class XxxJudge(ProjectJudge): ...                         │
│ - 实现 build_context()、normalize_result() 等扩展点          │
│ - 只包含项目特有的业务逻辑                                   │
└─────────────────────────────────────────────────────────────┘
```

### 调用链路示例（Judge）

```
pipeline.py:
  adapter.judge().judge_trace(trace)
         ↓
impl/core/judge_protocol.py (_JudgeProtocol.judge_trace):
  # 协议层：定义不可变的流程骨架
  1. context = self.build_context(trace)        → 调用操作层扩展点
  2. raw = self._run_llm_judge(trace, context)  → 调用内部方法
  3. validated = self._validate_judge_output(raw) → 硬约束校验（内部方法）
  4. return self._normalize_result(trace, validated) → 调用操作层扩展点
         ↓
impl/core/judge_protocol.py (_JudgeProtocol._run_llm_judge):
  # 协议层内部方法：调用通用层
  from impl.core.judge import judge_trace
  return judge_trace(spec, trace, context)
         ↓
impl/core/judge.py (judge_trace):
  # 通用层：可复用的通用函数
  - 实际的 LLM 调用逻辑
  - 通用 prompt 构建
  - 结果解析
         ↓
impl/core/judge_protocol.py (ProjectJudge.build_context):
  # 操作层：扩展点，调用项目实现
  return project_specific_build_context(trace)
         ↓
impl/projects/<project>/judge.py (XxxJudge.build_context):
  # 项目层：项目特有的业务逻辑
  - 项目特有的 context 构建逻辑
  - 项目特有的 normalize_result 逻辑
```

### 职责划分原则

1. **抽象层**（`impl/core/schema/`）：定义数据形状，不承载行为
2. **通用层**（`impl/core/<role>.py`）：可复用的通用函数（LLM 调用、校验、转换），被协议层的内部方法调用
3. **协议层**（`impl/core/<role>_protocol.py` 中的 `_XxxProtocol`）：定义流程骨架和内部方法，项目不能修改
4. **操作层**（`impl/core/<role>_protocol.py` 中的 `ProjectXxx`）：定义扩展点，项目可以在这些地方填入自己的逻辑
5. **项目层**（`impl/projects/<project>/<role>.py`）：实现扩展点，只包含项目特有的业务逻辑

**关键原则**：
- 项目只应实现操作层的扩展点基类
- 项目不应直接调用通用层的函数（除非有明确的理由，如工具函数需要复用）
- 协议层是流程的"骨架"，项目不能修改流程的执行顺序
- 操作层是流程的"扩展点"，项目可以在这些地方填入自己的逻辑

---

## 十、相关文档

- `spec/info-volume.md` — 通用层 vs 项目层职责边界
- `spec/tool2.md` — VerifiableTool 协议
- `spec/mock.md` — MockAgent 协议
- `spec/live.md` — Live 模块设计
- `impl/project_implementation_standard-template.md` — 项目实现标准模板



---------

老实说，我觉得通用层只是协议层过度迁移过程的一个中转站，实在说必要性的话就是提供一些偏通用的、可复用的函数

你说得对！通用层确实只是协议层过度迁移过程的一个中转站。让我基于这个观点重新定义：

## 🎯 重新定义通用层和协议层

### 通用层（纯工具函数）

**职责**：提供一些偏通用的、可复用的函数

**特点**：
- ✅ 纯工具函数（无业务逻辑）
- ✅ 可被多个项目复用
- ✅ 无状态
- ✅ 例如：数据转换、字符串处理、配置读取、API 调用

**不应该包含**：
- ❌ 业务逻辑
- ❌ 流程控制
- ❌ 校验逻辑
- ❌ 错误处理策略

### 协议层（业务流程定义）

**职责**：定义公共约定好的通用业务流程，以及项目可定制部分的接口/函数标准化

**特点**：
- ✅ 定义流程的步骤和顺序
- ✅ 定义每个步骤的输入/输出
- ✅ 定义步骤之间的数据流转
- ✅ 定义校验逻辑（因为校验是流程的一部分）
- ✅ 定义错误处理策略（因为错误处理是流程的一部分）
- ✅ 定义扩展点接口（项目可定制的部分）
- ✅ 提供默认实现

**不应该包含**：
- ❌ 项目特定的业务逻辑（放在项目层）
- ❌ 纯工具函数（放在通用层）

## 📋 合理的函数划分

**以 `deliver` 为例**：

**协议层（live_protocol.py）**：
```python
class _LiveProtocol:
    @final
    def deliver(self, case):
        # 流程骨架：定义步骤和顺序
        request = self.build_request(case)
        self._validate_request(request)  # 校验逻辑
        raw_response = self._execute_delivery(case, request)
        output = self._extract_output(raw_response)
        self._validate_output(output)  # 校验逻辑
        result = self._build_execution_result(case, request, raw_response, output)
        return self.normalize_result(result)
    
    def _validate_request(self, request):
        # 校验逻辑：属于流程的一部分
        if self.live_schema is None:
            return
        ok = self.live_schema.check.request(request)
        if not ok:
            # 错误处理策略：属于流程的一部分
            raise ValidationError("request 不符合 live_schema")
```

**通用层（live.py）**：
```python
def _call_api(request, timeout=10):
    # 纯工具函数：调用外部 API
    response = http_client.post(request.url, data=request.data, timeout=timeout)
    return response

def _parse_response(response):
    # 纯工具函数：解析响应
    return response.json()
```

**项目层（projects/QA/live.py）**：
```python
class QALive(ProjectLive):
    def build_request(self, case):
        # 项目特定的业务逻辑
        return QARequest(case=case)
    
    def normalize_result(self, result):
        # 项目特定的业务逻辑
        result.project_fields["qa_specific_field"] = "..."
        return result
```

## 💡 总结

**通用层** = 纯工具函数（可复用的、无业务逻辑的）
**协议层** = 业务流程定义（流程骨架 + 校验逻辑 + 错误处理 + 扩展点定义）
**项目层** = 项目特定的业务逻辑（实现协议层的扩展点）

这样函数的职责会更清晰，划分也会更合理。





--------



你说得对！让我重新梳理一下：

## 🎯 重新理解

### 协议层 = 主流程

**协议层**就是**主流程**，定义了完整的业务流程：

```python
class _LiveProtocol:
    @final
    def deliver(self, case):
        # 主流程：定义步骤和顺序
        request = self.build_request(case)      # 扩展点
        raw_response = self._call_api(request)   # 通用层
        output = self._extract_output(raw_response)  # 扩展点
        return self._normalize_result(output)     # 扩展点
```

### 通用层 = 可复用的工具函数

**通用层**提供**可复用的工具函数**，主流程需要时调用：

```python
# live.py（通用层）
def _call_api(request):
    # 纯工具函数：调用外部 API
    return http_client.post(request.url, data=request.data)
```

### 操作层 = 项目可定制的地方

**操作层**定义**项目可定制的方法点**：

```python
class ProjectLive(_LiveProtocol):
    @abstractmethod
    def build_request(self, case): ...  # 必须实现
    
    def normalize_result(self, result):  # 可选覆盖
        return result
```

## 📋 正确的理解

| 层级 | 本质 | 职责 |
|------|------|------|
| **协议层** | 主流程 | 定义完整的业务流程，包括步骤顺序、校验逻辑、错误处理 |
| **通用层** | 工具函数 | 提供可复用的纯工具函数，主流程需要时调用 |
| **操作层** | 扩展点 | 定义项目可定制的方法点，项目可以覆盖这些方法 |
| **项目层** | 实现 | 实现操作层的扩展点，填入项目特定的逻辑 |

## 💡 关键理解

1. **协议层 = 主流程**：不是"模板"或"骨架"，而是完整的业务流程定义
2. **通用层 = 工具箱**：主流程需要时从工具箱取工具，不是流程的一部分
3. **操作层 = 扩展点**：明确定义哪些方法可以定制，其他地方不能动
4. **项目层 = 填空**：只在操作层定义的扩展点中填入项目特定的逻辑

## 🎯 总结

- **协议层**：定义主流程，包括步骤、校验、错误处理
- **通用层**：提供工具函数，主流程需要时调用
- **操作层**：定义扩展点，项目可以定制这些地方
- **项目层**：实现扩展点，填入项目特定的逻辑

这样理解对吗？