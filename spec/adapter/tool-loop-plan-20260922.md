# ToolLoop 框架：模型自主工具循环与显式完成条件

> 状态：框架及现有调用方已实现。用户已明确授权将 `completion_hook` 设为独立必填参数、将辅助 hooks 改为事件字典。  
> 本文描述当前唯一接口；旧匿名 hook 列表及隐式默认完成条件不再支持。  
> 场景实例参考：[llmtracing 的 ToolLoop 实例化方案](llmtracing-toolloop-instance.md)。

## 0. 一句话

一个 **ToolLoop** = `system_prompt + tools + completion_hook + hooks + client + budget + end`。

模型自主选择工具；框架执行、回放并继续。模型不再调用工具时只是申请结束：必须询问显式传入的核心完成 hook。未满足条件则将原因反馈模型，继续循环。

ToolLoop 自身可以通过 `as_tool()` 暴露为工具，嵌入父 loop。框架不认识六轴、tracing provider、Insurance 或其他业务含义。

## 1. 职责边界

- 框架：驱动循环、执行工具、调度 hooks、隔离调用历史、处理完成/继续/中止、提供嵌套能力。
- 实例：配置任务 prompt/skill、tools、核心完成条件、辅助 hooks 和预算。
- LlmClient：执行单次模型请求，负责路由、请求重试、超时与上下文记录；不在请求内部执行本 loop 的工具。
- 项目 adapter：调用实例、接收结果，不在框架外另写模型重试循环。
- build-eval：离线检验实例效果，不进入运行时控制面，也不把 accepted 当质量分数。

实例优先使用框架已有能力；缺能力时先与框架作者确认，不构建影子框架。框架接口变更必须更新全部在用调用方，不保留兼容层。

## 2. 执行语义与借鉴范围

借鉴 Claude Code 的模型自主工具循环，以及 `PreToolUse`、`PostToolUse`、`Stop` 等生命周期思想。不把外部产品的全部事件复制成当前框架的必需功能。

官方 hooks 页面最近一次访问返回403，未核实最新版完整事件清单；本文事件集合与行为以本地实现为准。

```text
模型回复有 tool_calls
  → 对每个调用执行 pre_tool → 工具 → post_tool
  → 工具结果进入历史 → post_batch
  → 再请求模型

模型回复没有 tool_calls
  → completion_hook.stop + 辅助 stop hooks
     → Done：end提取结果，返回complete
     → Continue(reason)：追加反馈，再进入模型循环
     → Failed(reason)：返回failed，不调用end
```

正常结束必须满足核心完成条件；工具调用期间的预算中止不等模型申请结束。

## 3. 框架接口

### 3.1 构造

```python
ToolLoop(
    id: str,
    system_prompt: str,
    tools: Sequence[VerifiableTool],
    client: StepClient,
    *,
    completion_hook: Hook,                 # 必填，只绑定stop
    hooks: Mapping[str, Sequence[Hook]] | None = None,
    end: Callable[[History], Any] = last_assistant_text,
    max_blocked: int = 8,
    budget: BudgetStop | None = None,
)
```

`completion_hook` 是核心完成条件，不混入辅助列表。任务不需要额外完成要求时，调用方显式传 `Hook()`，表示接受模型自行结束；不能省略参数，也不能传None。

辅助 hooks 按事件注册，字典值为有序 **Hook对象序列**，不是函数、命令字符串或配置DSL：

```python
receipts = ReceiptGate(...)
loop = ToolLoop(
    "evaluation", prompt, tools, client,
    completion_hook=RequireDone(["submit"]),
    hooks={
        "pre_tool": [dependency_check, receipts],
        "post_batch": [receipts],
        "stop": [failure_guard],
    },
    end=take_accepted("submit"),
)
```

注册只激活对应事件的方法。一个对象即使实现了多个方法，注册在pre_tool下也不会自动执行它的start/post_tool/stop。同一对象可显式注册到多个事件，供其共享实例状态。

构造时拒绝：旧匿名列表、未知事件名、非Hook处理器、错误的处理器序列，以及将同一核心完成对象再次注册到辅助stop。

框架复制注册字典和处理器序列，避免调用方后续修改列表悄悄改变注册；不深拷贝Hook对象。可变Hook状态须按case/loop实例隔离。

### 3.2 事件与返回值

|位置|参数|返回|合成规则|
|---|---|---|---|
|completion_hook.stop|history, blocked|Done / Continue(reason) / Failed(reason)|始终参与结束检查，不能被辅助Done覆盖|
|hooks['start']|history, ctx|字符串序列|按注册顺序追加到初始user上下文|
|hooks['pre_tool']|history, call|Allow(args?) / Deny(reason) / Abort(reason)|Abort > Deny > Allow；Deny原因合并；参数改写按顺序传递|
|hooks['post_tool']|history, call|新的工具返回值|按注册顺序链式处理call.result|
|hooks['post_batch']|history, calls|字符串序列|整批完成后按顺序追加反馈|
|hooks['stop']|history, blocked|Done / Continue / Failed|与核心条件一起按Failed > Continue > Done合成|
|end|history|对外返回值|仅正常完成后调用一次，不驱动循环|

支持的辅助事件键为 `start / pre_tool / post_tool / post_batch / stop`。`end` 是独立结果提取函数，不是注册事件。

工具执行异常写入call.error及工具结果，post_tool可据此处理失败；本期不新增独立的工具失败事件。Hook自身异常直接传播，不当作放行；pre_tool/stop的返回类型不合法会抛TypeError，不允许空返回隐式完成。

### 3.3 循环与预算

- 一步调用一次 `StepClient.complete_step`；模型给出一批工具调用，由框架执行后回放。
- 模型无工具调用时结束一个segment，调用核心与辅助stop检查。
- 核心条件先执行，辅助stop按注册顺序执行。所有结束检查仍参与合成：有Failed即失败，否则有Continue即继续，否则完成。
- Continue的reason追加为新的user消息，保留历史上下文；max_blocked限制连续拦回次数。
- budget作为内置pre_tool检查始终排第一，辅助hooks不能移除或绕过它。默认 `BudgetStop(tool_calls=32)`。
- 工具预算包含被拒、未知工具和非法参数调用；未知工具/非法参数只过预算，不触发场景pre_tool语义。
- 达到预算或拦回上限返回failed，无部分完成结果，不调用end。
- BudgetStop.seconds在工具边界检查，单次模型请求的强超时由LlmClient负责；不宣称能强制打断任意阻塞工具。

### 3.4 History 与批次可见性

`History.messages` 是追加式消息历史；`History.calls` 保存调用参数、工具原始返回、错误和拒绝原因。

同一批中各调用的pre_tool只能看到此前已完成批次。批尾才将该批calls写入History并调用post_batch。因此同批read+submit不能声称模型已看到刚读取的正文。

Hook共享状态来自明确的实例对象与History；不通过全局可变列表串案。

### 3.5 loop作为tool

```python
child.as_tool(description, parameters, render=None) -> VerifiableTool
```

子loop成功时父层只收到end返回值，不自动收到整个子历史。失败时父层收到明确的失败对象，是否使父任务失败由父实例的hooks决定。

render可将父层工具参数转换成子loop输入，冻结原始证据由程序注入，不要求父模型转述。只能在父ToolLoop执行工具时调用；trace_id和stage通过ContextVar从父步继承。

### 3.6 模型与记录

`LoopContext(trace_id, stage)` 标识执行。每次请求stage包含loop id、segment及step序号。

`LlmClient.complete_step` 使用公共请求内核、agno外部工具执行暂停与OpenAI形messages；工具在请求之外执行，因此端点重试不会重新执行已经完成的工具。

框架与实例不得另发一套SDK请求来实现循环。每个请求的用量、错误、端点选择和上下文沿原LlmClient机制保存。

## 4. 常用组件

|组件|注册位置|职责|
|---|---|---|
|RequireDone|completion_hook|必需工具各有一次被接受提交才Done；清单可以由History动态计算|
|DependsOn|pre_tool|按工具名检查前置条件，不满足则Deny|
|after / cites_read|DependsOn的条件|要求前置工具成功/被接受或指定引用已读取|
|until_accepted|DependsOn的条件|某提交被接受后不允许再次调用；不是完成条件的替代|
|BudgetStop|独立budget参数，内置pre_tool首位|限制工具数/检查时间|
|take_accepted|end|提取被接受的提交参数，不采用最后一句自由文本|

提交tool负责结构与当前内容检查，pre_tool负责与历史相关的依赖，completion_hook负责是否做完，end负责结果提取。不得用“工具调用成功”冒充“提交已被接受”。

## 5. 实例A：Agno案卷整理

`process_loop/analysis.py`：
- 核心完成条件为 `RequireDone([submit_structure])`。
- 同一个ReceiptGate显式注册在pre_tool和post_batch。
- end提取被接受的整理结果与读取审计。

接口更新不改变Agno原有证据解释、结构整理或判定规则。

## 6. 实例B与llmtracing实例

### Agno六轴父loop

`process_loop/evaluation.py` 将子Analysis作为工具：
- 动态RequireDone独立作为completion_hook。
- 前置依赖、接受后禁止重复以及读取回执注册在pre_tool。
- AnalysisFailed同时注册pre_tool和辅助stop：模型继续调工具或申请结束时都能中止失败任务。
- 读取回执的批尾状态更新注册在post_batch。

六轴共享会话；需要拆成子loop时使用as_tool，不新增另一套循环机制。

### llmtracing六轴实例

`process_loop/llmtracing.py`：
- `completion_hook=SixAxesCompleted(...)`，复用RequireDone并记录未完成反馈。
- DependsOn注册pre_tool，EvidenceReceipts注册post_batch。
- `_finish`作为end提取已接受提交。

provider负责证据能力，框架不引入Agno或llmtracing特有假设。主裁决是否迁入loop是单独的项目决策，不包含在本次框架接口更新中。

## 7. 隔离与错误语义

- 每次run有独立History；调用方为并行任务提供独立的可变Hook实例。
- 注册失败发生在模型调用前；运行中Hook异常不会被默认为Done。
- 核心completion返回Continue/Failed时，辅助Done不能放行。
- 辅助stop返回Failed时，核心Done也不能强行完成。
- 工具错误、框架失败、被测业务fail分别表达，不通过salvage掩盖未完成任务。
- ToolLoop未被调用的项目不因此切换执行路线；本次只更新现有调用方的构造方式。

## 8. 验证与实施范围

框架实现：`impl/core/tool_loop/` 包，对外统一从 `impl.core.tool_loop` 导入。

- `types.py`：运行记录、StepClient、Hook 协议与决策类型。
- `runtime.py`：循环、工具执行、hook 调度与嵌套。
- `hooks.py`：依赖条件、RequireDone、BudgetStop 等通用组件。
- `outputs.py`：最终结果提取策略。
- `__init__.py`：公共 API 导出；不保留旧 `tool_loop.py` 文件或转发层。

本次目录化不改变事件、预算、完成检查或失败语义。实现指纹包含包内全部 Python 模块。

现有调用方：
- `impl/projects/llm_probe/process_loop/analysis.py`
- `impl/projects/llm_probe/process_loop/evaluation.py`
- `impl/projects/llm_probe/process_loop/llmtracing.py`

测试：
- `tests/test_tool_loop_package.py`：公共 API 类型一致、模块依赖边界、实现指纹覆盖全部包源码。
- `tests/test_tool_loop_registration.py`：必填参数、事件字典、未知注册拒绝、事件隔离、顺序、核心与辅助stop合成、非法返回、注册列表复制。
- `tests/test_tool_loop.py`：真实LlmClient对接本地假OpenAI，覆盖非流式/流式循环、依赖、预算、重试、工具失败与嵌套。
- `tests/test_process_loop.py`：Agno父子loop行为不变。
- `tests/test_llmtracing_tool_loop.py`：六轴完成、反馈继续、end、失败及实例隔离。

冻结的旧评测输入、历史源码快照和历史判词不随接口更新改写；它们是旧版本记录，不是需要兼容执行的调用方。再次实测须登记新源码版本，不能继续标称无改动对照。

## 9. 非目标

不增加动态工具列表、权限交互、压缩事件、通用DAG、另一套SDK循环或治理LLM。不修改业务判准、样本答案、模型配置，不因框架接口更新声称语义评判更准确。

## 10. 验收标准

1. 缺completion_hook不能构造；旧hook列表不能构造。
2. 事件未注册，不执行该对象相应方法。
3. 模型持续调工具时正常推进；模型停下后才执行完成检查。
4. 核心条件不满足则带原因继续；硬失败不能被辅助Done覆盖。
5. 预算和max_blocked仍有效；失败不执行end。
6. 已有Agno与llmtracing实例经新接口运行，原依赖与提交行为保留。
7. 本地假服务验证和项目回归通过后，再单独申请真实模型评测；代码测试不当作质量成绩。

本次验收：新增22项注册与核心完成契约测试；全量 **1648 passed、5 skipped，仍为此前已记录的11个失败**，473.70秒。
请求客户端和主裁决源码哈希未变化；没有调用真实模型、重启服务或提交代码。

## 11. 后续

当前接口已按用户授权实施，不再保留“等待确认后才字典化”的状态。新的事件类型或框架能力仍应说明真实需求后与作者确认，不因为接口已经开放就不断增加预防性扩展。
