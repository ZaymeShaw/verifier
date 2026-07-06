# 关于schema
## schema的定位
> impl/core/schema承担整个项目数据流的对接标准。schema不是摆设，他们实际上是标准
算法/前端/后端的数据流结构（输入/输出）要跟schema对齐，中间的实现你可以自己决定，但是对接的地方要跟他保持一致

比如说table.py展示表逻辑，后端实现的表结构和前端展示的summary表结构，都应该与他对齐
table.py只是一个例子，要审视整个项目的数据流结构，实现关键位置的结构对齐和统一

## 如何使用schema
> 统一使用schema的数据结构
- 所有函数的输入/输出字段，尽量直接复用schema的数据类，而不是创造新的东西
- 尽量不要用schema以外的数据结构，统一数据类型
- 功能相似的schema，请尽量进行合并，并保持字段的简洁性，存在冲突需修改/删除时向用户进行确认
>> 如果测评系统数据流需求，以当前schema无法满足
- 先考虑是否能统一改为为使用当前已有的schema，而不是创建新的schema
- 如果实在需要创建新的schema，需先向用户进行确认
>> 非schema的其他参数，通常作为extra param存在

## 需要schema标准化的关键位置
judge agent
attribute agent
live（实时业务系统请求）
mock agent
trace
view
前端表格view


## schema样例的加载

现在虽然写了schema，但是我对于schema里面装的是什么还是没有一个很直观的概念，能不能设法可视化给我看，比如让我看每个schema的一个case，这个有没有可能脚本化？
我觉得schema这个东西除了可视化外，最直观的一个作用是可以用来快速构建mock数据，用来测某些函数或功能，得能支持这个东西，作为一个输入 
我希望的测试方式：比如说ExpectationAttribution这个schema，我希望我想用的时候，能直接load_fixture("impl.core.schema.attribute.ExpectationAttribution"),就加载出一个样例出来，并且当我想改里面的某些值定向测试时，我也能通过传参的方式直接修改 
我觉得这个功能你可以在impl/core/schema/fixture/fixture.py里面实现
同时要注意不同业务场景可能适合不同的mock数据，因此建议core 提供通用场景，project 可以注册/覆盖自己的业务场景：
比如：
  load_fixture("impl.core.schema.attribute.ExpectationAttribution")
  load_fixture("impl.core.schema.attribute.ExpectationAttribution", scenario="implementation_bug")
  load_fixture("impl.core.schema.attribute.ExpectationAttribution", scenario="client_search.missing_asset_level")
f


# 关于config
> config整体的对齐，项目对齐config配置，从统一位置获取env信息启动
- 项目启动python env对齐
- 相关llm 调用key和base_url
- 项目标准化启动端口，端到端uat测试启动端口（这两端口可以设置为不同）

考虑project.yaml的问题，project.yaml的话，各个项目应该保持相对一致，最好有个公用的模版
+ 配置公共层
    - 配置原项目代码位置
    - 项目主调用接口
    - 项目启动脚本
+ 配置额外层
    - 项目特有配置


## 关于project.yaml的特化

❯ 其实我现在觉得project.yaml有一个额外的用途是可以给用户补充各种项目特化信息，比如把md文件配置在这里，然后到时候llm根据需求自己去 
  查询解析拆解项目内容啥的。然后impl里的project.yaml则是根据coding base一点  


对，这个判断很合理，而且比“一个 project.yaml 统一所有东西”更清晰：**把 project.yaml 分成“用户侧项目知识入口”和“impl 侧运行/实现配置”两层**。

建议这样理解：

## 1. 用户侧 `projects/<project>/project.yaml`

它的职责不是直接驱动 verifier runtime，而是作为**项目知识索引 / 需求材料入口**。

适合放：

```yaml
project_id: client_search
name: 客户搜索
description: 这个项目业务上要解决什么

common:
  source:
    repo: /path/to/original/project
  api:
    base_url: http://localhost:8000
    endpoint: /api/xxx
    method: POST
  start:
    command: ./start.sh

materials:
  demand: demand.md
  readme: readme.md
  start: start.md
  config: config.md
  prompt: prompt.md
  judge_boundary: judge_boundary-template.md
  field_definitions: /path/to/field_definitions.yaml

notes:
  - 这里可以写用户补充的项目特化信息
```

作用是：

- 告诉 LLM：这个项目有哪些资料可以查。
- 告诉 LLM：原项目代码在哪。
- 告诉 LLM：如果要理解业务、拆需求、分析边界，该从哪些 md/yaml/source 入手。
- 这些内容偏“用户确认的项目事实”。

它不应该承载太多 verifier 内部实现字段。

---

## 2. 实现侧 `impl/projects/<project>/project.yaml`

它的职责是**verifier 当前实现怎么跑这个项目**。

适合放：

```yaml
project_id: client_search
name: 客户搜索评估实现

common:
  api:
    base_url: http://localhost:8000
    endpoint: /api/v1/client_search_query_parse_no_encipher
    method: POST
    timeout: 60

extra:
  downstream_search:
    base_url: http://localhost:8081
    endpoint: /api/v1/search/customer
  semantic_equivalence_rules: ...
  frontend_extensions: ...
  check_rules: ...
```

作用是：

- verifier runtime 读取它。
- adapter / judge / attribute / check 使用它。
- 这里可以根据 codebase、实际适配器实现、测试结果不断演化。
- 这些内容偏“实现侧配置”和“AI/开发维护配置”。

---

## 3. 两层的关系

可以这么定：

```text
projects/<project>/project.yaml
  = 用户侧项目知识索引，偏需求、资料、原项目事实

impl/projects/<project>/project.yaml
  = verifier 实现侧配置，偏运行、适配、judge/check/frontend 规则
```

用户侧是“源事实”，impl 侧是“实现落地”。

LLM 工作流可以是：

1. 先读用户侧 `projects/<project>/project.yaml`
2. 根据里面的 `materials` 去读 md、原项目代码、配置、prompt
3. 理解项目需求和边界
4. 再看 `impl/projects/<project>/project.yaml`
5. 判断当前 verifier 适配是否对齐需求
6. 必要时更新 impl 侧配置或 adapter

这样就不会把“业务资料索引”和“runtime 实现配置”混在一个文件里。

---

## 4. 这个设计解决的坑

它能避免：

- 用户侧配置被 AI 实现细节污染
- impl 侧配置被当成业务事实
- 一个 YAML 里既放需求文档，又放 judge 规则，又放 frontend 字段，越来越乱
- LLM 不知道该从哪里找业务资料
- 后续新增项目时，不知道哪些字段是用户必须填、哪些是实现过程生成的

---

## 5. 最小建议

用户侧模板可以是：

```yaml
project_id:
name:
description:

common:
  source:
    repo:
  api:
    base_url:
    endpoint:
    method:
  start:
    command:

materials: {}

notes: []
```

impl 侧模板可以继续是：

```yaml
project_id:
name:
description:

common:
  source:
    repo:
  api:
    base_url:
    endpoint:
    method:
    timeout:
  start:
    command:

extra: {}
```

区别是：

- 用户侧多 `materials` / `notes`
- impl 侧多 `extra`

这样就很清楚：

```text
materials = 给 LLM 查项目资料
extra = 给 verifier 实现跑项目
```