# Verifier 配置与项目知识路由协议

本文定义 verifier 产品公共配置、项目知识路由和项目运行配置的长期边界，并记录当前仓库迁移到该协议所需的一次性改造任务。hooks、Skill、OpenSpec 等独立工具的内部配置不属于 verifier 产品配置，但其与 verifier 正式运行的连接点仍受本文约束。

本文中的 `<project>` 表示项目目录名和规范化后的 `project_id`。除明确标注为迁移兼容的行为外，第一章中的要求均为长期不变量；第二章只描述当前差异和完成后可删除的一次性任务，不得反向改变第一章协议。

# 第一章：Spec 标准

## 1. 目标

配置协议必须同时满足以下目标：

1. verifier 公共运行参数只有一个代码入口；
2. harness AI 理解业务项目时只有一个知识入口；
3. verifier 运行某个业务项目时只有一个项目配置入口；
4. 人类能够审核和编辑正式项目配置，AI 不得在后续接入中静默覆盖人工决策；
5. 配置可以迁移到不同机器、仓库路径和部署环境，不依赖开发者个人绝对路径；
6. 秘密不进入仓库配置、项目文档、日志或生成产物；
7. 模板、schema、加载器和门禁共同形成可执行标准，而不是只依赖文字约定；
8. 独立工具可以自治，但不得让工具配置成为 verifier 产品运行的旁路。

## 2. 三层标准与环境值注入

在 verifier 产品配置范围内，长期只承认以下三类仓库内入口，以及一类仓库外值注入：

| 层 | 唯一路径 | 权威范围 | 主要消费者 | 是否被 verifier 运行时读取 |
|---|---|---|---|---|
| 公共运行配置 | `impl/config.yaml` | verifier 跨项目、非敏感运行参数 | core/server/CLI 统一配置加载器 | 是 |
| 人类项目知识路由 | `projects/<project>/project.yaml` | 业务知识的位置、用途和接入意图 | evals / harness AI | 否 |
| 业务项目运行配置 | `impl/projects/<project>/project.yaml` | verifier 如何运行和评估该项目 | 统一项目配置加载器 | 是 |
| 环境值注入 | 本地根目录 `.env`、进程环境或 Secret Manager | 已登记环境变量的实际值 | 统一配置/知识路由加载器 | 是，但不成为配置事实源 |

`impl/projects/project.template.yaml` 是业务项目运行配置的公共构建模板。模板不是第四个配置层，不参与运行时优先级，也不是任何项目的事实源。

### 2.1 配置项判定

本文所称“配置项”是指：不修改协议、数据结构或算法实现，仅改变 verifier 产品运行、业务项目行为、策略、资源选择或环境适配结果的值。

配置项按作用域唯一归属：

```text
跨项目的 verifier 产品配置
  -> impl/config.yaml

项目专属的 verifier 运行配置
  -> impl/projects/<project>/project.yaml

AI 理解项目所需的知识入口
  -> projects/<project>/project.yaml
```

协议不变量、算法实现、测试 fixture、case、Trace、manifest、report 和其他运行产物不是配置项。判断一个代码常量是否属于配置时，以“运维人员、项目接入者或业务审核者是否可能在不改变算法语义的情况下调整它”为准；若可以调整，它就是配置，不能仅因写成 `DEFAULT_*` 而留在代码中。

### 2.2 独立工具自治

hooks、Skill、OpenSpec 和其他开发工具可以维护自己的配置。工具配置不因物理上位于 `impl/projects/<project>/` 下就自动成为项目运行配置；应根据实际消费者和生效边界判断。

一个配置只有同时满足以下条件，才可认定为独立工具配置：

1. 仅在显式调用所属工具时加载；
2. verifier 正式运行时不加载、不解析；
3. 工具未运行时，live/mock/judge/attribute/pipeline 行为不变；
4. 不承载 verifier 公共运行参数或业务项目正式运行参数；
5. 工具产生的结果若要进入正式运行，必须通过 `impl/config.yaml` 或 `impl/projects/<project>/project.yaml` 中明确登记的连接点。

例如 `draft_config.yaml` 中的 objective、material、mock_source、review、max_iterations 和 report_path 属于 Draft Skill 的任务配置，可以由 Draft Skill 自治；正式启用哪个 draft role、加载哪些 role assets 以及 promotion 后的生产行为，仍必须以 `impl/projects/<project>/project.yaml` 为唯一权威。项目目录中的 DraftConfig 不得被项目运行时 loader 自动加载。

独立工具若消费环境变量，必须在自己的配置 schema 中登记，并遵守与 verifier 相同的名称、类型、必填和秘密标记要求。工具可以复用公共环境值 bootstrap，但 verifier 产品 loader 不得读取工具专属登记，工具 loader 也不得把工具变量注入 `RuntimeConfig` 或 `ProjectSpec`。

## 3. 公共运行配置

### 3.1 职责

`impl/config.yaml` 只保存跨项目共享的、非敏感的 verifier 运行参数，例如：

- verifier server 和 UAT 的默认 host/port；
- 默认 LLM provider、model、base URL 和秘密变量名；
- Python 启动策略；
- 公共并发、超时、存储和可观测性策略；
- 其他不依赖具体业务项目的部署默认值。

具体项目的 API、业务规则、角色资产和业务文档映射不得进入公共配置。

### 3.2 唯一加载入口

公共配置必须由 `impl/core/config.py` 或其后继的统一配置模块加载。其他模块必须通过类型化配置对象获取值，不得：

- 再次解析 `impl/config.yaml`；
- 直接解析 Key、模型、URL、host、port 等环境变量；
- 复制公共默认值；
- 从 `env.md` 或其他 Markdown 读取运行参数或秘密；
- 在业务代码中保留能够改变部署行为的硬编码 fallback。

依赖库若要求在 import 前设置兼容环境变量，初始化动作仍由统一配置 bootstrap 完成，不能成为第二套配置解析逻辑。

### 3.3 优先级

同一公共运行参数的长期优先级固定为：

```text
明确的 CLI 临时参数
  > 部署平台或当前进程环境
  > 本地根目录 .env
  > impl/config.yaml
  > 代码内协议安全默认值
```

CLI 和环境变量只是已登记配置字段的临时值注入通道，不是新的配置标准。哪些字段允许覆盖、变量名、类型、是否必填和是否为秘密，必须预先声明在其所属的 `impl/config.yaml` 或 `impl/projects/<project>/project.yaml` 中。代码不得临时发明未登记环境变量。

代码内默认值只能保证配置缺失时安全失败或提供与环境无关的最小行为，不能复制完整部署配置。每个字段只能有一个环境变量命名规范，不得长期保留多个含义相同的别名；别名只允许在有删除期限的迁移期存在。

## 4. 人类项目知识路由

### 4.1 定位

`projects/<project>/project.yaml` 是 evals 和 harness AI 理解业务项目的唯一知识入口。这里的“唯一”表示：

- AI 必须从该文件开始发现业务知识；
- 所有允许 AI 使用的项目知识必须从该文件直接或间接可达；
- AI 不得绕过该入口，在 verifier 仓库或开发者机器上盲搜未声明资料；
- 被路由文件和源码才是知识正文，路由 YAML 不复制大段正文。

知识路由不是 verifier 运行配置，生产运行时不得读取或依赖它。

### 4.2 应表达的内容

知识路由至少包含：

- `project_id`、名称和业务描述；
- live 系统启动、API 和环境要求的文档入口；
- 需求、场景、judge boundary、attribution、checklist 等资料入口；
- 业务源码或外部仓库入口；
- `ready` 数据流声明；
- 单轮或多轮交互声明；
- 每个资料入口的用途说明，使 AI 能按需读取而不是全量加载。

一个知识路由示意如下：

```yaml
project_id: client_search
name: 客户搜索
description: 代理人通过自然语言搜索客户

live:
  startup_doc: start.md
  api_doc: api.md
  env_doc: env.md

docs:
  - path: demand.md
    description: 业务目标、范围和核心场景
  - path: judge_boundary.md
    description: 可评价边界和外部依赖责任

source:
  repo: ${CLIENT_SEARCH_REPO}

environment:
  variables:
    CLIENT_SEARCH_REPO:
      bind: source.repo
      type: path
      required: true
      secret: false
      description: client_search 业务源码位置，仅供 evals/harness AI 读取

ready: []
interaction: single_turn
```

### 4.3 路由约束

- 仓库内资料使用相对于知识路由目录的相对路径；
- 外部仓库使用显式环境变量、workspace mount 或其他可移植引用，不写开发者个人绝对路径；
- 知识路由使用 `${VAR}` 时，必须在同一文件的 `environment.variables` 中登记变量名、绑定路径、类型、必填性、秘密标记和用途；该登记只供 evals/harness AI 使用，不会自动成为 verifier 运行配置；
- `env_doc` 只能说明需要哪些变量及其用途，不能保存真实秘密；
- 路由目标缺失、越界或不可读时，evals 必须报告明确错误；
- `project_id` 必须与目录名一致；
- 知识路由 schema 必须拒绝未知字段和错误类型。

## 5. 业务项目运行配置

### 5.1 定位

`impl/projects/<project>/project.yaml` 是 verifier 运行和评估该业务项目的唯一硬配置。它由 AI 在首次接入时根据人类知识路由生成，由人类审核并可继续编辑，提交后成为正式代码的一部分。

“由 AI 生成”不代表它是可以任意覆盖的临时产物。首次接入后，该文件与项目 Python 实现具有同等代码权威；任何更新必须形成可审核 diff。

### 5.2 应表达的内容

所有项目专属、可在不修改算法语义的情况下调整的 verifier 运行决策，都必须在本文件中表达。未在本文件及其正式 schema 中声明的项目可调值均视为配置旁路。内容包括：

- 规范化后的项目标识、名称、描述和 capabilities；
- `ready` 和 interaction/runtime mode；
- verifier 实际使用的 API transport 参数；
- 项目文档和角色资产映射；
- live/mock/judge/attribute 等角色的启用和 draft 选择；
- endpoint discovery；
- verifier 需要结构化消费的业务规则和 frontend extensions；
- 指向人类知识路由或外部业务源码的可移植引用；
- 用于发现知识变化的来源版本元数据；
- 项目专属环境变量的名称、目标字段、类型、必填性和秘密标记。

运行配置不得保存：

- 真实 Key、Token、密码或证书；
- 大段业务知识正文；
- mock case、回归结果、Trace 或运行日志；
- 可以从协议层动态发现的扩展点清单；
- 已由项目 Python 代码唯一表达的算法实现；
- 仅在显式调用独立 hook/Skill/开发工具时生效的工具任务配置；
- 开发者个人绝对路径。

### 5.3 生成与人工编辑语义

项目配置生命周期固定为：

1. 首次接入时，evals 从人类知识路由进入，按需读取被路由资料；
2. evals 依据 `impl/projects/project.template.yaml` 和正式 schema 生成初始运行配置；
3. 人类审核或编辑后，该配置成为项目运行时权威；
4. 后续 evals 运行必须同时读取知识路由和现有运行配置；
5. AI 只能提出配置 diff，不得因重新分析知识而静默覆盖人工字段；
6. 知识与现有运行配置冲突时必须列出冲突、依据和建议，由人类决定；
7. 只有显式接受的 diff 才能写回正式配置。

运行配置可以保存来源元数据，例如：

```yaml
metadata:
  schema_version: 1
  initialized_from: ../../../projects/client_search/project.yaml
  source_revision: "<knowledge-revision>"
```

`source_revision` 只用于过期提示和审计，不能授权自动覆盖人工配置。

### 5.4 与知识路由的关系

人类知识路由和业务运行配置可以描述同一业务对象，但不能同时成为同一运行字段的权威。例如：

- `api.md` 描述业务服务真实提供的接口；
- 运行配置声明 verifier 在当前环境实际调用的 endpoint、timeout 和 transport mode。

前者是业务知识，后者是运行决策。不得在两份 YAML 中长期维护结构完全相同且都声称为运行时权威的字段。

## 6. 公共构建模板与正式 schema

### 6.1 模板职责

`impl/projects/project.template.yaml` 负责：

- 展示运行配置的推荐结构；
- 提供安全、可移植的默认示例；
- 为 evals/scaffold 生成初始配置提供形状参考；
- 解释可选字段和常见组合。

模板不得被运行时加载，也不得替代 schema 校验。

### 6.2 Schema 与解析

公共配置、知识路由和项目运行配置必须分别具有正式、类型化 schema。加载器必须使用标准 YAML parser，并至少校验：

- 必填字段；
- 字段类型和枚举；
- 未知字段；
- `project_id` 与目录名一致；
- URL、HTTP method、timeout 和端口范围；
- 路径是否存在、是否越界以及是否允许外部引用；
- draft module 和 role asset 是否位于允许目录；
- schema version 是否受支持；
- 模板示例能否通过当前 schema。

不得以手写的简化 YAML parser 作为正式运行时解析器。

## 7. 路径、环境和秘密

### 7.1 可移植路径

- 仓库内文件必须优先使用相对路径；
- 解析相对路径时必须以所属配置文件目录为基准；
- 外部源码通过环境变量、workspace mount 或显式 URI 引用；
- 不得提交 `/Users/<name>/...`、`/home/<name>/...` 等个人绝对路径；
- Python 默认解释器使用可移植命令，本机特殊解释器通过环境覆盖；
- 路径解析必须阻止非预期的目录越界。

### 7.2 环境变量登记

verifier 和 evals/harness AI 只允许读取已经登记的环境变量。公共运行变量登记在 `impl/config.yaml`，项目运行变量登记在 `impl/projects/<project>/project.yaml`，仅用于解析知识路由的变量登记在 `projects/<project>/project.yaml`；独立工具变量由所属工具配置登记。登记项至少包含：

- 环境变量名；
- 绑定的配置字段路径；
- 值类型；
- 是否必填；
- 是否为秘密；
- 用途说明。

公共变量示意：

```yaml
environment:
  variables:
    DEEPSEEK_API_KEY:
      bind: llm.api_key
      type: string
      required: true
      secret: true
      description: verifier 默认 LLM API Key
```

项目变量示意：

```yaml
environment:
  variables:
    CLIENT_SEARCH_BASE_URL:
      bind: api.base_url
      type: url
      required: false
      secret: false
      description: client_search 业务服务地址
```

约束：

- 环境变量名在仓库可发现的登记域内全局唯一；
- 公共变量不得在各项目重复登记；
- 知识路由变量若在对应 impl 项目配置中再次登记，必须保持名称、类型和语义一致，并由一致性门禁校验；
- 一个环境变量不得绑定多个无关字段；
- 项目变量应使用稳定的项目命名空间；
- verifier 产品 loader 只读取公共登记和当前 impl 项目登记中的变量；
- 类型转换、必填检查和错误报告由统一 loader 完成；
- 项目代码、脚本和 checklist 不得直接调用 `os.getenv()` 解析产品配置；
- `projects/<project>/env.md` 只描述业务系统环境知识，不能代替 impl 侧的环境变量登记；evals 必须把 verifier 真正需要消费的变量转化为正式登记。

### 7.3 `.env` 本地值载体

仓库根目录 `.env` 是本地开发环境的可选值载体，不是配置事实源。长期只允许 verifier 自动加载这一份 `.env`，不得再建立项目级 `.env`、角色级 `.env` 或其他生产配置 sidecar。

加载与校验规则：

```text
部署平台或当前进程环境
  > 仓库根目录 .env
  > 所属 YAML 中的非敏感默认值
```

- `.env` 必须被 Git 忽略，不得提交；
- `.env` 可以保存本地秘密，但它是本机明文文件，不替代生产 Secret Manager；
- `.env` 中的变量必须存在于公共配置、知识路由、某个已安装项目配置或独立工具配置的登记表中，未登记项必须阻断；
- 校验 `.env` 时使用全部可发现登记表的并集；verifier 运行时只解析公共登记与当前 impl 项目登记，evals/harness AI 只解析当前知识路由登记，独立工具只解析自己的登记；
- 当前进程中与 verifier 无关的系统环境变量不报错，统一 loader 只读取已登记名称；
- `.env.example` 必须从全部可发现登记表生成，不得人工维护第二份变量定义；
- `.env.example` 只输出变量名、非敏感示例和说明，秘密值必须为空；
- resolved config、日志和错误消息必须按 `secret` 标记脱敏。

### 7.4 秘密管理

真实秘密只允许来自本地 `.env`、当前进程环境或部署平台 Secret Manager。仓库可以保存秘密变量名、类型、绑定关系和使用说明，但不得保存秘密值。

以下受版本控制的位置均不得包含真实秘密：

- `impl/config.yaml`；
- 两类 `project.yaml`；
- `.env.example`；
- Markdown 文档和 `env.md`；
- Python、Shell、测试 fixture；
- report、Trace、日志和前端响应；
- `.codex`、hook 或其他工具配置。

配置检查必须包含秘密扫描；错误消息不得打印秘密值或可识别前缀。

## 8. 运行时访问边界

长期调用关系必须保持为：

```text
impl/config.yaml
  + 已登记的进程环境或根目录 .env 值
  -> 公共配置加载器
  -> RuntimeConfig
  -> core/server/CLI

impl/projects/<project>/project.yaml
  + 该项目已登记的进程环境或根目录 .env 值
  -> 项目配置加载器
  -> ProjectSpec
  -> adapter / live / mock / judge / attribute / tools

projects/<project>/project.yaml
  -> evals / harness AI
  -> 被路由知识
  -> 初始配置或配置 diff
```

约束：

- 项目实现只接收 `ProjectSpec` 或更小的类型化配置对象，不自行打开 YAML；
- core 不读取人类知识路由；
- evals 不把知识路由直接当作运行配置；
- adapter 不新增配置加载职责；
- checklist、临时诊断脚本和测试不得形成生产配置旁路；
- hooks、OpenSpec 和开发工具可以维护满足第 2.2 节独立性条件的自身配置，但不得承载 verifier 公共运行参数或业务项目正式运行参数；
- 独立工具配置即使位于项目目录，也只能由所属工具在显式调用时加载；例如 Draft Skill 可以读取 `draft_config.yaml`，项目 loader 不得读取它；
- 独立工具与 verifier 正式运行耦合的开关、资产映射和 promotion 结果必须回到正式公共或项目配置；
- `.env` 只由统一 bootstrap 加载，项目模块和工具不得各自调用 dotenv 或再次解析该文件。

## 9. 配置门禁

仓库必须提供统一配置检查，并纳入新项目接入与回归。门禁至少包括：

1. 公共配置 schema 校验；
2. 全部人类知识路由 schema 和可达性校验；
3. 全部业务项目运行配置 schema 校验；
4. `project_id`、目录名和两侧项目对应关系校验；
5. 模板与正式 schema 一致性校验；
6. 公共、知识路由、项目和独立工具环境变量登记的名称唯一性、绑定路径、类型、必填性、秘密标记及跨层一致性校验；
7. `.env` 未登记变量、缺失必填值、错误类型和 `.env.example` 生成一致性校验；
8. 秘密、个人绝对路径和配置旁路扫描；
9. 独立工具配置不得被 verifier 正式运行路径加载；
10. 项目配置可以构造 `ProjectSpec`；
11. adapter/protocol compliance、mock-check 和最小单链验证。

配置错误必须尽早阻断，并指出文件、字段路径、实际值类型和期望约束；不得静默使用另一份配置或隐式兼容错误字段。

## 10. 长期不变量

1. `impl/config.yaml` 是公共运行配置的唯一仓库入口；
2. `projects/<project>/project.yaml` 是 harness AI 的唯一项目知识入口；
3. `impl/projects/<project>/project.yaml` 是项目运行硬配置的唯一入口；
4. `impl/projects/project.template.yaml` 只是模板，不参与运行；
5. verifier 运行时不依赖人类知识路由；
6. 人类知识路由不复制正式运行配置；
7. AI 后续更新只能提交 diff，不能静默覆盖人工配置；
8. 所有配置使用标准解析器和正式 schema；
9. verifier 只消费正式登记的环境变量，根目录 `.env` 只是本地值载体；
10. 秘密不落仓库，个人绝对路径不进入正式配置；
11. 独立工具配置可以自治，但不得成为 verifier 正式运行配置旁路；
12. 同一个配置字段只有一条解析链和一个最终权威。

# 第二章：Changes

## 1. 当前现状差异

### 1.1 公共 LLM 配置存在重复入口

当前 `impl/config.yaml` 和 `impl/core/config.py` 已建立公共 LLM 配置，但 `impl/core/llm_client.py` 仍独立维护默认 model、base URL、环境变量优先级和 `env.md` Key 读取逻辑。部分 checklist 脚本也直接读取 `env.md` 或写死 DeepSeek URL/model。

结果是同一个 Key、模型和 URL 存在多条解析链，修改公共配置不能保证所有调用生效。

### 1.2 公共配置包含本机路径

当前 `impl/config.yaml` 的 Python executable 是开发者个人 conda 绝对路径，不满足跨机器迁移要求。

### 1.3 人类知识路由尚未统一到新模板

`projects/project.template.yaml` 已使用 `live.startup_doc`、`live.api_doc`、`live.env_doc`、`docs`、`source`、`ready` 和 `interaction` 表达知识路由，但部分现有项目仍使用旧的 `common.api`、`common.start` 和 `common.ready` 结构；部分 `project_id` 与目录名也不一致。

因此 evals 目前不能依赖统一的人类知识路由协议。

### 1.4 evals 对知识事实源的描述与模板不一致

当前 evals skill 一方面把 `projects/<project>/project.yaml` 定义为唯一事实源，另一方面仍要求从其中读取 `common.api`。这与现行人类模板以 Markdown 为主的知识路由结构不一致，也没有明确区分“知识事实源”和“运行时事实源”。

### 1.5 项目运行配置存在重复和不可移植值

部分 `impl/projects/<project>/project.yaml` 同时维护 `source_project`、`application.external_repo`、绝对文档路径、endpoint discovery source root 等同源路径；部分服务 URL 在多个字段或项目代码 fallback 中重复。多个项目仍保存开发者个人绝对路径。

### 1.6 项目配置解析器不是完整 YAML 实现

当前项目加载器使用手写 `load_simple_yaml`。它只支持 YAML 子集，没有严格未知字段检查，也没有完整的类型、版本、路径和跨字段校验。公共配置和项目配置因此使用两种不同解析语义。

### 1.7 模板不是可执行标准

当前测试主要检查模板是否包含或不包含若干文本，以及现有项目能否宽松加载；尚未证明模板、类型 schema、加载器和所有实际项目严格一致。错误字段可能被忽略或通过兼容逻辑吸收。

### 1.8 生产配置旁路仍然存在

部分项目代码、diagnostic/checklist 脚本和 LLM 客户端保留 host、port、model、base URL 或环境变量的直接 fallback。它们会在迁移后绕开正式配置入口。

### 1.9 环境变量尚未形成登记协议

当前公共配置允许多个环境变量别名，部分模块直接读取 `os.getenv()`；仓库没有统一 dotenv bootstrap、环境变量类型/绑定 schema、未登记变量门禁或从登记表生成的 `.env.example`。`.gitignore` 目前忽略 `env.md`，但没有建立根目录 `.env` 的正式忽略与使用约定。

### 1.10 独立工具配置边界尚未被验证

hooks、Skill 和 OpenSpec 已各自维护配置，这是合理自治；但当前门禁尚未验证这些配置是否只被所属工具显式加载，也没有阻止生产代码把工具配置当作运行旁路。位于项目目录的 `draft_config.yaml` 也尚未在本协议中明确为 Draft Skill 任务配置，并与项目正式 `<role>_draft`/`role_assets` 配置区分。

## 2. 一次性改造原则

改造期间遵循以下原则：

- 先建立新 schema、加载器和只读检查，再迁移实际配置；
- 先让新旧配置得到同样运行结果，再删除兼容逻辑；
- 不批量覆盖现有项目的人类审核字段；
- 不在迁移中改变项目业务行为、judge 标准或 attribute 算法；
- 不把满足独立性条件的 hook/Skill/OpenSpec 配置强行合并进 verifier 产品配置；
- 每一步都保留可独立验证的门禁；
- 兼容字段和别名必须登记删除任务，不得成为永久协议。

## 3. 一次性改造任务

### C1. 建立三类正式配置 schema

- 为 `impl/config.yaml` 建立严格 `RuntimeConfig` schema；
- 为 `projects/<project>/project.yaml` 建立 `ProjectKnowledgeRoute` schema；
- 为 `impl/projects/<project>/project.yaml` 建立严格 `ProjectConfig`/`ProjectSpec` schema；
- 在公共、知识路由和项目 schema 中定义统一的环境变量登记结构；
- 明确 schema version、必填字段、枚举、未知字段策略和跨字段约束；
- 增加模板必须通过 schema 的测试。

验收：三类配置均由正式 schema 验证，错误字段不能静默通过。

### C2. 统一 YAML 解析器和错误模型

- 使用标准 YAML parser 读取三类配置；
- 删除运行路径对 `load_simple_yaml` 的依赖；
- 统一字段路径、类型、文件位置和修复建议的错误格式；
- 对重复 key、未知字段、非法类型和不支持版本 fail fast。

验收：现有项目全部通过标准解析器；针对 YAML 边界和错误字段有回归测试。

### C3. 收敛公共配置加载

- 让 LLM client、server、CLI、knowledge base 和相关调用方只消费统一公共配置对象；
- 移除 `impl/core/llm_client.py` 中重复的 model/base URL/Key 解析；
- 将 import 前兼容初始化收口到统一 bootstrap；
- 移除生产代码和 checklist 对 `env.md` 中秘密的读取；
- 让公共配置 loader 只消费公共登记表中的环境变量；
- 为环境变量保留唯一规范名，必要的旧别名只做有期限兼容；
- 将 Python 默认 executable 改为可移植命令，本机路径只允许环境覆盖。

验收：修改 `impl/config.yaml` 或规范环境变量后，所有公共调用使用同一个解析结果；仓库不存在第二套 DeepSeek Key 解析链。

### C4. 标准化全部人类项目知识路由

- 以 `projects/project.template.yaml` 和 `ProjectKnowledgeRoute` schema 迁移所有现有项目；
- 修正 `project_id` 与目录名不一致；
- 把启动、API、环境、需求和评价资料组织为明确路由；
- 将知识正文保留在 Markdown/源码中，不复制进 YAML；
- 清除个人绝对路径，改为相对路径或环境变量引用；
- 对知识路由中使用的环境变量进行显式登记；
- 验证所有路由目标存在且用途描述充分。

验收：每个 `projects/<project>/project.yaml` 都能作为 AI 唯一入口到达接入所需知识，不依赖仓库盲搜。

### C5. 标准化全部业务项目运行配置

- 以 `impl/projects/project.template.yaml` 和正式项目 schema 迁移所有现有项目；
- 统一 `common`、`api`、`application`、documents、draft 和 role assets 的规范位置；
- 合并 `source_project`、`external_repo` 和文档路径中的重复来源表达；
- 清除个人绝对路径和重复 URL；
- 增加 `metadata.schema_version`、知识路由引用和可选的 source revision；
- 将项目真正需要消费的环境变量登记到项目配置，并删除项目代码中的直接解析；
- 保证迁移前后构造出的 `ProjectSpec` 业务语义一致。

验收：每个项目运行时只依赖自己的 impl 配置，配置 diff 经人类审核，现有项目回归不退化。

### C6. 更新 evals 与 scaffold 生命周期

- 将 evals Step 0 改为读取 `ProjectKnowledgeRoute`，不再假设旧 `common.api`；
- 明确人类知识路由是知识事实源、impl 项目配置是运行时事实源；
- scaffold 除项目代码骨架外，按模板生成初始项目运行配置；
- 首次接入允许生成，后续运行必须输出 diff 并保护人工字段；
- 增加知识变化、source revision 过期和冲突报告；
- 将配置检查纳入 onboarding 门禁。

验收：全新项目能够从知识路由初始化；对已有项目重跑 evals 不会静默覆盖运行配置。

### C7. 清除配置旁路和硬编码 fallback

- 扫描 core、server、项目实现、CLI、checklist 和 scripts 中的直接 `os.getenv`、host、port、model、base URL、Key 和个人绝对路径；
- 将生产运行值接入公共或项目配置；
- 项目代码仅从注入的 `ProjectSpec` 取项目运行参数；
- 保留的协议常量、测试 fixture 和独立工具配置必须明确不属于生产配置；
- 对 hooks、Skill、OpenSpec 和项目目录内工具配置执行独立性检查，不迁移满足条件的自治配置；工具使用环境变量时检查其自身登记；
- 明确 `draft_config.yaml` 只由 Draft Skill 显式消费，项目 loader 只读取 `project.yaml` 中的 `<role>_draft` 和 `role_assets`；
- 将直接 DeepSeek 测试改为消费统一 LLM 配置，或明确移出正式回归入口。

验收：静态门禁不再发现未登记的生产配置旁路。

### C8. 标准化环境值注入

- 在统一 bootstrap 中加载仓库根目录 `.env`，且不覆盖部署平台或当前进程已提供的值；
- 将 `.env` 加入 Git ignore，并禁止项目级/角色级 dotenv 旁路；
- 让 loader 只读取正式登记的变量并执行类型、必填和秘密校验；
- `.env` 中出现未在公共、知识路由、任一已安装项目或可发现独立工具登记的变量时阻断；
- 从公共、知识路由、项目和可发现工具登记表确定性生成 `.env.example`；
- 为生产环境保留同名进程环境/Secret Manager 注入；
- 对 resolved config、日志和错误消息统一脱敏。

验收：本地 `.env` 和生产 Secret Manager 使用同一变量登记与解析链；未登记变量不能影响 verifier 行为，秘密不会进入版本控制或日志。

### C9. 建立统一 config-check 门禁

- 提供可检查单项目和全部项目的统一命令；
- 检查三类 schema、路由可达性、环境变量登记、`.env`、路径安全、秘密、绝对路径和配置旁路；
- 检查知识路由与 impl 项目的对应关系；
- 检查独立工具配置不被正式运行路径加载；
- 串联 adapter compliance、protocol compliance、mock-check 和最小 run-chain；
- 纳入 CI 和新项目接入验收。

验收：配置问题在启动业务链路之前被稳定阻断，错误可定位到具体文件和字段。

### C10. 删除迁移兼容层并更新文档

- 在所有配置迁移且调用方切换后，删除旧字段兼容、旧环境变量别名和简化 parser；
- 删除把 `env.md` 当秘密源的说明与代码；
- 删除未登记环境变量、旧 dotenv 入口和人工维护的环境变量样例；
- 更新 README、evals skill、项目模板和接入文档；
- 记录最终允许的配置位置及工具配置例外；
- 执行全量配置、协议和项目回归。

验收：第一章长期协议可以在没有第二章兼容逻辑的情况下独立成立。

## 4. 推荐迁移顺序

```text
C1 schema
  -> C2 标准解析器
  -> C3 公共配置收敛
  -> C4 人类知识路由迁移
  -> C5 项目运行配置迁移
  -> C6 evals/scaffold 更新
  -> C7 旁路清理
  -> C8 环境值注入标准化
  -> C9 config-check/CI
  -> C10 删除兼容层
```

C4 与 C5 可以按项目逐个推进，但同一项目必须先完成知识路由，再审核其运行配置。兼容层只能在全部存量项目和调用方迁移后删除。

## 5. 改造完成验收

全部一次性改造完成时，必须同时满足：

- `impl/config.yaml` 的公共参数只有一条解析链；
- 所有 DeepSeek/LLM 调用消费统一配置，不再读取 `env.md` Key；
- 公共、知识路由、项目和独立工具环境变量均先登记后消费，根目录 `.env` 被忽略且不存在项目级 dotenv 旁路；
- `.env.example` 可由登记表确定性生成，生产 Secret Manager 使用同一组登记名称；
- 所有人类项目知识路由遵循同一 schema，且资料可达；
- 所有业务项目运行配置遵循同一 schema，且不存在个人绝对路径；
- verifier 运行时不读取 `projects/<project>/project.yaml`；
- hooks、Skill、OpenSpec 等自治配置只由所属工具显式加载；`draft_config.yaml` 不被项目运行时加载；
- evals 从该知识路由开始，并只以 diff 更新已有运行配置；
- 模板、schema、加载器和实际项目相互一致；
- 配置和秘密检查进入 CI/onboarding；
- adapter、protocol、mock 和最小单链门禁通过；
- 旧字段、旧别名、简化 parser 和其他临时兼容代码已删除。
