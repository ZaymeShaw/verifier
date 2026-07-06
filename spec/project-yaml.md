
❯ 我不建议加adapter，实际上这个引用的逻辑是固定的，路径也固定，没必要加，你应该 
  配置一些非固定的东西。回到上一版的逻辑，把一些不必要的去掉                    

⏺ 对，adapter 不应该放进模板公共配置里。
  如果约定固定路径：

  impl/projects/<project_id>/adapter.py

  那它就是框架约定，不是项目配置。配置里再写：

  adapter: adapter.py

  反而是重复信息，也增加用户心智负担。

  所以公共模板应该只放非固定、需要项目自己提供的东西。

  ---
  回到上一版，但去掉不必要字段

  你的目标是：

  公共层：
  - 原项目代码位置
  - 项目主调用接口
  - 项目启动脚本

  额外层：
  - 项目特有配置

  那我建议模板就变成：

  project_id: example
  name: 示例项目
  description: 简短说明这个项目测什么

  common:
    source:
      repo:

    api:
      base_url:
      endpoint:
      method: POST
      timeout: 60

    start:
      command:

  extra: {}

  就这些。

  ---
  为什么去掉 adapter

  因为 adapter 路径固定：

  impl/projects/<project_id>/adapter.py

  由 loader 按约定加载即可，不需要用户填。

  如果以后真的有特殊 adapter，再说，不作为模板默认项。

  ---
  为什么去掉 capabilities

  capabilities 看起来通用，但其实容易变成“用户不知道该填啥”的字段。

  而且能力很多时候可以从 adapter / 项目文件推断或默认：

  live_run
  judge
  attribute
  cluster
  check

  如果某项目特殊，比如 QA 不真实调用、SSE、多轮，可以放到：

  extra:
    capabilities:
      - scenario
      - multi_turn

  或者：

  extra:
    mode: uploaded_output

  但不进公共模板。

  ---
  为什么去掉 documents

  documents 虽然当前代码用得多，但它更像 verifier 框架的固定约定：

  application.md
  mock.md
  evaluation.md
  judge_boundary.md
  attribution.md
  checklist.md

  如果这些文件名都固定，那也不该每个项目都填一遍。

  建议以后默认按固定文件名读取：

  impl/projects/<project_id>/application.md
  impl/projects/<project_id>/mock.md
  impl/projects/<project_id>/evaluation.md
  impl/projects/<project_id>/judge_boundary.md
  impl/projects/<project_id>/attribution.md
  impl/projects/<project_id>/checklist.md

  只有非标准文档、外部 source 文档才放 extra：

  extra:
    source_docs:
      readme: ../../../projects/client_search/readme.md
      config: ../../../projects/client_search/config.md
      prompt: ../../../projects/client_search/prompt.md

  ---
  最小公共模板

  我现在建议就是：

  project_id: example
  name: 示例项目
  description: 简短说明这个项目测什么

  common:
    source:
      repo:

    api:
      base_url:
      endpoint:
      method: POST
      timeout: 60

    start:
      command:

  extra: {}

  ---
  字段解释

  project_id

  项目 ID，和目录名一致：

  project_id: client_search

  ---
  name

  展示名：

  name: 客户搜索评估示例

  ---
  description

  描述这个项目测什么：

  description: 评估客户搜索 query parse 输出是否符合业务语义。

  ---
  common.source.repo

  原项目代码位置：

  common:
    source:
      repo: /Users/xiaozijian/WorkSpace/package/marketing-planning

  如果没有原项目：

  common:
    source:
      repo:

  ---
  common.api

  项目主调用接口：

  common:
    api:
      base_url: http://127.0.0.1:9006
      endpoint: /api/v1/marketing-planning/stream
      method: POST
      timeout: 120

  如果没有主调用接口，比如纯上传输出评估：

  common:
    api:
      base_url:
      endpoint:
      method:
      timeout:

  ---
  common.start.command

  项目启动脚本：

  common:
    start:
      command: ./start.sh

  如果需要用户自己启动，就空着：

  common:
    start:
      command:

  ---
  extra

  所有项目特有配置。

  比如 client_search：

  extra:
    source_docs:
      readme: ../../../projects/client_search/readme.md
      config: ../../../projects/client_search/config.md
      prompt: ../../../projects/client_search/prompt.md

    downstream_search:
      base_url: http://localhost:8081
      endpoint: /api/v1/search/customer

    semantic_equivalence_rules:
      ...

  比如 marketting-planning：

  extra:
    protocol: sse
    scenarios:
      - clarification
      - execution_planning
    event_aliases:
      done:
        - done
        - complete
        - completed

  比如 QA：

  extra:
    mode: uploaded_output
    scenarios:
      - qa_gold_answer
      - qa_context_faithfulness
    score_dimensions:
      - correctness
      - completeness
      - faithfulness

  ---
  和当前代码的关系

  当前代码还依赖：

  adapter
  capabilities
  documents
  frontend_extensions
  application
  api

  所以如果真要实施，有两步：

  第一步：确定新模板

  新增：

  impl/projects/project.template.yaml

  内容就是上面的最小版。

  第二步：兼容 loader

  让 loader 支持新字段，同时兼容旧字段：

  common.api -> 旧 spec.api
  common.source.repo -> 旧 application.external_repo
  common.start.command -> 旧 application.start_command
  extra -> 新 project-specific config

  同时旧字段暂时不删。

  也就是说，现有项目还能继续跑；新项目按最小模板写。

  ---
  我现在的推荐结论

  模板不要写：

  adapter
  capabilities
  documents
  frontend_extensions

  因为：

  - adapter：路径固定，框架约定即可
  - documents：核心文档也应固定文件名
  - capabilities：容易让用户填不清楚，项目特殊能力放 extra
  - frontend_extensions：名字不准确，项目特有东西统一放 extra

  最终公共模板：

  project_id: example
  name: 示例项目
  description: 简短说明这个项目测什么

  common:
    source:
      repo:

    api:
      base_url:
      endpoint:
      method: POST
      timeout: 60

    start:
      command:

  extra: {}

  这个才符合“只配置非固定的东西”。

✻ Worked for 59s

※ recap: 目标是统一项目配置：全局运行配置已改，当前在收敛 project.yaml 模板。下一步应按最小公共层设计：只保留 project_id/name/description、common.source/api/start 和 extra。




----------


这个建议更合理，我赞同。

可以把职责按目录分开：

```text
projects/<project>/project.yaml          # 人写，需求侧/业务侧权威配置
impl/projects/<project>/project.yaml     # AI/实现侧补充配置，服务 verifier 运行
```

这样比 `project.yaml` + `project.ai.yaml` 放在同一目录更清楚，因为它正好对应现有仓库里的两层结构：

- `projects/<project>/`：偏需求、业务资料、人工维护
- `impl/projects/<project>/`：偏实现、adapter、评测执行、verifier 运行时

## 推荐职责划分

### 1. `projects/<project>/project.yaml`：人写，权威配置

只放人确认过的核心信息：

```yaml
project_id: client_search
name: 客户搜索
description: 评估客户搜索 query parse 输出是否符合业务语义

common:
  source:
    repo: /path/to/source/project

  api:
    base_url: http://localhost:8000
    endpoint: /api/v1/query
    method: POST
    timeout: 60

  start:
    command:
```

特点：

- 人写
- 简短
- 权威
- 不放 AI 猜测
- 作为项目真实意图/接入信息的 source of truth

### 2. `impl/projects/<project>/project.yaml`：AI/实现侧配置

放 verifier 实现需要的补充信息：

```yaml
project_id: client_search

extra:
  source_docs:
    readme: ../../../projects/client_search/readme.md
    config: ../../../projects/client_search/config.md

  downstream_search:
    base_url: http://localhost:8081
    endpoint: /api/v1/search/customer

  semantic_equivalence_rules:
    ...
```

特点：

- 可由 AI 维护
- 可包含探索补充
- 可包含 verifier 运行、judge、attribute、frontend、check 所需配置
- 不应该反过来覆盖人工权威配置，除非显式允许

## 加载优先级建议

我建议语义上是：

```text
projects/<project>/project.yaml = 权威基础配置
impl/projects/<project>/project.yaml = 实现补充配置
```

加载时可以合并：

```text
最终 ProjectSpec = 人写 project.yaml + impl project.yaml 补充
```

但冲突时应该：

```text
人写配置优先
```

例如：

```text
projects/client_search/project.yaml common.api.base_url
优先于
impl/projects/client_search/project.yaml common.api.base_url
```

AI 写的 impl 配置可以补充：

- `extra`
- source docs
- frontend hints
- semantic rules
- check rules
- adapter 特定参数

但不应该悄悄改掉人写的：

- 项目 ID
- 项目名
- 主接口
- 原项目代码路径
- 启动命令

## 对现有项目的兼容

现阶段应该继续兼容：

```text
impl/projects/<project>/project.yaml
```

因为现在运行时已经依赖它。

后续迁移可以变成：

1. 新增 `projects/<project>/project.yaml` 作为人工权威配置。
2. loader 优先读取人工配置。
3. 再读取 `impl/projects/<project>/project.yaml` 作为补充。
4. 冲突时人工配置优先。
5. 老项目没有人工配置时，继续只读 impl 配置。

## 我建议的最终约定

```text
projects/<project>/project.yaml
```

放“人确定的项目事实”：

- 原项目代码位置
- 主调用接口
- 启动脚本
- 项目描述

```text
impl/projects/<project>/project.yaml
```

放“verifier 实现需要的补充”：

- source docs
- semantic rules
- frontend/check/judge/attribute 扩展
- AI 探索信息
- 兼容旧字段

这样能同时满足：

- 人控制权威配置
- AI 可以继续补充实现细节
- 当前代码兼容
- 未来项目结构更清晰。









----------------
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