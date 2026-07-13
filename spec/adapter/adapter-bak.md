能不能设计机制，最大限度将他的逻辑移出去其他模块，但是留住adapter这个统一中转站的角色？这个逻辑要硬，不能说让别人有可能继续从adapter里面实现，但是又要有这个角色。至少需要有mock、live、judge、attribute这几个角色是要挪出去的。比如这个几个角色，也设计相应的抽象基类，impl/projects/<project>中进行实现，但是统一通过adapter来中转？

mock模块理论上也应该有，但是现在暂时不拆出来吧。后面再考虑

这是一个很好的设计方向——adapter 作为**统一入口/外观模式**，但实际逻辑全部分发到各专项模块。

让我设计这个机制：

---

## 设计方案：Adapter 作为统一中转站

### 核心思路

adapter 不再自己实现任何业务逻辑，而是**持有各专项模块的实例，纯转发**。每个专项模块有独立的抽象基类，项目在 `impl/projects/<project>/` 下实现，adapter 负责组装和暴露。


### 抽象基类设计

```python
# impl/core/live_protocol.py
class ProjectLive(ABC):
"""项目 live 投递协议"""
def __init__(self, spec: ProjectSpec): ...

@abstractmethod
def build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest: ...

def deliver_real(self, request: LiveRequest) -> LiveExecutionResult: ...  # 默认 HTTP 调用
def extract_output(self, raw_response: Any) -> dict: ...
def application_boundary(self, raw_response, extracted_output) -> dict: ...
def provided_output_raw(self, case, request) -> Any: ...
def build_frontend_extensions(self, trace) -> dict: ...

# impl/core/judge_protocol.py
class ProjectJudge(ABC):
"""项目 judge 判定协议"""
def __init__(self, spec: ProjectSpec): ...

@abstractmethod
def build_context(self, trace: RunTrace) -> dict: ...

def build_intent_frame(self, trace: RunTrace) -> dict: ...  # 默认实现
def normalize_result(self, trace, judge_result) -> JudgeResult: ...
def reconcile_result(self, trace, judge_result) -> JudgeResult: ...

# impl/core/attribute_protocol.py
class ProjectAttribute(ABC):
"""项目 attribute 归因协议"""
def __init__(self, spec: ProjectSpec): ...

@abstractmethod
def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict: ...

def normalize_result(self, trace, judge_result, attr_result) -> AttributeResult: ...
def probes(self, trace, judge_result) -> list[dict]: ...

# impl/core/tool_protocol.py
class ProjectTools(ABC):
"""项目 tool 注册协议"""
def __init__(self, spec: ProjectSpec): ...

def verifiable_tools(self) -> list[VerifiableTool]: ...
def protocol_tools(self) -> ToolRegistry: ...
def get_runtime_checks(self, runtime_values, context) -> dict: ...
```

### Adapter 作为中转站

```python
# impl/core/adapter.py —— 只做转发，零业务逻辑
class ProjectAdapter(ABC):
def __init__(self, spec: ProjectSpec):
self.spec = spec
self._live: ProjectLive | None = None
self._judge: ProjectJudge | None = None
self._attribute: ProjectAttribute | None = None
self._tools: ProjectTools | None = None

# --- 每个子模块的加载由 adapter 统一管理 ---
def live(self) -> ProjectLive:
if self._live is None:
self._live = self._load_live()
return self._live

def judge(self) -> ProjectJudge:
if self._judge is None:
self._judge = self._load_judge()
return self._judge

def attribute(self) -> ProjectAttribute:
if self._attribute is None:
self._attribute = self._load_attribute()
return self._attribute

def tools(self) -> ProjectTools:
if self._tools is None:
self._tools = self._load_tools()
return self._tools

# --- 子类必须实现的加载逻辑（一行 import） ---
@abstractmethod
def _load_live(self) -> ProjectLive: ...
@abstractmethod
def _load_judge(self) -> ProjectJudge: ...
@abstractmethod
def _load_attribute(self) -> ProjectAttribute: ...
@abstractmethod
def _load_tools(self) -> ProjectTools: ...
```

### 项目实现

```python
# impl/projects/client_search/adapter.py —— 只有加载逻辑，约 30 行
class Adapter(ProjectAdapter):
def _load_live(self):
from impl.projects.client_search.live import ClientSearchLive
return ClientSearchLive(self.spec)

def _load_judge(self):
from impl.projects.client_search.judge import ClientSearchJudge
return ClientSearchJudge(self.spec)

def _load_attribute(self):
from impl.projects.client_search.attribute import ClientSearchAttribute
return ClientSearchAttribute(self.spec)

def _load_tools(self):
from impl.projects.client_search.tools import ClientSearchTools
return ClientSearchTools(self.spec)
```

```python
# impl/projects/client_search/live.py —— 实现 ProjectLive
class ClientSearchLive(ProjectLive):
def build_request(self, case):
# 原来的 build_request 逻辑
...

def extract_output(self, raw_response):
# 原来的 extract_output 逻辑
...
```

### Pipeline 调用方式

```python
# pipeline.py —— 通过 adapter 中转，但逻辑在专项模块
adapter = load_adapter(spec)

# live 投递：adapter.live() 拿到 ProjectLive 实例
live_request = adapter.live().build_request(case)
result = adapter.live().deliver_real(live_request)

# judge：adapter.judge() 拿到 ProjectJudge 实例
context = adapter.judge().build_context(trace)
judge_result = judge_trace(spec, trace, context=context)
judge_result = adapter.judge().normalize_result(trace, judge_result)

# attribute：adapter.attribute() 拿到 ProjectAttribute 实例
attr_context = adapter.attribute().build_context(trace, judge_result)
attr_result = attribute_failure(spec, trace, judge_result, context=attr_context)
attr_result = adapter.attribute().normalize_result(trace, judge_result, attr_result)

# tools
verifiable_tools = adapter.tools().verifiable_tools()
```

### 为什么这个机制"硬"

1. **`ProjectAdapter` 只有 `_load_*` 抽象方法**，没有任何业务逻辑方法（没有 `build_request`、没有 `build_judge_context`、没有 `normalize_judge_result`）。任何人想在 adapter 里加业务逻辑，必须加新方法，review 时一眼就能看到。

2. **专项基类（`ProjectLive`、`ProjectJudge` 等）有完整的抽象方法**，逻辑必须写在这些子类里，不能绕过。

3. **adapter 只暴露 `.live()` / `.judge()` / `.attribute()` / `.tools()` 四个访问器**，外部调用方通过 adapter 拿到专项实例，但具体逻辑在专项模块里。

4. **review 检查自动化**：adapter.py 超过 N 行、或包含 `def build_` / `def normalize_` / `def get_verifiable` 等方法名时，CI 可以直接报错。

### 迁移路径

1. 先定义 `ProjectLive`、`ProjectJudge`、`ProjectAttribute`、`ProjectTools` 四个抽象基类
2. 各项目创建对应的实现类，把 adapter 里的逻辑搬过去
3. 修改 `ProjectAdapter`，删掉所有业务方法，只保留 `_load_*` 抽象方法
4. 修改 pipeline 调用点，从 `adapter.build_request()` 改为 `adapter.live().build_request()`
5. 旧项目 adapter 里的 `build_request` 等直接删除

这样 adapter 保留"统一中转站"角色，但逻辑零泄漏。



---------



❯ 1。这套机制会不会有什么问题？我希望无论协议还是projects内，都要拆的清楚，2。我还是希望有mock的位置 3。                                           
其他的你思考下，从整个架构的角度看怎么做比较合理，我希望的其实就是无论协议还是projects内，都要拆的清楚，至于是不是adapter.md这种，其实都行。方便 
后续做新项目的快速适配，以及attribute/judge的draft构建切换                                                                                       

⏺ 明白了。你的核心诉求是：协议层和项目层都拆干净，新项目能快速适配，draft 切换顺畅。我来系统思考一下整个架构。

---
一、先回答你的疑问

1. 动态加载机制的问题

现有 ProjectLiveCompat / ProjectLiveModule 那套自由函数 + 动态加载机制，问题在于：

- 鸭子类型：靠 hasattr 判断有没有某个函数，没有接口约束，项目可以随便写签名，运行时才发现不对
- 绕过后门：项目可以在 adapter 里继续塞逻辑，动态加载不会强制它写 ProjectLive 子类
- 调试困难：错误在 import 阶段或运行时才暴露，没有静态类型检查

你想要"拆得清楚"，那这套就应该废弃。用基类约束 + 类型提示 + 静态检查，项目实现时 IDE 能提示、编译时能发现签名不对。

2. mock 的位置

你说"希望有 mock 的位置"，我理解是 mock 也要有独立的协议和项目实现。那现在是 5 个角色：

┌───────────┬───────────────────────────────────────────────────────────────────────────────┐
│   角色    │                                     职责                                      │
├───────────┼───────────────────────────────────────────────────────────────────────────────┤
│ live      │ 投递与执行（build_request + deliver + extract_output + application_boundary） │
├───────────┼───────────────────────────────────────────────────────────────────────────────┤
│ mock      │ 项目级 mock 策略（场景、模板、case 归一化、下一轮输入策略）                   │
├───────────┼───────────────────────────────────────────────────────────────────────────────┤
│ judge     │ 判定上下文 + 结果后处理                                                       │
├───────────┼───────────────────────────────────────────────────────────────────────────────┤
│ attribute │ 归因上下文 + 探针 + 结果后处理                                                │
├───────────┼───────────────────────────────────────────────────────────────────────────────┤
│ tools     │ 工具注册 + runtime_checks                                                     │
└───────────┴───────────────────────────────────────────────────────────────────────────────┘

mock 不拆的注释可以删掉了，我会把它纳入这次改造。

---
二、从整体架构重新设计

你的核心诉求：

1. 协议层拆清楚：每个角色有独立的协议（抽象基类 + 数据结构）
2. 项目层拆清楚：每个项目有独立的实现文件，不混在一起
3. 新项目快速适配：有模板、有类型提示、IDE 能自动补全
4. draft 切换顺畅：draft 实现和正式实现结构一致，切换只改配置

我重新设计一下：

协议层（impl/core/protocols/）

impl/core/protocols/
├── __init__.py
├── live.py        # ProjectLive 基类 + LiveRequest/LiveExecutionResult
├── mock.py        # ProjectMock 基类 + MockBuildSpec/MockBuildResult
├── judge.py       # ProjectJudge 基类 + JudgeResult/JudgeContext
├── attribute.py   # ProjectAttribute 基类 + AttributeResult/ProbeResult
└── tools.py       # ProjectTools 基类 + VerifiableTool/ToolRegistry

每个协议文件包含：
- 抽象基类：定义项目必须/可选实现的方法
- 数据结构：该角色的输入/输出 dataclass
- 默认实现：通用逻辑的 fallback

项目层（impl/projects/<project>/）

impl/projects/<project>/
├── project.yaml          # 配置（包括 draft 开关）
├── adapter.py            # 只做加载 + 暴露（~50行）
├── live.py               # 实现 ProjectLive
├── mock.py               # 实现 ProjectMock（可选）
├── judge.py              # 实现 ProjectJudge
├── attribute.py          # 实现 ProjectAttribute
├── tools.py              # 实现 ProjectTools（或 tools/__init__.py）
├── schema.py             # 项目 dataclass（或 schema/__init__.py）
└── draft/
├── attribute.py      # draft 版 ProjectAttribute
└── tools.py          # draft 版 ProjectTools

Adapter 的定位

adapter 仍然是统一入口，但只做两件事：

1. 加载：根据 project.yaml 配置，加载正式或 draft 版本的实现
2. 暴露：通过 .live() / .mock() / .judge() / .attribute() / .tools() 访问器暴露

class ProjectAdapter:
def __init__(self, spec: ProjectSpec):
self.spec = spec
self._instances: dict[str, Any] = {}

def live(self) -> ProjectLive:
return self._get_or_load("live", self._load_live)

def mock(self) -> ProjectMock:
return self._get_or_load("mock", self._load_mock)

def judge(self) -> ProjectJudge:
return self._get_or_load("judge", self._load_judge)

def attribute(self) -> ProjectAttribute:
# draft 开关决定加载正式还是 draft 版本
if self._use_draft_attribute():
return self._get_or_load("attribute_draft", self._load_attribute_draft)
return self._get_or_load("attribute", self._load_attribute)

def tools(self) -> ProjectTools:
if self._use_draft_attribute():
return self._get_or_load("tools_draft", self._load_tools_draft)
return self._get_or_load("tools", self._load_tools)

# 子类只需实现 _load_* 方法
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
# draft 版本（可选，默认抛 NotImplementedError）
def _load_attribute_draft(self) -> ProjectAttribute: raise NotImplementedError
def _load_tools_draft(self) -> ProjectTools: raise NotImplementedError

---
三、关于 pipeline 调用点

现在我倾向于保留一层薄的转发，让 pipeline 调用保持简洁：

# pipeline.py
def live_run(project_id, case):
adapter = load_adapter(spec)
request = adapter.live().build_request(case)      # 明确走 live 协议
result = adapter.live().deliver_real(request)
...

def judge(project_id, trace):
adapter = load_adapter(spec)
context = adapter.judge().build_context(trace)
result = judge_trace(spec, trace, context)         # 通用协议入口
return adapter.judge().normalize_result(trace, result)

def attribute(project_id, trace, judge_result):
adapter = load_adapter(spec)
context = adapter.attribute().build_context(trace, judge_result)
result = attribute_failure(spec, trace, judge_result, context)
return adapter.attribute().normalize_result(trace, judge_result, result)

调用点改动明确：adapter.xxx() 拿到协议实例，然后调协议方法。没有隐式转发，所有调用显式写清楚走哪个协议。

---
四、关于迁移策略

我建议分两步：

第一步：定义协议层骨架（不改现有代码）

1. 在 impl/core/protocols/ 下定义 5 个基类
2. 写单元测试验证基类约束
3. 这一步不影响任何现有代码

第二步：逐项目迁移（可暂停、可验证）

按项目逐个迁移，每迁完一个项目：
- 跑该项目测试
- 跑 checklist check1
- 确认无回归后再迁下一个

项目迁移顺序建议：QA → client_search → marketting-planning-intent → marketting-planning（从简单到复杂）

---
五、最终确认

在我开始实施之前，确认以下几点：

1. 协议层位置：impl/core/protocols/ 还是保留在现有 impl/core/ 下（如 live_protocol.py、judge_protocol.py）？
2. mock 要纳入：对，这次一起做
3. pipeline 调用点：全部改成 adapter.xxx().method() 显式调用
4. 迁移方式：先建骨架（不改旧代码），再逐项目迁移

你确认这几点，我就开始写协议基类。



----------


❯ 目前我有一个疑问，无论协议层还是项目层，其实都有大量的代码，然后本身还要新增这些基类档案，你怎么平衡抽象层、协议层、项目层的实现关系和关联逻辑？ 

⏺ 这是个非常本质的问题。我先把当前各层的实际代码量和职责摸清楚，再回答你怎么平衡——否则就是空谈抽象。

Read 1 file (ctrl+o to expand)

⏺ Bash(echo "=== 项目层代码量 ===" && for proj in client_search QA marketting-planning marketting-planning-intent; do echo "--- $proj ---" && wc -l
impl/projects/$proj/adapt…)
⎿  === 项目层代码量 ===
--- client_search ---
499 impl/projects/client_search/adapter.py
… +22 lines (ctrl+o to expand)
⎿  Allowed by auto mode classifier

Read 1 file (ctrl+o to expand)

⏺ 现在我看清楚了。让我直接回答你的问题：

---
一、当前代码量的真相

┌────────────────────┬───────────────┬────────┬──────────────────────────────────────────┐
│        层级        │     模块      │ 代码量 │                 核心内容                 │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│ core 协议层        │ live.py       │  500   │ live 投递编排 + ProjectLiveCompat 兼容层 │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│                    │ judge.py      │  464   │ LLM 调用 + fulfillment 推导 + self-check │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│                    │ attribute.py  │  286   │ LLM 调用 + agno 桥接                     │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│                    │ mock_agent.py │  364   │ LLM 扮演用户生成 case                    │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│                    │ adapter.py    │  249   │ 基类 + 大量默认方法                      │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│ 项目层 (4项目平均) │ adapter.py    │  610   │ 业务逻辑全在这里                         │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│                    │ live.py       │  246   │ 投递逻辑                                 │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│                    │ judge.py      │   69   │ 判定上下文                               │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│                    │ attribute.py  │   98   │ 归因上下文                               │
├────────────────────┼───────────────┼────────┼──────────────────────────────────────────┤
│ schema             │ normalize.py  │  729   │ 数据结构 + 归一化                        │
└────────────────────┴───────────────┴────────┴──────────────────────────────────────────┘

问题核心：项目 adapter 平均 610 行，是所有项目模块里最膨胀的。 而 core adapter 也有 249 行，里面混了太多"默认实现"——这些默认实现本该是协议层的
fallback，但现在成了项目绕过协议的后门。

---
二、你问的本质问题：抽象层、协议层、项目层怎么平衡？

我的答案是：不要新增"基类档案"，用现有代码重新分配职责。

具体说：

1. 抽象层（数据结构）= 现有的 impl/core/schema/

这部分已经很好：
- JudgeResult、AttributeResult、LiveExecutionResult、RunTrace 等都是 dataclass
- normalize.py 是数据结构的归一化逻辑

不动。 这就是你的"抽象层"——它定义了数据形状，不承载行为。

2. 协议层（行为约束）= 现有 impl/core/*.py 重新分配

不要新建 protocols/ 目录，而是把现有代码的职责说清楚：

┌──────────────┬─────────────────────────────┬───────────────────────────────────────────────────────────┐
│     文件     │          当前内容           │                         调整方向                          │
├──────────────┼─────────────────────────────┼───────────────────────────────────────────────────────────┤
│ live.py      │ 编排 + 兼容层 + trace 构建  │ 拆成：live_protocol.py（基类）+ live.py（编排入口）       │
├──────────────┼─────────────────────────────┼───────────────────────────────────────────────────────────┤
│ judge.py     │ LLM 调用 + fulfillment 逻辑 │ 保留：通用 judge 逻辑；judge_protocol.py 已有基类         │
├──────────────┼─────────────────────────────┼───────────────────────────────────────────────────────────┤
│ attribute.py │ LLM 调用 + agno 桥接        │ 保留：通用 attribute 逻辑；attribute_protocol.py 已有基类 │
├──────────────┼─────────────────────────────┼───────────────────────────────────────────────────────────┤
│ adapter.py   │ 基类 + 大量默认方法         │ 大幅精简：只保留 _load_* + 访问器                         │
└──────────────┴─────────────────────────────┴───────────────────────────────────────────────────────────┘

关键：协议层的"基类"不是要新写一堆代码，而是把现有代码里的"接口部分"抽离出来，剩下的通用实现变成默认方法或独立函数。

3. 项目层 = 从 adapter 搬家

项目 adapter 里的 600 行逻辑，按职责搬到：

- live.py：build_request、extract_output、application_boundary、run_interactive
- judge.py：build_judge_context、normalize_judge_result、reconcile_judge_result
- attribute.py：build_attribute_context、probes、normalize_attribute_result
- tools.py（或 tools/__init__.py）：get_verifiable_tools、protocol_tools、runtime_checks

搬完后，adapter.py 只剩：

class Adapter(ProjectAdapter):
def _load_live(self):
from .live import ProjectLiveImpl
return ProjectLiveImpl(self.spec)
def _load_judge(self):
from .judge import ProjectJudgeImpl
return ProjectJudgeImpl(self.spec)
# ... 共 ~30行

---
三、"新增基类档案"的问题怎么解决？

你说得对，如果只是新加一堆基类文件，项目还要写一堆实现，代码量不降反增。

我的策略：基类只定义签名，默认实现用现有代码的 fallback。

举例：

# impl/core/live_protocol.py
class ProjectLive(ABC):
"""项目 live 协议。基类只定义签名，不写默认逻辑。"""

@abstractmethod
def build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
"""必须实现：case 输入转业务请求"""
...

def extract_output(self, raw_response: Any) -> dict:
"""可选：提取结构化输出。默认从 raw_response['data'] 取"""
if isinstance(raw_response, dict) and "data" in raw_response:
    return raw_response["data"]
return {}

def application_boundary(self, raw_response, extracted_output) -> dict:
"""可选：业务边界。默认空"""
return {}

def provided_output_raw(self, case, request) -> Any:
"""可选：provided 输出。默认从 case.output 取"""
return getattr(case, "output", None) or {}

def build_frontend_extensions(self, trace) -> dict:
"""可选：前端扩展。默认空"""
return {}

注意：
- 只有 build_request 是抽象方法，必须实现
- 其他方法都有简单默认实现（3-5行），项目如果不覆盖也能工作
- 默认实现不调 adapter，不引入循环依赖

这样项目只需要实现自己关心的方法，不用写一堆空方法。

---
四、现有 *_protocol.py 的处理

当前已有的：
- judge_protocol.py（42行）：run_project_judge_protocol 函数
- attribute_protocol.py（39行）：run_project_attribute_protocol 函数

这两个是协议执行入口，不是基类。它们的作用是：
1. 从项目层拿 context
2. 调通用层 LLM 逻辑
3. 后处理返回结果

保留这两个文件，它们是"协议层如何执行"的入口，而不是"项目层必须实现什么"的约束。

真正的基类约束，我会加到：
- live_protocol.py：class ProjectLive(ABC)
- mock_protocol.py：class ProjectMock(ABC)
- judge_protocol.py：追加 class ProjectJudge(ABC)
- attribute_protocol.py：追加 class ProjectAttribute(ABC)

---
五、我的实施建议

分三步，每步可独立验证：

第一步：定义 5 个基类（只加签名 + 简单默认）

在现有 protocol 文件里追加基类，不新建文件。每个基类只有：
- 1-2 个抽象方法（必须实现）
- 几个带简单默认的方法（可选覆盖）

这一步不改任何现有代码，只是新增接口定义。

第二步：新建 project.template/ 目录

放一个完整的项目模板，展示新结构下项目该怎么写：

impl/projects/project.template/
├── project.yaml
├── adapter.py        # ~30行，只做加载
├── live.py           # 实现 ProjectLive
├── mock.py           # 实现 ProjectMock（可选）
├── judge.py          # 实现 ProjectJudge
├── attribute.py      # 实现 ProjectAttribute
├── tools.py          # 实现 ProjectTools
└── schema.py         # 项目 dataclass

新项目可以复制这个模板，填自己的业务逻辑。

第三步：逐项目迁移

每迁一个项目：
1. 创建项目的 ProjectXxxImpl 类，把 adapter 里的方法搬过去
2. adapter 只保留 _load_* 方法
3. 跑测试验证

---
六、最终回答你的问题

▎ 你怎么平衡抽象层、协议层、项目层的实现关系和关联逻辑？

平衡原则：

1. 抽象层（schema）不动 —— 数据结构已经清晰
2. 协议层只加签名，不加实现 —— 基类只定义"项目必须实现什么"，默认实现控制在 3-5 行
3. 项目层从 adapter 搬家 —— 按职责拆到对应模块，不新增文件类型
4. adapter 只做加载 —— 删掉所有业务方法，只保留 _load_*

核心约束：不让任何一层膨胀成上帝对象。协议层不承载项目逻辑，项目层不绕过协议。

要我开始按这个思路写第一步（5 个基类定义）吗？





---------


❯ 问题在于，如果是继承的方式，我希望协议有一些东西是不能被改的，就是得对项目有约束，项目只能改一部分代码，剩下的都要按照协议的逻辑来，避免项目为了 
适应自己的逻辑瞎改，得做到这个。你怎么确保这点呢                                                                                                 

⏺ 这是个关键问题。让我直接回答：

---
一、问题本质

你想要的是：协议层有一部分逻辑是"硬"的，项目层不能改；项目层只能在明确允许的扩展点定制。

这要求我们区分协议的两种方法：

┌──────────┬───────────────────────────────────┬───────────────────────────┐
│   类型   │               特征                │       项目能做什么        │
├──────────┼───────────────────────────────────┼───────────────────────────┤
│ 模板方法 │ 协议定义执行流程，调用项目的 hook │ 只能实现 hook，不能改流程 │
├──────────┼───────────────────────────────────┼───────────────────────────┤
│ 扩展点   │ 协议提供默认实现，项目可覆盖      │ 可以完全覆盖              │
└──────────┴───────────────────────────────────┴───────────────────────────┘

模板方法模式是关键——把"不能改的流程"锁在协议层，项目只能填空。

---
二、具体设计

1. Judge 协议的模板方法

# impl/core/judge_protocol.py

class ProjectJudge(ABC):
"""项目 judge 协议。

模板方法模式：
- judge_trace() 是模板方法，定义执行流程，项目不能改
- build_context() 是扩展点，项目必须实现
- normalize_result() 是扩展点，项目可选覆盖
"""

# ===== 模板方法：final，项目不能覆盖 =====
def judge_trace(self, trace: RunTrace, expected_intent: str | None = None) -> JudgeResult:
    """执行 judge 的完整流程。这个方法是 final 的，项目不能覆盖。"""
    # 1. 项目提供上下文（扩展点）
    context = self.build_context(trace)

    # 2. 通用协议：调 LLM 生成判定（不可改）
    raw_result = self._run_llm_judge(trace, context, expected_intent)

    # 3. 协议校验：检查 fulfillment 状态是否合法（不可改）
    validated = self._validate_judge_output(raw_result)

    # 4. 项目后处理（扩展点）
    final_result = self.normalize_result(trace, validated)

    # 5. 协议最终校验：确保结果符合 schema（不可改）
    self._final_schema_check(final_result)

    return final_result

# ===== 内部方法：前缀 _ 表示不可覆盖 =====
def _run_llm_judge(self, trace, context, expected_intent) -> dict:
    """调用 LLM 做 judge。项目不能改。"""
    from .judge import run_llm_judge  # 通用实现
    return run_llm_judge(trace, context, expected_intent)

def _validate_judge_output(self, data: dict) -> JudgeResult:
    """校验 LLM 输出是否符合协议。项目不能改。"""
    # fulfillment 状态必须在允许范围内
    # overall_fulfillment 必须与细粒度结果一致
    # ... 协议层硬约束
    ...

def _final_schema_check(self, result: JudgeResult) -> None:
    """最终 schema 校验。项目不能改。"""
    # 检查必填字段、类型、值域
    ...

# ===== 扩展点：项目可以定制 =====
@abstractmethod
def build_context(self, trace: RunTrace) -> dict:
    """项目必须实现：构造 judge 上下文。"""
    ...

def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
    """项目可选覆盖：后处理 judge 结果。默认直接返回。"""
    return result

关键点：
- judge_trace() 是模板方法，不以 @abstractmethod 形式暴露，项目想覆盖也覆盖不了（Python 没有 final 关键字，但我们可以用命名约定 + 文档约定 +
静态检查）
- _run_llm_judge() / _validate_judge_output() / _final_schema_check() 是内部方法，前缀 _ 表示不可覆盖
- build_context() 是抽象方法，项目必须实现
- normalize_result() 是可选覆盖点

2. Attribute 协议的模板方法

# impl/core/attribute_protocol.py

class ProjectAttribute(ABC):
"""项目 attribute 协议。

模板方法：
- attribute_failure() 定义归因流程，项目不能改
- build_context() 是扩展点，项目必须实现
- probes() 是扩展点，项目可选实现
- normalize_result() 是扩展点，项目可选覆盖
"""

# ===== 模板方法：不可覆盖 =====
def attribute_failure(self, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    """执行归因的完整流程。这个方法是 final 的。"""
    # 1. 收集项目上下文
    context = self.build_context(trace, judge_result)

    # 2. 运行探针（扩展点，项目可选提供）
    probe_results = self._run_probes(trace, judge_result)
    context["probe_results"] = probe_results

    # 3. 调 LLM 做归因（不可改）
    raw_result = self._run_llm_attribute(trace, judge_result, context)

    # 4. 协议校验（不可改）
    validated = self._validate_attribute_output(raw_result)

    # 5. 项目后处理（扩展点）
    final_result = self.normalize_result(trace, judge_result, validated)

    # 6. 最终校验（不可改）
    self._final_schema_check(final_result)

    return final_result

def _run_probes(self, trace, judge_result) -> list[dict]:
    """运行项目提供的探针。探针是可选的，协议层负责调度。"""
    probe_fn = self.probes()
    if not probe_fn:
        return []
    try:
        return probe_fn(trace, judge_result)
    except Exception:
        return []  # 探针失败不中断归因

def _run_llm_attribute(self, trace, judge_result, context) -> dict:
    """调 LLM 做归因。项目不能改。"""
    from .attribute import run_llm_attribute
    return run_llm_attribute(trace, judge_result, context)

def _validate_attribute_output(self, data: dict) -> AttributeResult:
    """校验归因输出。项目不能改。"""
    ...

def _final_schema_check(self, result: AttributeResult) -> None:
    """最终校验。项目不能改。"""
    ...

# ===== 扩展点 =====
@abstractmethod
def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
    """项目必须实现：构造归因上下文。"""
    ...

def probes(self) -> Callable[[RunTrace, JudgeResult], list[dict]] | None:
    """项目可选实现：提供探针函数。默认无探针。"""
    return None

def normalize_result(self, trace, judge_result, result) -> AttributeResult:
    """项目可选覆盖：后处理归因结果。"""
    return result

3. Live 协议的模板方法

# impl/core/live_protocol.py

class ProjectLive(ABC):
"""项目 live 协议。

模板方法：
- deliver() 定义投递流程，项目不能改
- build_request() 是扩展点，项目必须实现
- extract_output() / application_boundary() 是扩展点，可选覆盖
"""

# ===== 模板方法：不可覆盖 =====
def deliver(self, case: SingleTurnCase | MultiTurnCase) -> LiveExecutionResult:
    """完整投递流程。这个方法是 final 的。"""
    request = self.build_request(case)  # 项目必须实现

    # 判断是 provided 还是 live
    if self._is_provided(case, request):
        raw = self.deliver_provided(case, request)
    else:
        raw = self.deliver_real(request)

    extracted = self.extract_output(raw, request)
    boundary = self.application_boundary(raw, extracted, request)
    trace = self.build_execution_trace(raw, extracted, request)

    # 组装结果（不可改的结构）
    return LiveExecutionResult(
        project_id=self.spec.project_id,
        case_id=request.case_id,
        normalized_request=request.normalized_request,
        raw_response=raw,
        extracted_output=extracted,
        application_boundary=boundary,
        execution_trace=trace,
        ...
    )

def _is_provided(self, case, request) -> bool:
    """判断是否 provided 模式。项目不能改。"""
    from .interaction_protocol import resolve_ready
    return resolve_ready(self.spec, case).output

def deliver_real(self, request: LiveRequest) -> Any:
    """真实投递。有默认实现（HTTP 调用），项目可选覆盖。"""
    return self._http_call(request)

def _http_call(self, request: LiveRequest) -> Any:
    """默认 HTTP 调用。项目不能改。"""
    from .http_client import call_project_api
    return call_project_api(self.spec, request.normalized_request)

def deliver_provided(self, case, request) -> Any:
    """provided 投递。有默认实现（从 case.output 取），项目可选覆盖。"""
    return self.provided_output_raw(case, request)

# ===== 扩展点 =====
@abstractmethod
def build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
    """项目必须实现：构造业务请求。"""
    ...

def extract_output(self, raw_response, request) -> dict:
    """项目可选覆盖：提取结构化输出。"""
    return {}

def application_boundary(self, raw_response, extracted_output, request) -> dict:
    """项目可选覆盖：业务边界。"""
    return {}

def build_execution_trace(self, raw_response, extracted_output, request) -> list:
    """项目可选覆盖：执行链路。"""
    return []

def provided_output_raw(self, case, request) -> Any:
    """项目可选覆盖：provided 输出。"""
    return getattr(case, "output", None) or {}

---
三、如何确保"项目不能改"？

Python 没有真正的 final 关键字，但我们用三层机制：

1. 命名约定 + 文档约定

- 模板方法：不用 @abstractmethod，直接定义实现，文档标注"final 方法，项目不应覆盖"
- 内部方法：前缀 _，文档标注"协议内部，不可覆盖"
- 扩展点：@abstractmethod 或普通方法，文档标注"项目可选/必须实现"

2. 静态检查（可选）

可以用 typing.final 装饰器 + mypy 检查：

from typing import final

class ProjectJudge(ABC):
@final
def judge_trace(self, trace, expected_intent=None) -> JudgeResult:
    ...

mypy 会警告项目层覆盖 @final 方法。

3. 运行时检查（硬约束）

在协议层基类加检测逻辑：

class ProjectJudge(ABC):
def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)
    # 检查项目是否覆盖了不该覆盖的方法
    _forbidden = {"judge_trace", "_run_llm_judge", "_validate_judge_output", "_final_schema_check"}
    for name in _forbidden:
        if name in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} 不能覆盖协议方法 {name}，这是模板方法，"
                f"请只覆盖扩展点方法（build_context, normalize_result）"
            )

这样项目一旦覆盖了不该覆盖的方法，实例化时就会报错，而不是运行到一半才发现问题。

---
四、总结

┌────────────────┬─────────────────┬──────────────┬─────────────────────────────────┐
│    方法类型    │      命名       │ 项目能做什么 │            强制手段             │
├────────────────┼─────────────────┼──────────────┼─────────────────────────────────┤
│ 模板方法       │ 普通方法名      │ 不能覆盖     │ @final + __init_subclass__ 检查 │
├────────────────┼─────────────────┼──────────────┼─────────────────────────────────┤
│ 内部方法       │ _ 前缀          │ 不能覆盖     │ 同上                            │
├────────────────┼─────────────────┼──────────────┼─────────────────────────────────┤
│ 扩展点（必须） │ @abstractmethod │ 必须实现     │ Python 强制                     │
├────────────────┼─────────────────┼──────────────┼─────────────────────────────────┤
│ 扩展点（可选） │ 普通方法        │ 可选覆盖     │ 无                              │
└────────────────┴─────────────────┴──────────────┴─────────────────────────────────┘

核心思想：模板方法 + 运行时检查，让项目只能在明确允许的扩展点定制，协议的骨架逻辑锁死。

要我开始写这个框架吗？




--------


⏺ 明白了，你的意思是：

- 协议层 = 一个"不可变"基类：定义模板方法（执行流程），这些方法项目不能覆盖
- 操作层 = 另一个基类：定义扩展点（hook），这些方法项目必须/可选实现

项目继承时，只继承操作层基类，操作层内部通过组合或委托调用协议层的模板方法。

这样项目代码里看不到协议层的模板方法，只能看到操作层的扩展点。

---
设计

# impl/core/judge_protocol.py

class _JudgeProtocol(ABC):
    """Judge 协议层（不可变）。定义执行流程，项目不能直接继承。"""

    def judge_trace(self, trace: RunTrace, expected_intent: str | None = None) -> JudgeResult:
        """模板方法：执行 judge 的完整流程。项目不能覆盖。"""
        context = self._build_context(trace)
        raw_result = self._run_llm_judge(trace, context, expected_intent)
        validated = self._validate_judge_output(raw_result)
        final_result = self._normalize_result(trace, validated)
        self._final_schema_check(final_result)
        return final_result

    def _run_llm_judge(self, trace, context, expected_intent) -> dict:
        """内部：调 LLM 做 judge。"""
        ...

    def _validate_judge_output(self, data: dict) -> JudgeResult:
        """内部：校验 LLM 输出。"""
        ...

    def _final_schema_check(self, result: JudgeResult) -> None:
        """内部：最终 schema 校验。"""
        ...

    # 这些会被操作层覆盖
    @abstractmethod
    def _build_context(self, trace: RunTrace) -> dict: ...

    def _normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        """默认直接返回，操作层可覆盖。"""
        return result


class ProjectJudge(_JudgeProtocol, ABC):
    """Judge 操作层。项目继承这个，实现扩展点。"""

    # 项目必须实现
    def build_context(self, trace: RunTrace) -> dict:
        """构造 judge 上下文。项目必须实现。"""
        ...

    # 内部委托给协议层
    def _build_context(self, trace: RunTrace) -> dict:
        return self.build_context(trace)

    # 项目可选覆盖
    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        """后处理 judge 结果。项目可选覆盖，默认直接返回。"""
        return result

    def _normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        return self.normalize_result(trace, result)

项目实现：

# impl/projects/client_search/judge.py

class ClientSearchJudge(ProjectJudge):
    def build_context(self, trace: RunTrace) -> dict:
        # 项目实现
        ...

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        # 项目可选覆盖
        ...

这样项目代码里：
- 只能看到 build_context、normalize_result 等操作层方法
- 看不到 judge_trace、_run_llm_judge、_validate_judge_output 等协议层方法
- 协议层通过 _build_context → build_context 的委托链调用项目实现

---
运行时检查

class ProjectJudge(_JudgeProtocol, ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # 禁止项目覆盖协议层方法
        _forbidden = {"judge_trace", "_run_llm_judge", "_validate_judge_output", "_final_schema_check"}
        for name in _forbidden:
            if name in cls.__dict__:
                raise TypeError(f"{cls.__name__} 不能覆盖协议方法 {name}")

---
五个角色的操作层基类

┌────────────────────┬──────────────────┬────────────────────────────────────┬───────────────┬───────────────────────────────────────────────┐
│       协议层       │      操作层      │              项目继承              │   必须实现    │                   可选覆盖                    │
├────────────────────┼──────────────────┼────────────────────────────────────┼───────────────┼───────────────────────────────────────────────┤
│ _LiveProtocol      │ ProjectLive      │ class XxxLive(ProjectLive)         │ build_request │ extract_output, application_boundary,         │
│                    │                  │                                    │               │ provided_output_raw                           │
├────────────────────┼──────────────────┼────────────────────────────────────┼───────────────┼───────────────────────────────────────────────┤
│ _MockProtocol      │ ProjectMock      │ class XxxMock(ProjectMock)         │ 无            │ scenarios, intent_labels, normalize_case,     │
│                    │                  │                                    │               │ next_turn                                     │
├────────────────────┼──────────────────┼────────────────────────────────────┼───────────────┼───────────────────────────────────────────────┤
│ _JudgeProtocol     │ ProjectJudge     │ class XxxJudge(ProjectJudge)       │ build_context │ normalize_result, reconcile_result            │
├────────────────────┼──────────────────┼────────────────────────────────────┼───────────────┼───────────────────────────────────────────────┤
│ _AttributeProtocol │ ProjectAttribute │ class                              │ build_context │ probes, normalize_result                      │
│                    │                  │ XxxAttribute(ProjectAttribute)     │               │                                               │
├────────────────────┼──────────────────┼────────────────────────────────────┼───────────────┼───────────────────────────────────────────────┤
│ _ToolsProtocol     │ ProjectTools     │ class XxxTools(ProjectTools)       │ 无            │ verifiable_tools, protocol_tools,             │
│                    │                  │                                    │               │ runtime_checks                                │
└────────────────────┴──────────────────┴────────────────────────────────────┴───────────────┴───────────────────────────────────────────────┘

---
项目 adapter

# impl/projects/client_search/adapter.py

class Adapter(ProjectAdapter):
    def _load_live(self):
        from .live import ClientSearchLive
        return ClientSearchLive(self.spec)

    def _load_mock(self):
        from .mock import ClientSearchMock
        return ClientSearchMock(self.spec)

    def _load_judge(self):
        from .judge import ClientSearchJudge
        return ClientSearchJudge(self.spec)

    def _load_attribute(self):
        from .attribute import ClientSearchAttribute
        return ClientSearchAttribute(self.spec)

    def _load_tools(self):
        from .tools import ClientSearchTools
        return ClientSearchTools(self.spec)

---
调用链

pipeline.live_run()
→ adapter = load_adapter(spec)
→ adapter.live().build_request(case)     # 项目实现
→ adapter.live().deliver_real(request)    # 协议层模板方法
    → adapter.live()._build_request(case)   # 协议层调用操作层
    → adapter.live().build_request(case)  # 项目实现
    → adapter.live()._run_llm_judge(...)    # 协议层硬逻辑
    → adapter.live()._normalize_result(...) # 协议层调用操作层
    → adapter.live().normalize_result(...) # 项目可选覆盖

---
总结

┌────────┬──────────────────────────────┬───────────────────────────┬─────────────────┐
│  层级  │             文件             │           内容            │   项目能看到    │
├────────┼──────────────────────────────┼───────────────────────────┼─────────────────┤
│ 协议层 │ impl/core/*_protocol.py      │ _XxxProtocol 类，模板方法 │ ❌ 不能直接继承 │
├────────┼──────────────────────────────┼───────────────────────────┼─────────────────┤
│ 操作层 │ impl/core/*_protocol.py      │ ProjectXxx 类，扩展点     │ ✅ 项目继承这个 │
├────────┼──────────────────────────────┼───────────────────────────┼─────────────────┤
│ 项目层 │ impl/projects/<project>/*.py │ 实现 ProjectXxx 子类      │ 只能看到扩展点  │
└────────┴──────────────────────────────┴───────────────────────────┴─────────────────┘

核心：协议层和操作层在同一个文件里，但分成两个类。项目只继承操作层，协议层对项目不可见。

要我开始写吗？

✻ Cogitated for 1m 2s

※ recap: 目标是把项目 adapter 瘦成统一中转站，逻辑按 live/mock/judge/attribute/tools 
拆到协议层加项目层。刚定下方案：协议方法放不可变基类、可操作方法放继承基类、运行时禁止覆盖。下一步开始写五个角色的基类定义。 (disable recaps in 
/config)

1 tasks (0 done, 1 in progress, 0 open)
◼ 设计模板方法+运行时检查的通用机制






----------------
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

## 三、三层架构

```
抽象层（数据结构）：impl/core/schema/
  定义数据形状（RunTrace / JudgeResult / AttributeResult 等），不承载行为。

协议层 + 操作层：impl/core/*_protocol.py
  _XxxProtocol：模板方法（流程骨架），final，项目不可覆盖。
  ProjectXxx：扩展点（hook），项目继承，实现允许定制的地方。

项目层：impl/projects/<project>/*.py
  实现 ProjectXxx 子类，只看到扩展点。
```

**核心机制**：协议层定义"不能改的流程"（模板方法），操作层定义"可以定制的地方"（扩展点）。项目只能填空，不能改流程。

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

### 三层职责与调用关系

```
┌─────────────────────────────────────────────────────────────┐
│ impl/core/<role>_protocol.py                                │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ _XxxProtocol（协议层）                                  │ │
│ │ - 模板方法（@final，不可覆盖）                           │ │
│ │ - 内部方法（_前缀，不可覆盖）                           │ │
│ └─────────────────────────────────────────────────────────┘ │
│                            ↓ 继承                           │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ProjectXxx（扩展点基类）                                │ │
│ │ - @abstractmethod（必须实现）                           │ │
│ │ - 普通方法（可选覆盖）                                  │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↓ 项目继承
┌─────────────────────────────────────────────────────────────┐
│ impl/projects/<project>/<role>.py                           │
│ - class XxxJudge(ProjectJudge): ...                         │
│ - 实现 build_context()、normalize_result() 等扩展点          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ impl/core/<role>.py                                         │
│ - 通用函数（LLM 调用、校验、转换等）                        │
│ - 被 *_protocol.py 的内部方法调用                           │
│ - 项目不应直接依赖这些函数                                  │
└─────────────────────────────────────────────────────────────┘
```

### 调用链路示例（Judge）

```
pipeline.py:
  adapter.judge().judge_trace(trace)
         ↓
impl/core/judge_protocol.py (_JudgeProtocol.judge_trace):
  1. context = self.build_context(trace)        → 调用项目扩展点
  2. raw = self._run_llm_judge(trace, context)  → 调用通用函数
  3. validated = self._validate_judge_output(raw) → 硬约束校验
  4. return self._normalize_result(trace, validated) → 调用项目扩展点
         ↓
impl/core/judge.py (_run_llm_judge):
  - 实际的 LLM 调用逻辑
  - 通用 prompt 构建
  - 结果解析
         ↓
impl/projects/<project>/judge.py (XxxJudge.build_context):
  - 项目特有的 context 构建逻辑
  - 项目特有的 normalize_result 逻辑
```

### 职责划分原则

1. **协议层 + 扩展点基类**（`*_protocol.py`）：定义流程骨架和项目可定制的地方
2. **通用函数**（`<role>.py`）：可复用的实现逻辑（LLM 调用、校验、转换）
3. **项目实现**（`projects/<project>/<role>.py`）：项目特有的业务逻辑

项目只应实现扩展点基类，不应直接调用通用函数，除非有明确的理由（如工具函数需要复用）。

---

## 十、相关文档

- `spec/info-volume.md` — 通用层 vs 项目层职责边界
- `spec/tool2.md` — VerifiableTool 协议
- `spec/mock.md` — MockAgent 协议
- `spec/live.md` — Live 模块设计
- `impl/project_implementation_standard-template.md` — 项目实现标准模板
