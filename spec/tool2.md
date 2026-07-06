我来先看看这两个文档，了解当前 tool 的设计和需求。

  Read 2 files (ctrl+o to expand)

⏺ I've read both specs. Let me understand the current tool implementation to ground the discussion.

  Read 5 files, listed 1 directory (ctrl+o to expand)

⏺ 我看完了 spec/tool.md、demand/tool.md，以及当前 impl/tools 和项目级 tool
  的实现。先说我的理解，再指出问题，最后给方向——我们一节一节对齐。

  一、Spec/Demand 想表达什么

  把两份 md 合到一起，它对 tool 的核心主张是三条：

  1. Tool 的本质 = 把业务系统里"可能有用的源代码函数"包成可调用单元。来源是业务系统源码，不是 verifier 自己编。
  2. 两层划分依据是"获取信息的方式"，不是"问题难易"：
    - 第一层（pipeline 预执行）：固定流程产出，确定性高、不需 LLM，每个 case 都跑（如 get_runtime_checks
  查表、simulate_trace_nodes 沿 trace 逐段重放）。
    - 第二层（LLM 动态调用）：上下文太多塞不进 prompt，或组合方式不固定，需 LLM 先判断缺什么再查什么。
  3. attr 的 tool 要做"live 链路拆解"：从业务系统源码出发，把 live 一次执行经过的确定性环节拆成"输入 schema → 业务函数 → 输出
  schema"的局部链路段；第一层沿这条链路按业务执行顺序逐段重放对照 trace.actual
  定位最早分歧；第二层把第一层够不到的段/相邻函数暴露成 tool。

  关键纠偏点（spec 自己写明）：主是业务系统 live 链路，trace 节点只是映射到这条链路上的快照样本。拆解依据来自源码，不来自 trace
  形状。

  二、当前实现的问题（对照 spec）

  #: 1
  问题: tool 来源错位
  现状: runtime_tools.py 的三个 tool（get_call_trace / get_function_signature / get_config_value）几乎全是从
    RunTrace.execution_trace 读字段 + 字符串拼装
  spec 要求: 应来自业务系统源码函数
  ────────────────────────────────────────
  #: 2
  问题: 第一层/第二层职责混淆    
  现状: runtime_tools.py 标榜"减少 tool call 6-10→2-3"，但 get_call_trace 自己就做了 divergence_point / next_steps 
    这种结论判断（_suggest_next_steps 按 stage 名硬编码建议）
  spec 要求: tool 只返回信息，不替 LLM 做判断
  ────────────────────────────────────────
  #: 3  
  问题: 没有"局部链路模拟单元"
  现状: 整个 impl/tools 里没有任何"输入 schema → 业务原函数 → 输出 schema"的可重放闭环。simulate_trace_nodes                  
    这类核心一层的单元根本不存在
  spec 要求: 第一层逐段重放、第二层暴露相邻段，都依赖这个最小颗粒
  ────────────────────────────────────────
  #: 4
  问题: 协议层混了两套抽象
  现状: protocol.py 同时有 ProtocolTool.run(context)（context 注入式）和 AgnoToolCall/agno_toolkit（agno Function
    式），_to_agno_function 里 entrypoint 还是 raise RuntimeError
  spec 要求: 一个 tool 体系要么 context-bound 要么 agno-callable，不要两套并存且互相 raise
  ────────────────────────────────────────
  #: 5
  问题: 项目级 tool 与通用 tool 边界模糊
  现状: search_condition_compare.py 放在项目 tools 下（合理），但通用层 field_retrieval / source_retrieval 也是"协议 +
    provider"模式，runtime_tools 又是另一套 factory 风格，三套写法不统一
  spec 要求: 通用层只放协议+provider 接口，项目层实现 provider；写法要统一
  ────────────────────────────────────────
  #: 6
  问题: trace 被当拆解依据
  现状: get_call_trace 直接 for step in execution_trace 拆段，正是 spec 点名批评的"沿 trace 节点拆"
  spec 要求: 应沿业务系统 live 链路拆，trace 节点只做对照样本

  三、问题 4 之外都还收敛，真正卡住的是 1+3

  把上面六条归类：
  - 结构性问题：1（来源错位）、3（缺最小颗粒）、6（拆解依据错）——这三条是同一件事的三个面：当前根本没有"业务系统 live 链路 →
  局部链路模拟单元"这条主线。
  - 职责问题：2（tool 替 LLM 下结论）——get_call_trace 里的 next_steps/divergence_point 应该砍，只留 stage 级
  input/output/expected/actual 原始对照。
  - 工程问题：4（两套抽象并存）、5（三套写法不统一）——值得修，但只有在 1+3 的主线立起来之后修才有意义，否则又是空架子。

  四、建议的方向（先对齐再动手）

  我倾向这样重构，但想先跟你确认：

  1. 统一 tool 协议为单一形态：context-bound 的 ProtocolTool（已有）作为唯一抽象，砍掉 AgnoToolCall/agno_toolkit
  那条并存的线。第二层 LLM 调用走"LLM 产出 tool_id+params → registry.run(tool_id, context)"，不直接喂 agno Function。
  2. 引入"局部链路段（Segment）"作为一等公民：定义 LiveSegment（input_schema / biz_function / output_schema /
  depends_on），从业务系统源码拆出来。这是第一层重放和第二层 tool 共用的最小颗粒——spec 第 2-3 步要求的东西。
  3. 第一层 = simulate_live_chain：沿 segment 列表按业务执行顺序重放，用 trace 节点 evidence 当输入、trace.actual 当对照，标
  passed/diverged，定位最早分歧。这是 spec 第一层。
  4. 第二层 tool = segment 的按需暴露：把第一层全量跑不到的相邻段、参数化查询、配置查询包成 tool。砍掉 get_call_trace
  的结论判断部分，只返回原始对照。
  5. 通用层只留协议+provider 接口：field_retrieval/source_retrieval
  的"协议+provider"模式是对的，保留并作为标准范式；runtime_tools.py 那套 factory 风格并入或废弃。

  在动手前，有两个分叉我想听你的：

⏺ User answered Claude's questions:
  ⎿  · 局部链路段（LiveSegment）的拆解来源怎么定？spec 说从业务系统源码拆，但源码结构每个项目不同。 → 通用层做自动拆解器
     · 现有 runtime_tools.py 的三个 tool 怎么处置？ → 整体废弃，由 segment 体系取代
     · tool 协议要不要统一成单一 context-bound 形态？ → 保留 agno 桥接
  
⏺ 你的选择我先复述一遍确认没歪：

  1. 拆解来源：通用层做自动拆解器 —— 不依赖每个项目手写 segment 列表，由通用层从业务系统源码/调用图自动拆出 LiveSegment。
  2. runtime_tools.py：整体废弃，三个 tool 的能力并入 segment 体系（第一层重放产出 stage 级对照信息；签名/配置查询作为第二层
  tool）。
  3. 协议形态：保留 agno 桥接 —— 不强行收敛成单一 context-bound，第二层继续喂 agno Function 给 agent。

  这三个选择里有一个我必须先标出来的张力，否则后面设计会拧着。先说这个，然后给整体设计。

  核心张力：自动拆解器 vs agno 桥接

  spec/tool.md 的关键论点是：拆解对象是业务系统 live 链路本身，每段是"输入 schema → 业务系统函数 → 输出 
  schema"的闭环。这意味着拆解器必须能从源码里识别出"哪个函数是 live 链路上的一段、它的输入 schema 和输出 schema
  是什么、段间依赖怎么连"。

  而 agno 桥接是第二层 LLM 动态调用用的，它只关心 tool 的入参/出参描述，不关心 segment 怎么拆。这两件事可以共存，但要分清：

  - 自动拆解器产出的是 LiveSegment 对象（input_schema, biz_function, output_schema, depends_on），它是第一层重放 + 第二层 tool 
  的共同数据源，不是 tool 本身。
  - agno 桥接只是把 segment（或 segment 衍生出的查询能力）包装成 agno Function 喂给 agent。

  所以"保留 agno 桥接"和"自动拆解器"不冲突，但前提是把拆解器和tool 包装层分成两层。现在的代码混在一起（runtime_tools.py
  既是链路分析又是 tool），所以才乱。

  整体设计

  我按这个张力把改造拆成三块，你看看哪块要先做、哪块要调整。

  第一块：LiveSegment 自动拆解器（通用层，新增）

  位置：impl/core/live_segment.py（或 impl/tools/segment_discovery.py）

  输入：ProjectSpec（拿到业务系统 root、adapter 路径、source_config_paths）+ 可选的 trace 样本。

  拆解器职责：
  1. 定位 live 链路入口：从 adapter 的 simulate_live / run_live 之类入口函数出发，沿调用图往下走。
  2. 识别确定性段：每遇到一个"输入 schema → 转换函数 → 输出 schema"的闭环就切一段。切分判据是：函数有明确的输入参数
  schema、输出是确定性转换（非 LLM、非 IO 随机）、且上下游通过返回值传参。
  3. 标注非确定性段：LLM 调用、外部 IO 段单独标
  nondeterministic=True，这些段第一层不重放（重放不出确定结果），只作为第二层探查对象。
  4. 输出 segment 列表：List[LiveSegment]，每段带 segment_id, input_schema, biz_function_ref, output_schema, depends_on, 
  deterministic。

  拆解器的"自动"程度需要你拍一下，因为这是整个方案最不确定的地方：

  - 纯静态分析（AST + 调用图）：完全自动，但对"输入/输出 schema"只能靠类型注解推断，没注解的函数拆不出。
  - 半自动（静态为主 + trace 辅助）：用 trace 节点辅助识别 schema 形状（trace 里有 input/output
  样本），静态分析负责定段边界。spec 里那句"trace 节点是验证样本不是拆解依据"说的就是不要让 trace 主导分段，但用作 schema
  形状提示是允许的。
  - 声明式为主 + 静态校验：每个项目在 adapter 里写一份 segment 声明（轻量），通用层只做静态校验（函数存在、签名匹配、依赖闭合）。
  这其实就是你否掉的"项目级显式声明"，但我想确认你否的是"完全手写"还是"手写 + 自动校验"。

  第二块：第一层重放器（通用层，新增/改造）

  位置：impl/core/trace_replay.py

  职责：沿拆解器产出的 segment 列表按依赖顺序逐段重放，对照 trace.actual 标 passed/diverged，定位最早分歧。这就是 spec
  第一层。它取代 runtime_tools.py 的 get_call_trace——但产出的是原始 stage 对照信息，不再带 divergence_point.reason / next_steps
  这种结论判断（spec/tool.md 第 28 行明确说 tool 不替 LLM 做判断）。

  第三块：第二层 tool 包装（保留 agno 桥接）

  位置：impl/tools/protocol.py（继续用）+ impl/tools/segment_tools.py（新增）

  第二层 tool 来自两类：
  1. 第一层够不到的 segment：非确定性段（LLM 调用）、相邻段、参数化查询段 → 包成 agno Function 给 LLM 按需调。
  2. 段衍生的查询能力：get_function_signature / get_config_value 的能力并到这里，但实现改成"读 segment 的 biz_function_ref
  元信息"，而不是现在的独立 provider 链。

  agno 桥接保留：ToolRegistry.agno_toolkit() / agno_functions() 这条线继续用。但要把现在 protocol.py 里那套"context-bound
  ProtocolTool"和"agno Function"双轨并存的拧巴收敛一下——具体说就是 _to_agno_function（raise RuntimeError 那个）和
  _to_agno_callable 两个中至少砍一个。

  ---
  在我写代码之前，有一个点必须你定，因为它决定了拆解器的可行性和工作量：

  自动拆解器靠什么识别"业务系统函数"和"输入/输出 schema"？ 纯静态（只看 AST 和类型注解）在很多项目上会拆不全；而完全靠 trace
  样本又违背 spec。我倾向"静态为主 + trace 辅助 schema
  形状"，但你业务系统的源码里类型注解覆盖率怎么样？如果大部分函数没注解，纯静态路线基本走不通，得退到半自动或声明式+校验。

  你先回答这个，我再决定拆解器第一版的实现路线。




---------



你这个判断方向是对的——这一串东西本质上是**一件事的不同切面**，应该作为一个整体来设计，而不是逐个零敲碎打。我把它们之间的依赖关系理一下，让你看清为什么必须一起设计：

## 为什么这些必须打包做

它们共享同一个数据模型，分散改必然出现"协议层这样、adapter 那样、trace 又是另一个形状"的脱节（QA ready 那个问题就是先例）：

1. **schema（数据骨架）**：`LiveSegment`（input_schema / biz_function / output_schema / depends_on / deterministic）+ `RunTrace` 上挂 `ready`（如果走方案 A）。所有其他层都引用它。
2. **后端 API**：第一层重放产出 stage 级对照信息（passed/diverged + 最早分歧），这决定了 API 返回的结构。它消费 schema，又决定前端怎么展示。
3. **前端**：展示链路分段、分歧点高亮——形状完全由后端 API 决定。
4. **tool（agno 桥接）**：第二层 LLM 调用的 tool，来自"第一层够不到的 segment"和"段衍生的查询能力"。它的入参出参依赖 segment schema。
5. **live trace 拆解器**：产出 `LiveSegment` 列表，是 1/2/4 的共同数据源。

**依赖链**：拆解器 → segment schema → {重放器(后端API) / tool 包装} → 前端展示。

所以正确的顺序是 **schema 先定，拆解器次之，然后重放器和 tool 并行，最后前端**。schema 没定之前动任何一层都是返工。

## 但有一个前提必须先解决

之前没回答的那个点：**自动拆解器靠什么识别业务系统函数和输入/输出 schema**。这是整串改造的根，因为它决定了 `LiveSegment` 的 schema 长什么样——纯静态（AST+类型注解）拆出的 segment 字段，和半自动（trace 辅助）拆出的字段形状不一样。这个不定，schema 就是空中楼阁。

## 建议的推进方式

不要一次性铺开五条线。先做两步：

1. **定 segment schema + 拆解器策略**（回答上面那个前提问题）。这一步只产出一个 `LiveSegment` 的 dataclass 定义 + 拆解器的工作方式说明，不写实现。
2. **在 client_search 一个项目上手工拼出一份 segment 列表跑通全链路**，验证 schema 设计对了。这是 spec/tool.md 说的"复用步骤"的干跑。
3. 之后再谈通用拆解器自动化、后端 API、tool 包装、前端。

也就是说：**先手工闭环验证数据模型，再谈自动化和前后端**。否则你五条线一起开，schema 一改全员返工。

如果认同这个顺序，下一步就是回答"拆解器第一版用纯静态还是半自动"——这取决于你业务系统源码的类型注解覆盖率。你那边源码注解情况怎么样？





-------



## 方案总结

### 整体思路

把"tool 构建"从当前的零散状态（runtime_tools 读 trace 字段 + 字段检索 + 源码检索，各走各的）收敛为一套以 **LiveSegment 拆解**为核心的体系：

**核心理念**（来自 spec/tool.md）：拆解对象是业务系统的 live 链路，每段是"输入 schema → 业务系统函数 → 输出 schema"的闭环。拆解后的 segment 同时服务于第一层重放（定位最早分歧）和第二层 tool（LLM 按需探查）。

### 数据流

```
业务系统源码 + mock 动态收集
        ↓
   拆解器（静态定边界 + 动态定形状）
        ↓
   LiveSegment 列表 → impl/projects/<project>/schema/
        ↓
   ┌─────────────────┬──────────────────┐
   ↓                 ↓                  ↓
第一层重放器      第二层 tool 包装     前端展示
(后端 API)       (agno 桥接)        (链路分段+分歧高亮)
```

### 改造内容

1. **通用层 schema**：`impl/core/schema.py` 新增 `LiveSegment` dataclass
2. **拆解器**：静态分析（AST/调用图）定段边界 + 动态 mock 收集定 schema 形状
3. **项目级 schema**：`impl/projects/<project>/schema/` 存拆解产出的 segment 实例
4. **第一层重放器**：沿 segment 列表逐段重放，对照 trace.actual 标 passed/diverged，定位最早分歧。取代 runtime_tools.py 的 get_call_trace
5. **第二层 tool**：第一层够不到的 segment（非确定性段、相邻段）包成 agno Function
6. **runtime_tools.py**：整体废弃，能力并入 segment 体系
7. **前端**：展示链路分段、分歧点高亮

### 可行性判断

**可行**。核心逻辑是自洽的：
- 静态 + 动态两条数据源互补，覆盖了"无类型注解"和"无外部 tracing"的盲区
- 拆解器产出物直接喂给重放器和 tool 包装，不需要中间转换
- 和现有目录结构（impl/core、impl/projects、impl/tools）对齐，不需要大动骨架

### 卡点

1. **mock 输入的代表性**：单份 mock 拆不全 schema（可选字段、条件分支会漏）。需要多份覆盖不同分支的 mock 跑合并。对策是用 trace 节点的 evidence 当 mock 输入，但 trace 可能也只覆盖了部分分支。

2. **确定性判别**：动态跑两次比对来判断一段是否确定性，有成本（跑两遍）也有边界情况（隐藏随机源如时间戳、缓存）。需要静态分析先标候选再动态确认。

3. **副作用隔离**：动态调真实业务函数可能触发外部副作用。需要沙箱/拦截层，这是拆解阶段和重放阶段的共同问题，值得统一设计。

4. **通用拆解器 vs 项目差异**：静态分析提取调用图的能力高度依赖项目语言和结构。Python 项目 AST 好做，但如果业务系统是其他语言（或混合语言），拆解器需要适配。第一版先按 Python 做，后续扩展。

5. **schema 格式的版本管理**：项目级 schema 存到 `impl/projects/<project>/schema/` 后，业务系统源码改了怎么办？需要"过期检测"机制（对比源码 hash 或函数签名），否则重放用的 segment 和实际函数不一致，结果不可信。





---------



对，这个点很关键，它改变了"有损"的边界。之前方案里把 heavy env 段一刀切标为"不可重放"，是因为默认只能在本地跑。但如果业务系统能暴露局部接口或远程执行权限，这些段就从"不可重放"变成"可远程重放"，有损程度大幅下降。

## 这个补充对方案的影响

**env_class 要扩出"远程可执行"这一类**。原来的四级（none/light/heavy/unavailable）是按"本地能不能跑"分的，现在要加一个维度——"能不能通过远程接口/远程执行权限跑"。一个依赖中间件的段，本地跑不起来（heavy），但如果业务系统提供了远程测试接口或远程执行入口，它能远程重放。所以 env_class 应该变成：

- `none`：纯转换，本地直接跑
- `light`：本地轻量环境可跑
- `remote`：本地跑不了，但能通过业务系统暴露的远程接口/远程执行权限重放
- `unavailable`：既不能本地跑、也没有远程入口，真正不可重放

**segment schema 要新增字段**。每个段不只声明环境依赖，还要声明"远程重放入口"——如果这个段能远程跑，它的入口是什么（一个 HTTP 接口、一个 RPC 方法、一个远程函数调用句柄）、入参怎么传、鉴权怎么做。这是项目级 adapter 要提供的配置。

**重放器执行内核要新增一种执行路径**。原来是"直接调 / mock 上下文 / 跳过"三种，现在加第四种"远程调用"——把 segment 的输入通过远程接口发给业务系统，拿回输出做对照。这条路径绕开了本地环境构建，verifier 不需要部署中间件，但需要能连到业务系统的远程入口。

**有损评估指标相应调整**。coverage 的分母不变（总段数），但分子从"本地可重放段数"变成"本地可重放 + 远程可重放段数"。unavailable 段占比才是真正的有损下限。divergence_bound 也收窄——原来被 heavy 段夹击的盲区，现在很多能被 remote 段填补，定位精度提升。

## 重新整理后的方案差异

其余九节（核心定位、数据模型、拆解器、第一层重放器、有损评估、第二层 tool、废弃清理、后端 API/前端、推进顺序）的结构不变，主要改三处：

1. **数据模型**：`LiveSegment` 的 `env_class` 扩成 none/light/remote/unavailable 四类，新增 `remote_entry` 字段（远程入口声明，可选）。
2. **第一层重放器**：执行内核新增远程调用路径，按 env_class 分流——none 直接调、light 走 mock、remote 走远程入口、unavailable 跳过标盲区。
3. **有损评估**：coverage 分子纳入 remote 段；真正有损的只剩 unavailable 段。

## 带来的新卡点

- **远程入口的覆盖度**：业务系统能暴露多少远程接口是不确定的。可能只有最终 live 接口、可能有一些中间接口、也可能有完整的远程执行权限。覆盖度直接决定 remote 段能占多少。
- **远程调用的副作用与隔离**：远程重放调的是真实业务系统，副作用（写操作）会落到真实环境。需要远程入口侧支持测试模式/影子库，或者只调只读接口。
- **远程调用的稳定性与成本**：远程调用有网络开销、可能限流、可能超时。并行重放时远程入口的并发承受能力要评估。
- **鉴权与环境上下文**：远程接口通常要鉴权，且远程侧的环境（连的是哪个库、哪个配置）要和 trace 采样时的环境对齐，否则对照失真。

核心还是那句话：verifier 不承担完整部署，但能利用业务系统暴露的远程入口把有损边界往外推。这把"有损"从"本地能力决定"变成"远程入口覆盖度决定"，是个实质性的改善。






--------



基于前面讨论定的架构（LiveSegment 拆解 + 有损重放 + 远程入口扩展），我把 schema、后端 API、前端三层的整合方案梳理一下。这是设计层面的整合，不涉及实现。

## 一、Schema 层

### 1. 通用层 `impl/core/schema.py`

**LiveSegment**（核心数据模型）：
```
segment_id: str
input_schema: dict          # 输入字段定义
output_schema: dict         # 输出字段定义
biz_function_ref: str       # module.function
depends_on: list[str]       # 上游段 id
deterministic: bool
env_class: str              # none | light | remote | unavailable
env_deps: list[str]         # 环境依赖声明
remote_entry: dict | None   # 远程入口声明（接口路径/方法/鉴权/上下文对齐信息）
```

**ReplayResult**（重放产出，不含结论判断）：
```
segment_id: str
status: passed | diverged | blindspot      # blindspot = unavailable 段
expected: dict | None
actual: dict | None
evidence: str
exec_path: local | mock | remote | skipped # 实际走的执行路径
```

**ReplaySummary**：
```
segments: list[ReplayResult]
first_divergence: segment_id | None
blindspots: list[segment_id]               # 不可重放段位置
coverage: float                            # (none+light+remote) / total
unavailable_ratio: float                   # unavailable / total，真正有损下限
gap_structure: continuous | scattered      # 不可重放段分布
divergence_bound: [start_seg, end_seg]     # 最早分歧能定位的最小区间
```

**ExecutionContext**（执行环境注入接口）：adapter 协议的注入点，声明"这个段怎么跑"。

### 2. 项目层 `impl/projects/<project>/schema/`

- `segments.json`：拆解器产出的 LiveSegment 列表（可版本管理、可手工修正）
- `remote_entries.yaml`（可选）：项目配置的远程入口清单（接口、鉴权、环境对齐）

## 二、后端 API

围绕"拆解结果 + 重放结果 + 有损指标"三组数据组织：

**拆解相关**：
- `GET /projects/<id>/segments` → 返回 segment 列表 + coverage/gap 等元信息
- `POST /projects/<id>/segments/refresh` → 触发重新拆解（源码变更后）

**重放相关**：
- `POST /projects/<id>/replay` → 入参 case_id（或 trace_id），沿 segment 重放，返回 ReplaySummary
- `GET /replay/<run_id>` → 取某次重放结果（含每段 ReplayResult）
- 重放结果里带 `exec_path` 字段，前端能区分哪些段走了本地/远程/跳过

**有损评估**：
- `GET /projects/<id>/segments/loss-profile` → 返回 coverage、unavailable_ratio、gap_structure、divergence_bound，作为项目级有损画像

**第二层 tool（agno 桥接）**：不走 REST，仍由重放器内嵌的 ToolRegistry 提供 agno Function 给 LLM agent 调用，拿到的归因结论挂在 ReplaySummary 上（新增 `attribution` 字段）。

## 三、前端样式

链路分段展示为核心，三个视觉层次：

**1. 链路分段视图**（主视图）：
- 横向排列的段卡片，按 depends_on 顺序连成链
- 每段卡片标注：segment_id、biz_function_ref、env_class 色标、deterministic 标记
- env_class 配色：none（绿）/ light（蓝）/ remote（紫）/ unavailable（灰）

**2. 重放结果叠加**：
- 重放后，每段卡片叠加状态：passed（绿勾）/ diverged（红叉）/ blindspot（灰盲）
- 分歧段高亮放大，展示 expected vs actual 对照
- 盲区段用虚线边框 + "无法重放"标记

**3. 有损指标面板**（侧栏或顶部）：
- coverage 进度条
- unavailable_ratio 数值
- gap_structure 图示（连续块画成一段灰条，散布画成多个小灰点）
- divergence_bound 标注在链路上的区间范围

**4. 归因结论区**（底部）：
- 展示第二层 LLM 的归因结论
- 标注"基于哪些段的重放结果 + 调了哪些 tool"

## 四、三层的依赖关系

schema 先定 → 后端 API 消费 schema 形状 → 前端消费 API 返回结构。三者共享同一组字段命名（env_class、exec_path、blindspot、coverage 等），避免脱节。这是之前 QA ready 问题（协议层/adapter/trace 形状不一致）的防范——这次三层字段统一从 LiveSegment/ReplayResult 派生，不各自发明。

## 五、需要你再拍板的点

1. **remote_entry 的鉴权与环境对齐**谁负责——verifier 侧配，还是业务系统侧提供标准接口？
2. **归因结论**（attribution 字段）是同步阻塞产出还是异步——批量评测场景下可能要异步。
3. **前端是新建页面还是扩展现有** `impl/frontend/live.html` / `summary.html`——现有页面已经有 trace 展示，segment 视图是叠加还是独立。

这三个定了，schema/API/前端就能进入具体设计。




-------



你说得对，现在这几个 tool 的问题不是"不该存在"，而是**太浅了**——只停留在"查个字段定义""读个文件""看个 trace 节点"这种表层信息检索，离"真正辅助归因"差得远。

## 现有 tool 为什么不够

- `field_retrieval`：查字段定义——这是静态字典查询，归因时 LLM 需要的是"这个字段在链路里怎么被处理、为什么值变成了这样"，不是"字段叫什么"。
- `source_retrieval`：读源码文件——这是把整份文件丢给 LLM 自己看，没有结构、没有重点，token 浪费在无关代码上。
- `runtime_tools` 的 get_call_trace：从 trace 字段拼调用链——但 trace 只记录了实际执行路径，**没有对照基线**，LLM 看到的是"这里输出了 other"，却不知道"这里本该输出什么"，无法定位分歧。

它们共同的问题：**都是信息搬运，不是验证**。归因的核心是"期望 vs 实际的对照定位"，现有 tool 没有一个能产出这个对照。

## 需要什么样的 tool 才够"深入"

真正辅助归因的 tool 应该能回答这类问题：

1. **链路关键函数定位**：给一个 case，自动找出"这个 case 的 live 执行经过了哪些关键函数、它们之间的数据流是什么"。不是读整份源码，而是只返回这条链路上的函数签名 + 入参出参类型 + 调用顺序。这比 `source_retrieval` 精准得多。

2. **局部函数可执行验证**：不只是"告诉你这个函数长这样"，而是**真的能跑这个函数**——给输入，跑出输出，让 LLM 对照 trace 里的 actual 看这个函数到底有没有问题。这才是"验证"，而不是"描述"。这一类 tool 才是归因的核心——它能产出"期望 vs 实际"的对照。

3. **数据流追溯**：某个字段在链路里被哪个函数读取、被哪个函数修改、最终在哪里被用来做决策。这是字段级别的链路，不是函数级别的——比 `field_retrieval` 的静态定义深一层。

4. **配置/规则的生效验证**：不是"读一个配置值"（现在的 get_config_value），而是"这个 case 的输入，触发了哪条配置规则、规则是怎么计算的、结果是什么"。配置是死的，规则执行是活的，归因要看活的。

## 这和之前讨论的关系

其实你绕回了之前 segment 方案想解决的问题——**可执行的局部链路验证**。区别在于：

- segment 方案要求**预先拆完整条链路**，太重。
- 现在的"指引"方案如果只停留在浅层检索，又太轻，满足不了归因。

中间的平衡点是：**不预拆整条链路，但让项目 adapter 能把"对归因真正重要的那几个关键函数/局部链路"做成可执行 tool**。也就是——不需要 segment 的全量拆解，但要有 segment 的"可执行验证"能力，只是范围收窄到"真正重要的部分"，由项目自己挑选。

换句话说，tool 要从"信息检索"升级到"可执行验证"，但"选哪些函数做成可执行 tool"这件事，从通用层自动拆解放回到项目层手工挑选关键函数。这是你之前 light 化方向的延续，但加上了"tool 必须能验证、不能只是搬运"的要求。





-------



## 完整解决方案（tool 从信息检索升级到可执行验证）

### 核心思路

通用层不预拆链路，但提供"可执行验证 tool"的协议和编排能力。项目 adapter 手工挑选对归因真正重要的关键函数/局部链路，做成可执行 tool。tool 的核心价值是产出"期望 vs 实际"的对照，不是搬运信息。

### 一、Schema 层

**VerifiableTool（新协议）**——可执行验证 tool 的统一抽象：
```
tool_id: str
description: str              # 一句话说明用途
applicable_scenario: str      # 什么场景下该调它
input_schema: dict            # LLM 传什么参数
output_schema: dict           # 返回什么结构
execute_fn: Callable          # 真正能跑的函数
```

**ToolResult（升级）**——必须能承载对照信息：
```
tool_id: str
executed: bool                # 是否真的执行了（vs 只查询）
actual: dict | None           # 实际输出
evidence: str
status: passed | diverged | inconclusive
```

通用层不定义 LiveSegment——segment 概念退化为项目 adapter 内部的实现细节，不是通用 schema。

### 二、通用层职责（impl/core/ + impl/tools/）

只做三件事：

1. **Tool 协议**：定义 VerifiableTool 接口 + ToolResult 结构。
2. **Tool 注册与发现**：统一注册表，LLM 拿到 tool 目录（tool_id + description + applicable_scenario），按需调用。
3. **编排调用**：接收 LLM 的 tool 调用请求，执行 execute_fn，返回 ToolResult。

不做拆解器、不做重放器、不做执行内核。执行能力由项目 adapter 的 execute_fn 自己提供（本地跑、mock 跑、远程调，通用层不关心）。

### 三、项目层职责（impl/projects/<project>/adapter.py）

新增 `get_verifiable_tools() -> List[VerifiableTool]`。项目自己挑选关键函数/局部链路，做成四类可执行 tool：

1. **链路关键函数定位**：给 case，返回这条 live 执行经过的关键函数签名 + 入参出参类型 + 调用顺序（不返回整份源码）。
2. **局部函数可执行验证**：给函数 + 输入，真跑出输出，对照 trace actual 标 passed/diverged。这是归因核心——产出期望 vs 实际对照。
3. **数据流追溯**：字段级别——某字段被哪个函数读、被哪个函数改、最终在哪做决策。
4. **配置规则生效验证**：给 case 输入，跑出触发了哪条规则、结果是什么（不是读死配置）。

### 四、第二层归因

LLM 拿到 case 的 trace + tool 目录，自主决策调哪些 tool、传什么参数。可执行验证 tool 直接产出对照结果，LLM 拿到对照后推理归因结论。结论挂在归因结果上。

### 五、废弃与收敛

- `runtime_tools.py`：废弃。get_call_trace 的对照能力并入项目 adapter 的"链路关键函数定位 + 局部函数验证"组合。
- `field_retrieval.py` / `source_retrieval.py`：保留但降级为辅助 tool，不作为归因主力。
- `protocol.py`：砍掉 `_to_agno_function` 双轨，保留 agno 桥接。

### 六、后端 API + 前端

- API：返回归因结论 + 调了哪些 tool + 每个 tool 的 ToolResult（含对照信息）。
- 前端：展示归因结论、tool 调用链、关键 tool 的 expected vs actual 对照可视化。

### 七、推进顺序

1. 定 VerifiableTool + ToolResult schema
2. client_search 上手工挑 2-3 个关键函数做成可执行 tool 跑通归因闭环
3. 通用层注册/编排/ agno 桥接收敛
4. 扩展到其他项目，逐步补充各类可执行 tool
5. 后端 API + 前端

### 八、和之前方案的区别

- 砍掉：通用拆解器、LiveSegment schema、重放器、执行内核、环境构建体系。
- 保留：可执行验证能力（这是 segment 方案想解决的核心），但范围从"整条链路全量拆"收窄到"项目手工挑选关键函数"。
- tool 从"信息搬运"升级到"可执行验证 + 期望实际对照"。

核心定位：通用层管协议和编排，项目层负责挑哪些函数值得做成可执行验证 tool。不再追求全量链路模型，只追求"对归因真正有用的那几个函数能被验证"。





--------



## 可执行验证 tool 构建与实现方案

### 一、核心定位

tool 从"信息搬运"升级到"可执行验证"。通用层管协议和编排，项目层负责挑选关键函数做成可执行 tool。tool 服务于 judge、attr 等所有阶段，不绑定特定环节。

### 二、数据模型（impl/core/schema.py）

**VerifiableTool**（精简后）：
```
tool_id: str
description: str              # 什么时候用、做什么
applicable_scenario: str      # 适用场景（judge/attr/通用）
parameters: dict              # 入参定义，直接对齐 agno/OpenAI function calling 格式
execute_fn: Callable          # 真正能跑的函数
```

**ToolResult**（精简后，砍掉 expected）：
```
tool_id: str
actual: dict | None           # 实际输出
evidence: str                 # 执行依据/来源说明
status: passed | diverged | inconclusive
```

对照逻辑从"expected vs actual"改为"actual 之间的交叉对照 + actual 和 trace 的对照 + LLM 语义推理"。

### 三、通用层职责（impl/core/）

只做三件事，不碰项目结构：

1. **ToolRegistry**（tool_registry.py）：统一注册表，管理 tool 目录。LLM 拿到的是 `[{tool_id, description, applicable_scenario, parameters}]`，按需调用。全局注册，不绑定阶段。

2. **ToolOrchestrator**（tool_orchestrator.py）：接收 LLM 的 tool 调用请求（tool_id + params），执行 execute_fn，返回 ToolResult。编排层只管调度，不管执行细节。

3. **agno 桥接**：把 VerifiableTool 转成 agno Function 喂给 agent。`parameters` 直接复用 agno/OpenAI function calling 格式，不做格式转换。

不做拆解器、不做重放器、不做执行内核。本地/mock/远程的执行方式由项目 execute_fn 自己决定。

### 四、项目层职责（impl/projects/<project>/adapter.py）

新增 `get_verifiable_tools() -> List[VerifiableTool]`。项目挑选关键函数做成四类可执行 tool：

1. **链路关键函数定位**：给 case，返回这条 live 经过哪些关键函数（签名 + 调用顺序，不返回整份源码）。
2. **局部函数可执行验证**：给函数 + 输入，真跑出 actual，对照 trace actual 或另一 tool 的 actual。
3. **数据流追溯**：字段级别——某字段被哪个函数读/改、最终在哪做决策。
4. **配置规则生效验证**：给 case 输入，跑出触发了哪条规则、actual 结果是什么。

### 五、对照方式（无 expected 的替代）

- **actual 交叉对照**：同一 case 的输入，tool A 的 actual 和 tool B 的 actual 比，一致则环节无分歧，不一致则分歧在 AB 之间。
- **actual vs trace**：tool 重跑的 actual 和 trace 记录的 actual 比，一致则行为稳定可排除，不一致则环境漂移或非确定性。
- **LLM 语义推理**：LLM 拿到 actual 后根据语义判断合理性，不需要二值对错。

### 六、废弃与收敛

- `runtime_tools.py`：整体废弃，能力并入项目 adapter 的四类 tool。
- `protocol.py`：砍掉 `_to_agno_function` 双轨（raise RuntimeError 那条），保留 agno 桥接。
- `field_retrieval.py` / `source_retrieval.py`：保留但降级为辅助 tool，不作为归因主力。

### 七、前端工作台（协议化、项目无关）

参考 context.html 思路，纯协议驱动，不读项目结构。只消费通用层运行时标准化数据：
- 已注册的 VerifiableTool 列表（从 ToolRegistry 读）
- 已跑过的 ToolResult 历史（从 orchestrator 读）
- trace 节点（通用层产出的标准数据）

不做"从项目里发现新资源"（那是项目相关的，工作台不碰）。scope 收窄到：基于已注册 tool 做试跑调试、看 ToolResult 对照、编排验证流程。

### 八、推进顺序

1. 定 VerifiableTool + ToolResult schema（精简版）
2. 实现 ToolRegistry + ToolOrchestrator + agno 桥接（通用层三件事）
3. 在 client_search 手工挑 2-3 个关键函数做成可执行 tool，跑通 judge/attr 调用闭环
4. 砍掉 runtime_tools.py，收敛 protocol.py 双轨
5. 扩展到其他项目，补充各类可执行 tool
6. 前端工作台（先做试跑调试，后做编排）

### 九、和之前方案的本质区别

- 砍掉：通用拆解器、LiveSegment、重放器、执行内核、环境构建、expected 字段、output_schema。
- 保留：可执行验证能力，范围收窄到项目手工挑选关键函数。
- tool 从"信息搬运"升级到"可执行验证 + actual 多源对照"。
- tool 不绑定 attr，judge/attr 等所有阶段通用。




---------


你说得对，这四条都有问题。我重新想：

## 1. tool 的分类应该体现"可执行验证"的意义

之前那四类（链路定位/局部函数验证/数据流追溯/配置规则验证）混合了"信息查询"和"可执行验证"，而且分类维度不统一。真正体现可执行验证的，应该按"**调什么、验证什么**"来分：

- **调远程 API/服务验证**：给 case 的入参，真调业务系统的某个接口（live 接口或中间接口），拿到实际响应。这是你说的"类似获取 api"——它验证的是"这条链路在真实业务系统里跑出来是什么"。
- **调本地函数验证**：给入参，真跑业务系统的某个本地函数，拿到实际输出。验证的是"这个函数的行为"。
- **对照验证**：把两个来源的 actual 放一起比对（比如 API 调用结果 vs trace 记录、本地函数输出 vs API 输出），产出对照结论。

前两类是"可执行"（真跑），第三类是"验证"（对照）。这才是可执行验证的意义——tool 真的执行了某个东西并拿到 actual，而不是搬运静态信息。

## 2. evidence 的用处

evidence 我本来想表达"这个 actual 是怎么来的"——调用的是哪个接口/函数、传了什么参数、执行环境是什么。目的是让 LLM 知道这个 actual 的可信度和上下文。

但你说得对，**LLM 能否可靠地产出 evidence 是个问题**——如果 evidence 要 LLM 自己描述，它可能编；如果是 execute_fn 自动填充，那它本质就是执行日志，不如直接叫 `trace` 或 `exec_log`，让 LLM 自己读。

倾向：evidence 改为 execute_fn 自动产出的执行日志（调了什么、传了什么、耗时、是否报错），是机器填充的事实记录，不是 LLM 产出的判断。如果这个字段对归因没实质帮助，也可以直接砍掉，actual 本身加上 tool 的 description 就够了。

## 3. "字段级别数据流追溯"泛化不好

你说得对，"某字段被哪个函数读/改、最终在哪做决策"这个描述太具体，假设了"字段流转"这种结构，不是所有项目都有。它其实不是一类 tool，而是"信息查询"——查询某个字段/数据在链路里的使用情况。

按第 1 点的分类，这一条不该独立存在。如果项目里有这种需求，它应该是一个具体的 VerifiableTool，由项目 adapter 自己定义，而不是通用层预设这个类别。

## 4. "配置规则生效验证"动机不明

这条的问题是：它假设了"配置驱动规则执行"这种模式，但很多项目没有显式规则引擎，"配置生效"本身是个模糊概念。它的动机其实是想验证"给定输入，业务系统的决策逻辑跑出什么"，但这本质上就是"调业务系统跑一遍拿 actual"——已经被第 1 点的"调远程 API/本地函数验证"覆盖了。

所以这条应该砍掉，不作为独立类别。

## 修正后的 tool 分类

通用层不预设具体类别，只定义"可执行验证"的抽象。项目 adapter 按需构建，常见形态就两类：

- **执行类 tool**：调 API 或本地函数，拿 actual（可执行）
- **对照类 tool**：把多个 actual 放一起比对，产出对照结论（验证）

通用层不强制这套分类，tool_id + description + applicable_scenario 由项目自定义，只要 execute_fn 真能跑、能产出 actual 就算合格的 VerifiableTool。




---------



虽然可能无法拿到所有信息，但是有多少信息拿多少信息，拿最有可能有用的信息做判断，而且为了证明我是对的，我需要执行执行和验证，来作为证据，这就是可执行可验证的作用

对，你这个表述把"可执行可验证"的真正动机讲透了，比前面所有讨论都更准。

## 核心动机

**归因不是"我全知全能地判断对错"，而是"在信息不全的情况下，拿能拿到的信息做最可能正确的判断，并且用执行验证来证明这个判断"**。

这拆成三层：

1. **有多少信息拿多少**：不追求完整链路、不追求 expected 基线。业务系统能暴露多少接口、能访问多少数据，就拿多少。拿不到的部分不硬凑，承认有盲区。

2. **拿最有可能有用的信息做判断**：在能拿到的信息里，挑对归因最有价值的——关键函数的 actual、关键 API 的响应、字段在链路里的实际值。LLM 基于这些做推理，得出一个"最可能"的归因结论。这个结论是假设性的，不是确定的。

3. **执行和验证作为证据**：这是关键——光靠 LLM 推理不够，结论需要被证明。怎么证明？真去执行（调 API、跑函数），拿真实的 actual，用它来验证前面的判断对不对。actual 是事实，不是 LLM 的猜测，它能把"我认为这里有问题"变成"我执行了这里，actual 证明了这里确实有问题"。

## 这解释了为什么之前那套不行

- 重放部署方案：要求"全知"（完整链路、完整环境、完整 expected），拿不到就放弃。违背"有多少拿多少"。
- 信息搬运 tool（field_retrieval 等）：只做第 1、2 层，没有第 3 层的执行验证。LLM 的判断没有证据支撑，不可靠。
- 可执行可验证 tool：同时覆盖三层——拿能拿的信息、挑有用的、用执行验证做证据。这才是归因真正需要的。

所以 expected 被删掉是对的根本原因也在浮现：归因不是"对错二值判断"（那才需要 expected 做标准答案），而是"用执行证据支撑一个最可能的判断"。证据是 actual，不是 expected。




--------


## 可执行可验证 Tool 完整设计

### 核心理念

归因不是"全知全能地判断对错"，而是"在信息不全的情况下，拿能拿到的信息做最可能正确的判断，并用执行验证来证明这个判断"。tool 从"信息搬运"升级到"可执行可验证"——真去调业务系统跑出 actual 作为证据，不是搬运静态信息。

### 通用层（只做三件事，不碰项目结构）

**1. 数据模型（impl/core/schema.py）**

- `VerifiableTool`：`tool_id + description + applicable_scenario + parameters（对齐 agno function calling 格式）+ execute_fn`
- `ToolResult`：`tool_id + actual + evidence（执行日志，机器填充的事实记录）+ status（passed | diverged | inconclusive）`
- 砍掉 expected、output_schema。对照逻辑是 actual 之间的交叉对照 + actual 和 trace 的对照 + LLM 语义推理。

**2. ToolRegistry（tool_registry.py）**

统一注册表，管理 tool 目录。LLM 拿到 `[{tool_id, description, applicable_scenario, parameters}]`，按需调用。全局注册，不绑定特定阶段（judge/attr 等都能用）。

**3. ToolOrchestrator（tool_orchestrator.py）**

接收 LLM 的 tool 调用请求（tool_id + params），执行 execute_fn，返回 ToolResult。编排层只管调度，不管执行细节。

**4. agno 桥接**

把 VerifiableTool 的 parameters 直接作为 agno Function 的入参定义，不做格式转换。砍掉 protocol.py 的 `_to_agno_function` 双轨。

### 项目层

adapter 新增 `get_verifiable_tools() -> List[VerifiableTool]`。项目挑选关键函数/API，做成可执行 tool。通用层不预设分类，只要求 execute_fn 真能跑、能产出 actual。

常见形态两种：
- **执行类**：调 API 或本地函数，拿 actual
- **对照类**：把多个 actual 放一起比对，产出对照结论

### 前端工作台

参考 context.html，纯协议驱动，项目无关。只消费通用层运行时标准化数据：已注册的 VerifiableTool 列表、ToolResult 历史、trace 节点。做试跑调试和对照查看，不做"从项目发现新资源"。

### 废弃与收敛

- `runtime_tools.py`：整体废弃
- `field_retrieval.py` / `source_retrieval.py`：降级为辅助 tool
- `protocol.py`：砍掉 `_to_agno_function` 双轨，保留 agno 桥接

### 推进顺序

1. 定 VerifiableTool + ToolResult schema
2. 实现 ToolRegistry + ToolOrchestrator + agno 桥接
3. client_search 手工挑 2-3 个关键函数/API 做成 tool，跑通闭环
4. 废弃 runtime_tools.py，收敛 protocol.py
5. 扩展到其他项目
6. 前端工作台

### 和之前方案的本质区别

- 砍掉：通用拆解器、LiveSegment、重放器、执行内核、环境构建、expected、output_schema
- 保留：可执行验证能力，范围收窄到项目手工挑选关键函数/API
- 核心转变：从"在 verifier 里模拟业务系统"变成"让业务系统自己跑，verifier 只负责对照"





----------



## 可执行可验证 Tool 完整设计

### 核心理念

归因不是"全知全能地判断对错"，而是"在信息不全的情况下，拿能拿到的信息做最可能正确的判断，并用执行验证来证明这个判断"。tool 从"信息搬运"升级到"可执行可验证"——真去调业务系统跑出 actual 作为证据。

---

### 通用层（impl/core/ + impl/tools/）

只做协议 + 编排，不碰项目结构，不预设 tool 分类。

**1. 数据模型（impl/core/schema.py）**

```
VerifiableTool:
  tool_id: str
  description: str              # 什么时候用、做什么
  applicable_scenario: str      # 适用场景（judge/attr/通用）
  parameters: dict              # 入参定义，对齐 agno/OpenAI function calling 格式
  execute_fn: Callable          # 真正能跑的函数

ToolResult:
  tool_id: str
  actual: dict | None           # 实际输出
  evidence: str                 # 执行日志，机器填充的事实记录
  status: passed | diverged | inconclusive
```

砍掉 expected、output_schema。对照逻辑是 actual 之间的交叉对照 + actual 和 trace 的对照 + LLM 语义推理。

**2. ToolRegistry（impl/core/tool_registry.py）**

统一注册表，全局管理 tool 目录。启动时从各项目加载 tool 注册。LLM 拿到 `[{tool_id, description, applicable_scenario, parameters}]`，按需调用。不绑定特定阶段，judge/attr/check 等都能用。

**3. ToolOrchestrator（impl/core/tool_orchestrator.py）**

接收 LLM 的 tool 调用请求（tool_id + params），查找 ToolRegistry 中的 VerifiableTool，执行 execute_fn，返回 ToolResult。编排层只管调度，不管执行细节。

**4. agno 桥接（impl/tools/protocol.py）**

把 VerifiableTool 的 parameters 直接作为 agno Function 的入参定义，不做格式转换。砍掉 `_to_agno_function` 双轨，保留 agno 桥接。

**5. 通用辅助 tool（impl/tools/）**

- `field_retrieval.py`：降级为辅助 tool，不作为归因主力
- `source_retrieval.py`：降级为辅助 tool，不作为归因主力

---

### 项目层（impl/projects/<project>/）

每个项目自定义自己的个性化 tool 集合，放在 `impl/projects/<project>/tools/` 下。

**目录结构：**
```
impl/projects/client_search/
  tools/
    __init__.py
    search_api.py              # 调搜索接口拿实际结果
    intent_mapping.py          # 调 intent 映射函数拿实际意图
    ...
  adapter.py                   # 新增 get_verifiable_tools()
```

**项目 adapter 职责：**

`adapter.py` 新增 `get_verifiable_tools() -> List[VerifiableTool]`，负责：
- 决定挑哪些函数/API 做成 tool（完全由项目自己决定）
- 实现每个 tool 的 execute_fn（调本地函数、调远程 API、调中间接口，项目自定）
- 定义 tool_id、description、applicable_scenario、parameters

**不同项目 tool 完全不同：**
- `client_search/tools/`：搜索接口调用、intent 映射验证、筛选条件对比等
- `marketting-planning-intent/tools/`：规划接口调用、意图分类验证、方案生成对比等
- `QA/tools/`：QA 接口调用、评分函数验证、答案正确性对比等

通用层只验证：execute_fn 真能跑、能产出 actual、parameters 符合 agno 格式。除此之外不干涉。

---

### 前端工作台（impl/frontend/）

参考 context.html，纯协议驱动，项目无关。只消费通用层运行时标准化数据：已注册的 VerifiableTool 列表、ToolResult 历史、trace 节点。做试跑调试和对照查看，不做"从项目发现新资源"。

---

### 废弃与收敛

- `runtime_tools.py`：整体废弃，能力并入各项目 tools/ 目录
- `protocol.py`：砍掉 `_to_agno_function` 双轨，保留 agno 桥接
- `field_retrieval.py` / `source_retrieval.py`：降级为辅助 tool

---

### 推进顺序

1. 定 VerifiableTool + ToolResult schema
2. 实现 ToolRegistry + ToolOrchestrator + agno 桥接（通用层三件事）
3. client_search 在 `impl/projects/client_search/tools/` 下手工做 2-3 个 tool，跑通闭环
4. 废弃 runtime_tools.py，收敛 protocol.py
5. 扩展到其他项目（每个项目在 tools/ 下定义自己的 tool 集合）
6. 前端工作台

---

### 和之前方案的本质区别

- 砍掉：通用拆解器、LiveSegment、重放器、执行内核、环境构建、expected、output_schema、通用层预设的 tool 分类
- 保留：可执行验证能力，**每个项目在 tools/ 下自定义自己的 tool 集合**
- 核心转变：通用层只管"协议 + 编排"，项目层完全自主决定"做哪些 tool、怎么实现"；从"在 verifier 里模拟业务系统"变成"让业务系统自己跑，verifier 只负责对照"



-------


## 刚刚讨论澄清的东西

**1. 闭包/工厂闭包模式不是协议层的事**
- 之前我把"trace/spec 怎么传给 tool"当成协议层要讨论的设计决策，这是错的
- 真相：tool 的入参完全由它自己的 `parameters` 定义决定，LLM 调用时只按 parameters 传参
- "tool 内部怎么拿到 trace/spec"是 tool 作者实现时的内部细节（可以闭包持有，可以不用，可以只用其中一个小字段），不是 LLM 调用层要操心的，也不是协议要规定的

**2. expected 字段删掉**
- 大多数情况下拿不到 expected（业务系统 trace 不记期望值、规则推导覆盖不全、人工标注不可持续）
- 归因不是"对错二值判断"，而是"用执行证据(actual)支撑最可能的判断"
- 对照逻辑改为：actual 之间的交叉对照 + actual 和 trace 的对照 + LLM 语义推理
- ToolResult 精简为 `tool_id + actual + evidence(执行日志) + status`

**3. tool 不绑定 attr**
- VerifiableTool 是通用能力，judge/attr/check 等所有阶段都能用，ToolRegistry 全局注册不绑定阶段

**4. input_schema/output_schema 精简**
- output_schema 砍掉（function calling 协议不需要返回结构定义）
- input_schema 保留但改名为 `parameters`，直接对齐 agno/OpenAI function calling 格式，不自己发明

**5. tool 分类不预设**
- 通用层不预设"链路定位/数据流追溯/配置规则验证"这种分类，这些维度不统一且泛化差
- 常见形态就两类：执行类（调 API/函数拿 actual）、对照类（多个 actual 比对）
- 具体做哪些 tool 由项目自己决定

**6. 项目个性化 tool**
- 每个项目在 `impl/projects/<project>/tools/` 下自定义自己的 tool 集合
- adapter 新增 `get_verifiable_tools()` 返回该项目的 tool 列表
- 通用层只验证 execute_fn 真能跑、能产出 actual、parameters 符合格式

**7. 可执行可验证的真正动机**
- 归因是"信息不全时拿能拿到的信息做最可能正确的判断，并用执行验证来证明"
- 不是"在 verifier 里模拟业务系统"(重放部署方案不行)，而是"让业务系统自己跑，verifier 只负责对照"
- 有多少信息拿多少，不追求完整链路/expected 基线

**8. 前端工作台**
- 参考 context.html，纯协议驱动、项目无关
- 只消费通用层运行时标准化数据（已注册 tool 列表、ToolResult 历史、trace 节点）
- 做试跑调试和对照查看，不做"从项目发现新资源"

**9. 最终的 VerifiableTool schema**
```
tool_id: str
description: str
applicable_scenario: str
parameters: dict       # 对齐 agno function calling 格式
execute_fn: Callable
```

**核心一句话**：通用层只管"协议 + 编排"，tool 的入参由 parameters 定义（LLM 按 parameters 传），tool 内部怎么拿环境数据是实现细节，每个项目在 tools/ 下自定义自己的 tool 集合，核心理念是用执行验证拿 actual 作证据支撑归因判断。




-------



tool.html