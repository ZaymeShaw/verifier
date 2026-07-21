# Verifier 配置与项目知识路由协议

本文定义 verifier 产品公共配置、项目知识路由和项目运行配置的长期边界，并记录当前仓库迁移到该协议所需的一次性改造任务。hooks、Skill、OpenSpec 等独立工具的内部配置不属于 verifier 产品配置；它们的单次输入和产物服从各自协议，只有持久改变 verifier 后续默认行为的 promotion 才受正式配置权威约束。

本文中的 `<project>` 表示项目目录名和规范化后的 `project.id`。除明确标注为迁移兼容的行为外，第一章中的要求均为长期不变量；第二章只描述当前差异和完成后可删除的一次性任务，不得反向改变第一章协议。

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
5. 工具不得绕过正式输入协议、promotion 流程或配置权威直接改变后续默认运行行为。

工具输出按生效方式分为三类：

| 工具输出 | 进入正式运行的方式 | 是否写入配置 |
|---|---|---|
| 单次运行数据 | 通过正式 API、case、Trace 或其他类型化输入协议进入指定 run | 否 |
| 报告和诊断证据 | 作为 artifact 保存和审核，不被运行时当作配置读取 | 否 |
| 改变后续默认行为的结果 | 经人类确认的 promotion，将正式选择、开关或资产引用写回公共/项目配置 | 是 |

因此，上传 output/reference、手动归因结果、临时 case 和工具报告不需要在配置中登记；它们只需遵守所属输入或 artifact 协议。只有启用新的默认 role、切换生产 asset、改变默认策略等持久行为变更，才必须通过 `impl/config.yaml` 或 `impl/projects/<project>/project.yaml` 显式生效。

例如 `draft_config.yaml` 中的 objective、material、mock_source、review、max_iterations 和 report_path 属于 Draft Skill 的任务配置，可以由 Draft Skill 自治；正式启用哪个 draft role、加载哪些 role assets 以及 promotion 后的生产行为，仍必须以 `impl/projects/<project>/project.yaml` 为唯一权威。项目目录中的 DraftConfig 不得被项目运行时 loader 自动加载。

独立工具若消费环境变量，必须在自己的配置 schema 中登记，或显式引用公共登记，并遵守与 verifier 相同的名称、类型、必填和秘密标记要求。同名变量只能有一个定义；其他 schema 只能引用该定义，不能复制出第二份语义。工具可以复用公共环境值 bootstrap，但 verifier 产品 loader 不得读取工具专属登记，工具 loader 也不得把工具变量注入 `RuntimeConfig` 或 `ProjectSpec`。

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

知识路由采用稳定文档 ID，而不是无类型文档列表。每个文档入口必须声明 `path`、`type`、`required` 和 `description`，使 AI 能按类型和用途按需读取。一个规范路由如下：

```yaml
schema_version: 1

project:
  id: client_search
  name: 客户搜索
  description: 代理人通过自然语言搜索客户

documents:
  startup:
    path: start.md
    type: startup
    required: true
    description: 本地服务启动、健康检查和故障排查
  api:
    path: api.md
    type: api
    required: true
    description: 业务服务接口合同
  requirements:
    path: demand.md
    type: requirements
    required: true
    description: 业务目标、范围和核心场景
  judge_boundary:
    path: judge_boundary.md
    type: judge_boundary
    required: true
    description: 可评价边界和外部依赖责任

source:
  repository: ${CLIENT_SEARCH_REPO}

onboarding:
  interaction: single_turn
  ready: []

environment:
  variables:
    CLIENT_SEARCH_REPO:
      bind: source.repository
      type: path
      required: true
      secret: false
      description: client_search 业务源码位置，仅供 evals/harness AI 读取
```

### 4.3 路由约束

- 只允许 `schema_version`、`project`、`documents`、`source`、`onboarding` 和 `environment` 作为正式顶层；其中 `schema_version`、`project`、非空 `documents` 和 `onboarding` 必填，`source` 与 `environment` 按需出现；不得为了满足形状创建空 source，也不得重新引入 `common`、`live`、无类型 `docs` 列表或同义顶层字段；
- `project.id` 必须与目录名一致；文档 ID 使用稳定 `snake_case`，路径改名不应迫使消费者改文档 ID；
- 文档入口不得用“暂无”、空字符串或虚构路径占位；`required: true` 的目标必须存在且可读，可选资料不存在时应删除该入口；
- 仓库内资料使用相对于知识路由目录的相对路径；
- 外部仓库使用显式环境变量、workspace mount 或其他可移植引用，不写开发者个人绝对路径；
- 知识路由使用 `${VAR}` 时，必须在同一文件的 `environment.variables` 中登记变量名、绑定路径、类型、必填性、秘密标记和用途；该登记只供 evals/harness AI 使用，不会自动成为 verifier 运行配置；
- `environment` 类型文档只能说明需要哪些变量及其用途，不能保存真实秘密；
- 路由目标缺失、越界或不可读时，evals 必须报告明确错误；
- AI 只能读取由本路由直接或间接可达的文件和源码；新资料必须先登记再被 harness 使用；
- 知识路由 schema 必须拒绝未知字段和错误类型。

### 4.4 文档类型的最低合同

路由 YAML 严格标准化，Markdown 正文只按机器是否依赖其结构施加最低合同，不统一业务叙述风格。标准文档类型及最低内容如下：

| `type` | 最低内容 |
|---|---|
| `startup` | 前置条件、启动方式、健康检查、成功信号、常见失败 |
| `api` | endpoint、method、请求、响应、错误语义 |
| `environment` | 变量名、用途、是否必填、是否为秘密；不得包含实际值 |
| `requirements` | 业务目标、范围、非目标、核心场景 |
| `judge_boundary` | 可评价范围、不可评价范围、外部依赖责任 |
| `attribution` | 可用证据来源、证据限制和无法归因时的处理 |
| `checklist` | 检查项、通过条件和失败证据 |
| `reference` | 资料来源、用途和适用范围；用于不属于前述机器合同的补充知识 |

机器会结构化读取的 Markdown 可以使用以下 front matter，以便门禁选择对应检查器：

```markdown
---
doc_type: api
schema_version: 1
---
```

front matter 不能替代路由登记，且其 `doc_type` 必须与路由中的 `type` 一致。对 `requirements` 等以人类表达为主的文档，门禁只检查最低主题是否可识别，不强制固定标题、章节顺序或表格格式；对 `api`、`startup` 等机器依赖更强的类型，可以由各自正式 schema 追加结构要求。

## 5. 业务项目运行配置

### 5.1 定位

`impl/projects/<project>/project.yaml` 是 verifier 运行和评估该业务项目的唯一硬配置。它由 AI 在首次接入时根据人类知识路由生成，由人类审核并可继续编辑，提交后成为正式代码的一部分。

“由 AI 生成”不代表它是可以任意覆盖的临时产物。首次接入后，该文件与项目 Python 实现具有同等代码权威；任何更新必须形成可审核 diff。

### 5.2 应表达的内容

所有项目专属、可在不修改算法语义的情况下调整的 verifier 运行决策，都必须在本文件中表达。未在本文件及其正式 schema 中声明的项目可调值均视为配置旁路。内容包括：

- 项目身份、能力、源码、文档和结构化领域信息；
- 项目的运行模式、交互方式、ready contract、本地部署生命周期和服务连接；
- verifier 接入项目所需的 field provider、endpoint discovery、角色开关和角色资产；
- 只影响展示而不影响判断结论的项目展示配置；
- 项目专属环境变量的名称、目标字段、类型、必填性和秘密标记；
- 用于发现知识变化和追踪配置来源的元数据。

运行配置不得保存：

- 真实 Key、Token、密码或证书；
- 大段业务知识正文；
- mock case、回归结果、Trace 或运行日志；
- 可以从协议层动态发现的扩展点清单；
- 已由项目 Python 代码唯一表达的算法实现；
- 仅在显式调用独立 hook/Skill/开发工具时生效的工具任务配置；
- 开发者个人绝对路径。

#### 5.2.1 顶层结构

项目运行配置按“描述的对象”分层，而不是按当前消费者或测评步骤分层。长期只允许以下顶层字段：

| 顶层字段 | 唯一职责 | 不得承载 |
|---|---|---|
| `schema_version` | 声明正式项目配置 schema 版本 | 业务值或迁移状态 |
| `project` | 项目自身的身份、能力、源码、文档和项目特殊字段 | 部署地址、角色实现、展示开关 |
| `runtime` | 被测项目如何部署、交互和提供服务 | judge/attribute 实现、知识正文 |
| `verifier` | verifier 针对该项目采用的接入、归因、角色和展示行为 | 被测系统自身的部署事实、独立工具任务配置 |
| `environment` | 项目字段允许从哪些环境变量注入值 | 真实秘密值或未绑定变量 |
| `metadata` | 配置来源、知识 revision 和审计信息 | 会改变运行行为的开关 |

这是一种对象归属，而不是评测流程分层：`project` 回答“项目是什么和拥有什么”，`runtime` 回答“项目怎样运行”，`verifier` 回答“verifier 如何处理这个项目”。`environment` 和 `metadata` 只支撑前三者，不构成业务架构层。

不得新增 `evaluation`、`verification`、`integration`、`presentation`、`common`、`application`、`api`、顶层 `extra`、`frontend_extensions` 等职责重叠或以历史消费者命名的顶层容器。展示会影响 verifier 输出形态，因此归入 `verifier.presentation`；但其字段不得改变 judge、attribute、ready 或 protocol 结论。

项目特殊字段可以进入 `project`、`runtime` 或 `verifier` 所属分区的 `extra`，但必须使用第 5.2.7 节的统一注解结构并具有项目专属 schema；分区内 `extra` 不是允许任意未知字段的逃生口。

`schema_version`、`project`、`runtime`、`verifier` 和 `metadata` 必填，其中 `verifier.attribution.enabled` 必须由每个项目显式声明。`environment` 仅在项目确有环境绑定时出现；配置文件不为可选区写无意义占位值，但 resolver 必须将缺失的可选子区解析为明确的空类型对象。各区内部的其他必填字段由 `runtime.mode` 和正式 schema 决定。

`schema_version: 1` 是本协议定义的第一个正式项目配置版本。当前没有 `schema_version` 的存量 YAML 统一视为 legacy，不追认为另一个正式版本。

#### 5.2.2 最小规范结构

正式配置应只写当前项目需要的字段。以下上传输出项目展示所有项目都必须具备的最小骨架，不暗示 live service、源码、field provider 或展示配置为通用必填项：

```yaml
schema_version: 1

project:
  id: QA
  name: 问答质量测评
  description: 基于用户上传的输出与 reference 评价回答质量
  capabilities:
    - single_turn

runtime:
  mode: uploaded_output_evaluation
  interaction:
    mode: single_turn
  ready:
    - output
    - reference

verifier:
  attribution:
    enabled: false

metadata:
  initialized_from: ../../../projects/QA/project.yaml
  source_revision: null
```

规范结构遵守以下归属规则：

- 修改原因属于项目业务身份或固有资源时，进入 `project`；
- 修改原因属于部署、启动、交互或服务连接时，进入 `runtime`；
- 修改原因属于 verifier 与该项目的接入或处理方式时，进入 `verifier`；
- 修改只影响前端或报告展示时，进入 `verifier.presentation`；
- 一个服务端点统一使用 `base_url`、`endpoint`、`method`、`timeout_seconds` 结构；主服务和依赖服务复用同一类型，但不得合并成同一个实例；
- 是否由 verifier 管理本地服务启动只由 `runtime.local_deployment.enabled` 声明，不得从 host、端口或脚本是否存在进行猜测；
- `verifier.endpoint_discovery.source_roots` 必须相对于 `project.resources.source.repository`，不得再次保存仓库绝对路径；
- adapter、judge、attribute、mock、live 的固定文件名若由项目协议规定，就不作为配置字段；只有确需选择的实现、draft 和 asset 才进入 `verifier`；
- 项目专属 schema 可以约束三大功能分区的 `extra` 和 `verifier.presentation` 具体字段，但不能新增未登记顶层字段。

#### 5.2.3 服务型项目扩展

只有需要 live service 的项目才增加资源、服务和环境绑定。例如：

```yaml
project:
  resources:
    source:
      repository: ${CLIENT_SEARCH_REPO}
      paths:
        python: src/main/python
    documents:
      application: application.md
      attribution: attribution.md
      checklist: checklist.md

runtime:
  mode: existing_service_required
  local_deployment:
    enabled: true
  interaction:
    mode: single_turn
  ready: []
  services:
    primary:
      base_url: ${CLIENT_SEARCH_BASE_URL}
      endpoint: /api/v1/client_search_query_parse_no_encipher
      method: POST
      timeout_seconds: 60
      healthcheck:
        endpoint: /health
        request_timeout_seconds: 5
        interval_seconds: 2
        startup_timeout_seconds: 120

environment:
  variables:
    CLIENT_SEARCH_REPO:
      bind: project.resources.source.repository
      type: path
      required: true
      secret: false
      description: client_search 业务源码挂载位置
    CLIENT_SEARCH_BASE_URL:
      bind: runtime.services.primary.base_url
      type: url
      required: false
      secret: false
      description: client_search 业务服务地址
```

本例是对 5.2.2 最小骨架的局部扩展；完整文件仍必须包含 `schema_version`、`project.id/name/description/capabilities`、`verifier.attribution` 和 `metadata`。

#### 5.2.4 verifier 项目选项

field provider、endpoint discovery、draft role、role asset 和展示选项仅在该项目确有需要时声明：

```yaml
verifier:
  attribution:
    enabled: true
  field_provider:
    module: field_provider.py
    class: ClientSearchFieldDefinitionProvider
  endpoint_discovery:
    enabled: true
    framework: fastapi
    source_roots:
      - src/main/python
  roles:
    attribute:
      draft:
        enabled: false
        module: draft/attribute.py
  presentation:
    scenarios: []
    score_dimensions: []
```

`verifier.presentation` 只控制 verifier 前端、报告或解释层的呈现，不得改变协议输入、judge 结论、attribute 证据或 ready contract。空的可选区应省略，而不是为了和示例一致写占位数组。

#### 5.2.5 本地服务部署约定

项目是否由 verifier 负责拉起本地服务，必须显式写入项目运行配置：

```yaml
runtime:
  local_deployment:
    enabled: true
```

`enabled` 只接受 boolean，缺失等价于 `false`：

- `true`：测评开始前先检查 `runtime.services.primary.healthcheck`；健康时直接复用，不健康时执行固定启动脚本并等待健康；
- `false`：verifier 绝不执行项目启动脚本；若当前 mode 要求 live 服务，只检查服务并在不可用时报告错误；
- 没有 live 服务的 mode 不配置 `runtime.services`，也不执行 health check。

启动脚本路径由协议固定，不作为可配置字符串：

```text
impl/projects/<project>/scripts/start.sh
```

当 `runtime.local_deployment.enabled: true` 时，schema/config-check 必须要求该文件存在且可执行，并要求 `runtime.services.primary.healthcheck` 完整。启动流程固定为：

```text
获取项目级启动锁
  -> health check
  -> 已健康：直接复用
  -> 未健康：在独立进程组启动 scripts/start.sh，不等待脚本退出
  -> 按 interval_seconds 轮询 health
  -> 在 startup_timeout_seconds 内健康：开始测评
  -> 超时或脚本失败：阻断并输出脱敏诊断
```

测评结束后不自动停止服务，后续测评继续复用。并发测评必须共享进程安全的项目级启动锁，防止不同 worker 重复拉起。启动器不得通过拼接 shell command 执行脚本；只能执行已经校验的固定路径，并捕获脱敏后的标准输出和错误输出。

`start.sh` 可以保持前台运行，也可以在把服务交给 Docker Compose/system supervisor 后正常退出；启动器始终以 health check 为成功判据。脚本在服务健康前非零退出时立即失败，零退出但服务未健康时继续等待至 startup timeout。

`start.sh` 是 verifier 侧统一包装脚本，可以在内部调用业务仓库已有脚本、Docker Compose 或其他启动工具，但必须满足：

- 可重复执行且非交互；
- 不包含开发者个人绝对路径；
- 只消费已登记环境变量，不保存或打印秘密；
- 不修改 verifier 正式配置；
- 失败返回非零状态并输出可诊断信息；
- 不要求每次测评完成后执行配套 stop 脚本。

#### 5.2.6 归因开关与手动触发

归因是否默认进入项目测评主链，统一由一个 boolean 声明：

```yaml
verifier:
  attribution:
    enabled: false
```

- `true`：主链自动执行归因；
- `false`：主链跳过归因；
- QA 等 reference-only 项目和当前暂时不希望执行归因的项目使用同一个 `false`，配置和实现不再区分“不可归因”与“本次不归因”。

`enabled` 表示项目默认行为，不是永久能力判定。手动触发归因是一次性 run override：它只作用于指定 run/Trace，不修改 `project.yaml`，也不引入第三种项目配置状态。前端在当前 run 尚无成功归因结果时可以提供手动触发按钮；手动请求必须幂等，并在 Trace 中记录 `manual_override` 来源、执行状态、耗时和结果。

若手动归因缺少足够生成来源或证据，归因结果按现有协议报告证据不足；不得为了区分 QA 等项目再增加 `supported`、`available` 或其他平行配置字段。

#### 5.2.7 项目特殊字段与 `extra`

各项目应最大程度复用正式公共字段。确有项目特殊语义时，可以在所属功能分区使用 `extra`，但每个特殊字段必须使用统一注解包装：

```yaml
runtime:
  extra:
    session_reuse:
      description: 是否复用该项目的业务会话
      value_type: boolean
      schema_version: 1
      consumers:
        - verifier.live
      value: true
```

允许 `extra` 的功能分区为 `project`、`runtime` 和 `verifier`。展示特例可以位于 `verifier.presentation.extra`。`environment` 和 `metadata` 不允许 `extra`，避免绕开环境变量登记、秘密检查或审计协议。顶层 `extra` 始终禁止。

每个 `extra.<field_id>` 必须满足：

- `field_id` 使用稳定的 `snake_case`，不得与同分区正式字段同名；
- `description`、`value_type`、`schema_version`、非空 `consumers` 和 `value` 全部必填；
- `value_type` 必须来自正式类型枚举，并由项目专属 schema 校验 `value`；
- `consumers` 必须指向已登记的项目专属消费者；公共 core 若需要读取该字段，就必须先将其提升为正式公共字段；
- 需要环境注入时，仍通过 `environment.variables.<VAR>.bind` 绑定到该字段的 `value`，不得在 `extra` 内发明环境变量入口；
- 真实秘密不得进入 `value`。

同一语义的特殊字段一旦出现在两个或更多项目，或开始被公共 core 消费，必须进入标准字段评审：确认语义一致后提升到对应分区的正式 schema；语义不同则保留各自项目专属 key 和 schema。config-check 必须报告未注解、未建 schema、无消费者或疑似重复语义的 `extra`。

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
schema_version: 1

metadata:
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
- `project.id` 与目录名一致；
- 知识路由文档 ID、`path/type/required/description`、front matter 一致性和各文档类型最低合同；
- URL、HTTP method、timeout 和端口范围；
- 路径是否存在、是否越界以及是否允许外部引用；
- draft module 和 role asset 是否位于允许目录；
- `runtime.local_deployment.enabled` 与 health check、固定 `scripts/start.sh` 的条件约束；
- `verifier.attribution.enabled` 必须是显式 boolean；
- 分区 `extra` 的注解完整性、项目专属 value schema 和消费者登记；
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
      bind: runtime.services.primary.base_url
      type: url
      required: false
      secret: false
      description: client_search 业务服务地址
```

约束：

- 环境变量定义在仓库可发现的登记域内全局唯一；多个消费者需要同一个变量时必须引用同一登记，不得重复定义；
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

本地文件使用 dotenv 的受限子集。例如：

```dotenv
# 公共模型秘密
DEEPSEEK_API_KEY=your-local-secret

# client_search 本机接入值
CLIENT_SEARCH_REPO=/Users/your-name/work/client-search
CLIENT_SEARCH_BASE_URL=http://127.0.0.1:8000
```

YAML 登记定义变量的语义，`.env` 只提供本机实际值。例如 `CLIENT_SEARCH_REPO` 和 `CLIENT_SEARCH_BASE_URL` 分别绑定 `project.resources.source.repository` 与 `runtime.services.primary.base_url`。改变量名、类型、绑定路径或秘密属性必须改权威 YAML；换机器路径、Key 或本地 URL 只改 `.env` 或进程环境。

加载与校验规则：

```text
部署平台或当前进程环境
  > 仓库根目录 .env
  > 所属 YAML 中的非敏感默认值
```

- `.env` 必须被 Git 忽略，不得提交；
- 文件使用 UTF-8，每行只允许一个 `KEY=value`；变量名必须匹配 `[A-Z][A-Z0-9_]*`，`=` 两侧不得有空格；
- 不允许 `export` 前缀、重复 key、命令替换、变量插值、续行或多行值；loader 必须按字面值解析，不能启用 dotenv 的扩展求值语义；
- 只允许独占一行的 `#` 注释，不允许行尾注释；值包含空格或 `#` 时使用双引号，双引号只负责界定字面值，不触发变量插值；
- `.env` 可以保存本地秘密，但它是本机明文文件，不替代生产 Secret Manager；
- 本地 `.env` 建议使用仅当前用户可读写的权限；证书等多行秘密通过 Secret Manager 或已登记的文件路径注入，不直接写入 `.env`；
- `.env` 中的变量必须存在于公共配置、知识路由、某个已安装项目配置或独立工具配置的登记表中，未登记项必须阻断；
- 校验 `.env` 时使用全部可发现登记表的并集；verifier 运行时只解析公共登记与当前 impl 项目登记，evals/harness AI 只解析当前知识路由登记，独立工具只解析自己的登记；
- 当前进程中与 verifier 无关的系统环境变量不报错，统一 loader 只读取已登记名称；
- `.env.example` 必须从全部可发现登记表生成，不得人工维护第二份变量定义；
- `.env.example` 只输出变量名、非敏感示例和说明，秘密值必须为空，并遵守同一受限语法；
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
  -> adapter / live / mock / judge / attribute

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
- 独立工具若要持久改变后续默认开关、资产映射或生产选择，promotion 结果必须回到正式公共或项目配置；单次输入和 artifact 不适用此条；
- `.env` 只由统一 bootstrap 加载，项目模块和工具不得各自调用 dotenv 或再次解析该文件。

## 9. 配置门禁

仓库必须提供统一配置检查，并纳入新项目接入与回归。门禁至少包括：

1. 公共配置 schema 校验；
2. 全部人类知识路由 schema 和可达性校验；
3. 全部业务项目运行配置 schema 校验；
4. 人类知识路由与项目运行配置的 `project.id`、目录名和两侧项目对应关系校验；
5. 模板与正式 schema 一致性校验；
6. 公共、知识路由、项目和独立工具环境变量登记的名称唯一性、绑定路径、类型、必填性、秘密标记及跨层一致性校验；
7. `.env` 受限语法、未登记变量、重复 key、缺失必填值、错误类型、Git ignore 和 `.env.example` 生成一致性校验；
8. 秘密、个人绝对路径和配置旁路扫描；
9. 独立工具配置不得被 verifier 正式运行路径加载；
10. 项目配置可以构造 `ProjectSpec`；
11. 本地部署项目的固定启动脚本、health check、并发启动锁和超时失败验证；
12. 归因开关的自动跳过、自动执行和单次手动覆盖验证；
13. 分区 `extra` 的注解、schema、consumer 和跨项目重复语义检查；
14. adapter/protocol compliance、mock-check 和最小单链验证。

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
12. 同一个配置字段只有一条解析链和一个最终权威；
13. 本地启动只由 `runtime.local_deployment.enabled` 控制，并只执行固定项目包装脚本；
14. 每个项目显式声明 attribution boolean，手动归因只形成单次 run override，不改正式配置；
15. 项目特殊字段只能进入功能分区内已注解、已建 schema、已登记消费者的 `extra`。

## 11. 配置系统构建架构

### 11.1 核心定义：唯一解析链，而不只是唯一文件

“一个标准产出位置”不等于把所有值塞进一个 YAML。长期标准是每个配置事实只有一个权威来源，并且从来源到消费者只有一条可追踪解析链：

```text
权威 YAML
  -> schema 校验
  -> 已登记的环境值或 CLI 临时值绑定
  -> 规范化与跨字段解析
  -> 类型化配置对象
  -> 运行消费者
```

verifier 只构建以下三条链：

```text
impl/config.yaml
  -> RuntimeConfigResolver
  -> RuntimeConfig
  -> core / server / CLI / 公共模型客户端

impl/projects/<project>/project.yaml
  -> ProjectConfigResolver
  -> ProjectSpec
  -> adapter / live / mock / judge / attribute / project tools

projects/<project>/project.yaml
  -> ProjectKnowledgeRouteResolver
  -> ProjectKnowledgeRoute
  -> evals / harness AI
  -> 初始配置或待人工审核的 diff
```

schema、模板、类型定义、迁移别名表和 `.env.example` 都是协议或派生产物，不是新的配置事实源。消费者不得跳过 resolver 直接读取 YAML、环境变量、Markdown 或代码默认值。

### 11.2 构建组件

配置系统由以下组件组成：

1. **权威源**：第 2 节规定的三个 YAML 入口；
2. **正式 schema**：定义字段类型、默认值来源、未知字段策略、条件约束和版本；
3. **统一 bootstrap**：定位仓库、加载根目录 `.env`、合并当前进程环境，并在 import-sensitive 依赖加载前完成必要初始化；
4. **resolver**：按登记关系绑定覆盖值、处理迁移别名、规范化路径并执行跨字段校验；
5. **类型化输出**：`RuntimeConfig`、`ProjectSpec`、`ProjectKnowledgeRoute`，是下游唯一可消费接口；
6. **配置门禁**：验证来源、解析结果、消费者接线和迁移兼容状态；
7. **解析证据**：输出不含秘密的来源、最终字段和配置指纹，用于证明一次运行实际采用了什么配置。

上述组件可以由多个代码文件实现，但不得产生第二套字段所有权、默认值或优先级。

### 11.3 字段所有权登记

每个可调字段必须在所属 schema 中携带或关联以下元数据：

| 元数据 | 作用 |
|---|---|
| canonical path | 字段唯一规范路径 |
| owner | `runtime`、`project`、`knowledge-route` 或独立工具 |
| type / constraints | 类型、枚举、范围和跨字段条件 |
| default source | 唯一默认值来源；不得在消费者重复定义 |
| override policy | 是否允许 CLI、环境或项目层覆盖及覆盖方向 |
| environment binding | 唯一环境变量名、必填性和秘密标记 |
| applicable modes | 字段适用的执行模式 |
| legacy aliases | 迁移期别名、告警方式和删除期限 |
| consumers | 预期消费该字段的组件，用于接线检查 |

字段必须按语义归类，不能只按当前文件位置归类：

- 跨项目可调运行策略属于 `RuntimeConfig`；
- 项目专属运行决策属于 `ProjectSpec`；
- AI 寻找业务知识所需的路由属于 `ProjectKnowledgeRoute`；
- 模型协议能力、adapter 接口和算法不变量属于代码协议，不伪装成配置；
- Trace、报告、fixture 和历史结果属于证据，不反向成为配置；
- 仅在显式调用时生效的 hook、Skill、OpenSpec、Draft 等配置属于独立工具。

### 11.4 公共默认、角色策略与项目收窄

模型、重试、并发、上下文预算等配置采用“公共默认 + 显式角色策略 + 受控项目收窄”模型：

```text
RuntimeConfig 公共默认
  -> RuntimeConfig 中登记的 role policy（可选）
  -> ProjectSpec 中 schema 明确允许的项目约束（可选）
```

- 公共模型字段至少覆盖 provider、model、base URL、credential binding、timeout、temperature、reasoning、JSON/tool capability；
- judge、attribute、mock、live stub、context analyzer 等角色默认继承公共模型；
- 角色确需不同模型或能力时，必须在 `impl/config.yaml` 的正式角色策略中显式声明，不得在角色代码中硬编码；
- 项目层只有在 schema 明确允许时才能覆盖角色策略，并应以业务所需的收窄或选择为主，不能发明新的公共 provider 配置；
- 模型变更必须先校验目标模型对 reasoning、JSON 输出、tool calling 和上下文长度的兼容性；
- 规范文档可以说明模型能力要求，但不得写成第二个会影响运行结果的 model 默认值。

因此，将公共调用模型改为 `deepseek-v4-flash` 时，长期只修改 `impl/config.yaml` 的规范 model 字段；允许覆盖该字段的已登记环境变量仍可临时替换它，显式角色策略保持自己的选择。所有继承公共模型的消费者必须在 resolved config 中同时显示新值。

### 11.5 执行模式驱动的条件配置

项目 schema 不能把所有服务字段对所有项目一律设为必填。`runtime.mode` 是条件校验的判别字段，当前协议至少覆盖仓库已经使用的以下模式：

| mode | live 服务 | API URL/transport | 上传或既有输出 |
|---|---|---|---|
| `existing_service_required` | 必须可用 | 必填并严格校验 | 可选 |
| `existing_service_optional` | 可选 | 选择 live 路径时必填 | 允许 |
| `uploaded_output_evaluation` | 不要求 | 不得因缺少 URL 或 HTTP timeout 阻断 | 必填 |

各模式还必须在 schema 中定义 `project.resources.source`、`project.resources.documents`、ready、interaction、endpoint discovery 和 credential 的必填/可选/禁止矩阵。新增 mode 属于协议变更，不能由某个项目自行写入任意字符串。当前存量 `existing_service` 不是长期枚举；迁移时必须根据项目实际行为显式归一为 required 或 optional，只能在集中 resolver 中做有期限兼容，不能由消费者静默猜测。

`runtime.local_deployment` 只允许出现在使用 live service 的模式；为 true 时必须同时存在 primary service healthcheck 和固定 `scripts/start.sh`，`uploaded_output_evaluation` 等无服务模式必须拒绝本地部署字段。`verifier.attribution.enabled` 不随 mode 推断，所有项目都必须显式声明。

### 11.6 构建和审核职责分离

配置生成、批准、执行和验证由不同职责完成：

1. evals/harness AI 读取知识路由和现有正式配置，只生成初稿或 diff；
2. 人类项目负责人审核业务语义、秘密边界和项目专属决策；
3. resolver 按 schema 机械执行，不推断未声明意图；
4. config-check 独立验证 schema、接线、旁路、秘密和兼容状态；
5. 运行链记录脱敏后的 resolved config 指纹和来源，以便复现。

生成配置的 AI 不能以“能够加载”自证配置正确；人类审核也不能替代自动 schema 和消费者接线测试。

### 11.7 变更验证单位

配置改造的最小完成单位不是“移动一个值”，而是一条纵向闭环：

```text
确定字段 owner
  -> 在权威 YAML/schema 中声明
  -> resolver 解析
  -> 类型化对象承载
  -> 全部目标消费者切换
  -> resolved-config/行为测试证明生效
  -> 删除旧入口和 fallback
```

只改 YAML、只改 loader 或只删除硬编码都不算完成。兼容层只能在新链已经覆盖存量配置、消费者行为等价且门禁能够发现回退时删除。

# 第二章：Changes

本章记录当前仓库与第一章长期协议的差异，以及一次性建设和迁移任务。任务完成后，兼容逻辑应删除；本章列出的当前文件和旧字段不因此获得长期协议地位。

截至 2026-07-22，P0/P1 公共配置闭环已经完成：公共严格 schema、受限 `.env`、登记式覆盖、来源追踪、秘密脱敏、LLM/embedding/Server/Python 消费者接线和 `config-check` 已落地。P2–P5 的项目配置、知识路由和全项目迁移仍按本章后续任务推进；迁移期环境变量 alias 保留至 P5 后删除。

## 1. 当前现状差异

### 1.1 公共模型配置没有形成单一解析链（P1 已解决）

P1 改造前，`impl/config.yaml` 和 `impl/core/config.py` 已表达公共 LLM 配置，但至少还存在以下平行入口：

- `impl/core/llm_client.py` 独立维护 model、base URL、Key 和 fallback；
- `LLM_MODEL` 等环境值可以覆盖 YAML，但登记、来源和最终解析结果没有统一证据；
- `impl/core/live_stub.py` 保存角色专属模型选择，但尚未纳入正式 role policy；
- `impl/checklist/test_deepseek_direct.py` 等诊断入口直接构造 DeepSeek 调用；
- `search-test-case/llm_attribution_server.py` 自带模型分支，是否为独立工具、单次数据输入还是会持久改变默认行为尚未制度化；
- `impl/demand/algorithm.md`、测试期望和历史报告中也出现具体模型名，但没有区分“规范能力要求、当前运行默认、测试 fixture、历史证据”。

该断链现已由统一 resolver、消费者合同测试和旁路门禁消除。只修改 `impl/config.yaml` 的公共 model 时，默认 LLM 消费者同步采用新值；`live_stub` 等显式 role policy 保持自己的选择并可追踪来源。

### 1.2 公共可调策略仍散落在代码和环境变量中

除 model 外，embedding、temperature、reasoning、重试、timeout、上下文上限、attribute 预算、并发、数据根目录、host/port 等值仍存在代码常量、多个环境变量或调用点 fallback。部分公共上限和项目收窄规则没有明确覆盖方向，同一策略可能在 bootstrap、policy、attribute 或 server 中重复。

### 1.3 环境变量尚未形成登记与秘密替换链（公共层已解决）

P1 改造前存在多个同义环境变量、模块直接 `os.getenv()`、从 `env.md` 读取 Key、缺少统一 dotenv bootstrap 等情况。公共层现已具备：

- 唯一变量名和字段绑定；
- 根目录 `.env` 的加载、忽略和未登记变量检查；
- `.env` 受限语法、字面值解析和重复 key 检查；
- 从登记表生成 `.env.example`；
- 与 Secret Manager 使用同名登记的生产注入；
- resolved config 和错误消息的统一脱敏。

公共消费者已停止读取 `env.md`，并由根目录 `.env`/进程环境提供本机值。项目层和独立工具的登记并集要在 P2–P4 完成；生产 Secret Manager 继续使用同名登记，不形成新解析入口。

### 1.4 公共启动配置包含不可移植值

`impl/config.yaml` 的 Python executable 当前包含开发者个人 conda 绝对路径。外部源码、文档路径和 endpoint discovery 中也存在个人机器路径或多种路径表达，无法直接迁移到其他机器。

### 1.5 人类知识路由尚未统一

`projects/project.template.yaml`、部分项目和 evals 当前混用 `project_id`、顶层 `live/docs/source/ready/interaction` 与旧 `common.api/common.start/common.ready`。有的 `docs` 是无类型列表，有的路由仍含个人绝对路径或“暂无”占位。当前还不能稳定判断资料用途、必填性和可达性，也不能保证 harness AI 只从一个入口出发即可到达全部允许知识。

知识路由迁移统一采用以下映射：

| 当前字段或行为 | 规范路径或处理方式 |
|---|---|
| `project_id`、顶层 `name/description` | `project.id/name/description` |
| `live.startup_doc/api_doc/env_doc`、`common.start/api` | 转为稳定文档 ID下的 `documents.<id>`，显式填写 `type/required/description` |
| 无类型 `docs` 列表 | 按用途迁入 `documents.<stable_id>`；无法判定用途时阻断并要求人工分类 |
| `source.repo`、`common.source.repo` | `source.repository` |
| 顶层 `ready/interaction`、`common.ready` | `onboarding.ready/interaction` |
| 个人绝对路径 | 仓库相对路径，或 `${VAR}` 加同文件环境登记 |
| `path: 暂无`、空值、虚构路径 | 删除可选入口；必填资料缺失时阻断接入 |

迁移时还必须按第 4.4 节补齐文档类型最低合同；不能只重命名 YAML 键而保留不可判读的正文。

### 1.6 项目运行配置存在别名、重复来源和消费者 fallback

现有项目使用 `source_project`、`application.external_repo`、`common.source`、document path、endpoint discovery source root 等多种方式表达相近来源；API URL、timeout、service mode 也可能同时存在于 YAML 和项目代码 fallback。字段形式看似统一，并不代表 `ProjectSpec` 和实际消费者采用了它。

### 1.7 项目 YAML 解析和 schema 不完整

项目加载路径仍依赖手写 `load_simple_yaml`，无法提供完整 YAML 语义、严格未知字段、重复 key、版本和跨字段校验。公共配置与项目配置因此具有不同解析行为和错误模型。

### 1.8 执行模式没有驱动条件校验

仓库现有项目至少使用 `existing_service`、`existing_service_required`、`existing_service_optional` 和 `uploaded_output_evaluation`。上传输出测评项目不需要 live API；若统一强制 URL、HTTP timeout 或 endpoint discovery，会把合法项目误判为错误。当前 schema 尚未形成按 mode 校验必填、可选和禁止字段的矩阵。

### 1.9 模板字段尚未证明能到达 `ProjectSpec`

`impl/projects/project.template.yaml` 中的 `common.source.repo`、`common.docs` 等字段没有被现有测试证明会填充实际 `ProjectSpec.source_project` 和 documents。现有测试偏重模板文本和宽松加载，不能发现“模板有字段、loader 丢字段、消费者继续 fallback”的断链。

### 1.10 独立工具边界尚未形成可验证合同

hooks、Skill、OpenSpec 和 `draft_config.yaml` 自治本身不是问题；问题是当前门禁不能证明它们只在显式调用时生效，也没有区分单次运行数据、artifact 与持久行为变更。改造必须允许前两者通过各自类型化协议直接进入某次 run 或证据存储，只要求改变后续默认行为的 promotion 经人类审核后写入公共/项目配置。`search-test-case` 等目录也需要按消费者和生效边界分类，而不能仅按目录名判断。

### 1.11 当前测试会保护旧行为，但不能证明新协议成立

现有 runtime/project 配置测试能够防止部分回归，却也可能把旧默认、旧 alias 或宽松加载固化为期望。迁移需要先补“解析后消费者合同测试”，再更新旧断言；不能以 YAML 文本出现某个值作为配置生效证据。

### 1.12 现有项目顶层结构不是长期标准

当前项目配置同时使用 `common`、`api`、`application`、`source_project`、`endpoint_discovery`、`frontend_extensions`、各角色 draft 和 `extra`。这些字段按历史消费者逐步增加，存在职责重叠和万能容器，不能作为正式 schema 的顶层结构继续扩展。

迁移统一采用以下映射：

| 当前字段或行为 | 规范路径或处理方式 |
|---|---|
| `project_id`、`name`、`description`、`capabilities` | `project.id`、`project.name`、`project.description`、`project.capabilities` |
| `source_project`、`application.external_repo`、`common.source.repo` | 合并为 `project.resources.source.repository` |
| 源码仓库内的命名子路径 | `project.resources.source.paths.<name>` |
| `documents` 和 loader 自动发现的默认文档 | 合并为显式 `project.resources.documents`；删除隐式发现 |
| `application.mode` | `runtime.mode` |
| interaction 相关字段 | `runtime.interaction` |
| `common.ready` | `runtime.ready` |
| `api`、`common.api`、`application.api_base` | 合并为 `runtime.services.primary` |
| `application.downstream_search` 等外部依赖 | `runtime.services.dependencies.<service_id>` |
| `application.start`、`application.startup_command`、`common.start.command` | 迁移为固定 `scripts/start.sh`，并按需声明 `runtime.local_deployment.enabled: true` |
| `endpoint_discovery` | `verifier.endpoint_discovery`；source root 改为相对 `project.resources.source.repository` |
| `field_provider_module`、`field_provider_class` | `verifier.field_provider` |
| `attribute_draft`、`judge_draft`、`mock_draft`、`live_draft` | `verifier.roles.<role>.draft` |
| `role_assets` | `verifier.assets` |
| `frontend_extensions` 中的业务枚举、等价规则 | 进入所属功能分区的已注解 `extra` |
| `frontend_extensions` 中纯展示字段 | 进入 `verifier.presentation` |
| `adapter: adapter.py` 等固定协议文件名 | 从配置删除，由项目协议约定 |
| 顶层 `extra` | 逐字段迁入所属分区的已注解 `extra`，无法归属的字段删除 |
| 当前默认执行的归因阶段 | 每个项目显式声明 `verifier.attribution.enabled` |

知识路由中的源码引用不因该映射自动与 `project.resources.source.repository` 合并。前者仍是 harness AI 的知识授权入口，后者是 verifier 运行配置中的源码引用；两者可以使用相同环境变量并由一致性门禁校验，但运行时不能跨层读取。

### 1.13 本地服务启动没有统一生命周期

当前启动方式可能出现在 `application.startup_command`、项目文档、开发者个人脚本或外部仓库命令中；运行链没有统一的 health-first、启动锁、启动超时和复用协议。以 deerflow 为例，现有 `startup_command` 还包含个人绝对路径。

迁移必须为需要 verifier 管理本地启动的项目新增固定 `impl/projects/<project>/scripts/start.sh` 包装，并显式设置 `runtime.local_deployment.enabled: true`。不需要本地启动的项目不得创建占位脚本或启用该字段。

### 1.14 归因和项目特殊字段缺少统一开关协议

当前 attribute/归因已有独立调用入口和项目实现，但项目 YAML 没有统一 boolean 决定是否进入主链，也没有把手动触发定义为不修改配置的单次 override。现有 `extra` 和 `frontend_extensions` 还混合了业务规则、展示字段和实现说明，缺少统一注解、项目 schema 和消费者登记。

迁移必须为每个项目显式补充 `verifier.attribution.enabled`，并把特殊字段按所属分区迁入第 5.2.7 节规定的 `extra`。不得通过是否存在 attribute.py、attribution.md 或 reference 字段猜测开关值。

## 2. 配置场景盘点与归属

迁移前必须将仓库中所有类似配置场景按下表归属。表中“标准位置”指权威产出位置，不包括 schema、测试和派生证据。

| 场景 | 标准位置 | 迁移重点 |
|---|---|---|
| 默认 LLM provider/model/base URL/credential | `impl/config.yaml` | 删除 client、server、script 的重复默认和 Key 解析 |
| judge/attribute/mock/live stub 等角色模型能力 | `impl/config.yaml` 的 role policy | 显式继承或覆盖，并验证 JSON/tool/reasoning 兼容性 |
| embedding provider/model/credential | `impl/config.yaml` | 与 LLM 使用同一 resolver 模式，避免知识库旁路 |
| server/CLI host、port、公共存储和数据根目录 | `impl/config.yaml` | CLI 只做已登记临时覆盖 |
| retry、temperature、reasoning、公共 timeout | `impl/config.yaml` | 每个字段一个默认，消费者不得复制 |
| 公共上下文、并发、资源预算上限 | `impl/config.yaml` | 明确公共上限和项目是否只能收窄 |
| 项目 API、transport、endpoint、service timeout | impl 项目配置的 `runtime.services` | 受 `runtime.mode` 条件校验 |
| 项目身份、capability、源码、文档和特殊字段 | impl 项目配置的 `project` | 源码和文档归入 `project.resources`；特殊字段使用已注解 `extra` |
| 项目 ready、interaction 和本地部署 | impl 项目配置的 `runtime` | 固定启动脚本、health-first 和条件校验 |
| field provider、endpoint discovery、角色 draft 和资产 | impl 项目配置的 `verifier` | 只表达 verifier 针对该项目的接入和处理方式 |
| 归因是否默认进入主链 | impl 项目配置的 `verifier.attribution.enabled` | boolean 项目默认值；手动执行是 run override |
| 纯前端和报告展示字段 | impl 项目配置的 `verifier.presentation` | 不得影响 protocol、judge 或 attribute 结果 |
| 项目专属预算或策略收窄 | `impl/projects/<project>/project.yaml` | 只允许 schema 登记的覆盖方向 |
| 业务知识、启动/API/需求文档和外部源码入口 | `projects/<project>/project.yaml` | 只服务 evals/harness AI，不被运行时读取 |
| Python executable、外部仓库路径 | 公共或所属项目 YAML + 已登记环境值 | 仓库默认必须可移植，机器值不落库 |
| hook、Skill、OpenSpec、Draft 任务参数 | 所属独立工具 | 单次数据/报告走各自协议；仅持久默认行为 promotion 回到 verifier 配置 |
| adapter 协议、算法不变量、模型能力最低要求 | 代码协议或规范文档 | 不做可变运行默认；变化走协议评审 |
| fixture、case、Trace、manifest、report、历史模型名 | 测试或证据目录 | 不批量改写，不得被运行时读取 |

该盘点不是一次性搜索清单。新增字段或新消费者时，必须先确定 owner、覆盖方向和验证方式，才能合入。

## 3. 构建总方案

建设分为两条产品配置主线、一条知识接入支线和一个横向门禁。三条链共享字段所有权、环境值 bootstrap、错误模型和解析证据，但不得互相读取对方的权威 YAML。

### 3.1 主线 A：RuntimeConfig / bootstrap

目标是完成公共配置的纵向闭环：

1. 为 `impl/config.yaml` 建立严格 schema 和字段所有权；
2. 建立根目录 `.env`、进程环境和 Secret Manager 的登记式绑定；
3. 统一 bootstrap 和 `RuntimeConfigResolver`；
4. 让 LLM、embedding、server、CLI、knowledge base、Python launcher 等消费者只接收 `RuntimeConfig`；
5. 为 role policy、模型能力和 import-sensitive 初始化建立显式合同；
6. 用 resolved config 和行为测试证明所有消费者采用同一结果；
7. 最后删除 `env.md` Key、直接 `os.getenv()`、重复默认和个人路径。

### 3.2 主线 B：ProjectConfig / ProjectSpec

目标是完成每个项目运行配置的纵向闭环：

1. 为 `impl/projects/<project>/project.yaml` 建立严格 schema；
2. 以 `runtime.mode` 驱动条件字段矩阵；
3. 统一标准 YAML parser、路径解析、alias 归一化和错误模型；
4. 明确模板字段到 `ProjectSpec` 的逐字段映射；
5. 让 adapter/live/mock/judge/attribute/project tools 只接收类型化对象；
6. 以服务型项目和上传输出项目分别做 pilot，证明迁移前后行为等价；
7. 完成全部项目迁移后删除 consumer fallback 和兼容 alias。

### 3.3 支线 C：ProjectKnowledgeRoute / evals

目标是让项目接入只从人类知识路由开始：

1. 建立 `ProjectKnowledgeRoute` schema 和路由可达性检查；
2. 迁移现有知识路由与 evals 的旧字段假设；
3. scaffold 基于正式项目模板/schema 生成初稿；
4. 已存在项目只生成 diff、冲突和来源 revision，不静默覆盖；
5. 人类审核后才写入正式项目运行配置。

### 3.4 横向门禁 G：Config Contract

横向门禁贯穿全部阶段，至少检查：

- 字段 owner、唯一默认值、覆盖方向和消费者清单；
- schema、模板、类型对象和实际 YAML 一致；
- 未登记环境变量、秘密、个人绝对路径和 YAML/环境旁路；
- execution mode 条件字段矩阵；
- legacy alias 的使用告警、项目清单和删除期限；
- resolved config 的来源、脱敏和指纹；
- 配置生成、人类批准、运行加载和独立验证的证据链。

## 4. 一次性改造原则

- 以“来源 → resolver → 类型对象 → 消费者 → 证明”作为最小交付单位；
- 先冻结合同和补消费者探针，再移动值或删除旧入口；
- 先建立秘密替代链，再删除 `env.md` 或旧 Key 来源；
- 先证明新旧解析结果和业务行为等价，再删除 alias/fallback；
- 项目按 execution mode 迁移，不用一个服务型 schema 强套所有项目；
- 不批量覆盖人类审核字段，不在配置迁移中改变 judge/attribute 算法语义；
- 独立工具按生效边界治理，不因目录位置被强行并入产品配置；
- 每个兼容字段必须有 owner、使用清单、告警和删除条件，不能永久保留；
- 文档中的规范能力要求、测试 fixture 和历史证据不作为运行默认值迁移。

## 5. 分阶段建设计划

### P0. 冻结合同和建立基线（已完成）

交付内容：

- 完成字段所有权清单，覆盖第 2 节全部场景；
- 冻结 `project`、`runtime`、`verifier` 三个业务分区与 `environment`、`metadata` 两个支撑分区的字段边界和旧字段迁移映射；
- 冻结本地部署 health/start/reuse 合同、归因 boolean 与手动 run override 合同、分区 `extra` 注解格式；
- 冻结 LLM/embedding role policy、环境变量规范名和覆盖优先级；
- 冻结 execution mode 条件矩阵；
- 建立 legacy alias/fallback 清单、现有消费者清单和退出期限；
- 为当前解析结果建立脱敏快照和消费者合同测试；
- 建立只读 `config-check` 骨架，先报告问题而不改变运行。

退出条件：能够回答任意一个可调值“由谁拥有、从哪里进入、哪些消费者采用、如何证明”，且后续迁移不会无意改变当前业务语义。

### P1. 纵向完成 RuntimeConfig（已完成）

交付顺序：

1. 建立严格 `RuntimeConfig` schema、标准 YAML parser 和统一错误模型；
2. 实现登记式环境绑定、根目录 `.env` 受限语法加载、Git ignore、`.env.example` 生成和 Secret Manager 同名注入合同；
3. 实现统一 bootstrap、路径解析和 resolved config 脱敏输出；
4. 接入 LLM、embedding、server、CLI、knowledge base 和 Python launcher；
5. 把 live stub 等例外迁入正式 role policy；
6. 验证公共 model、base URL、credential、retry、timeout 等变更传到所有目标消费者；
7. 只有替代链验证通过后，删除 `env.md` Key 读取、重复 `DEFAULT_*`、直接环境解析和个人 Python 路径。

退出条件：所有公共消费者只能从 `RuntimeConfig` 获值；修改一个公共字段时，所有继承它的消费者同步变化，显式角色例外保持不变。

### P2. 建立 ProjectConfig 合同并完成双模式 pilot

交付顺序：

1. 建立严格 `ProjectConfig` schema 和标准项目 resolver；
2. 落实 execution mode 条件字段矩阵；
3. 建立三个业务分区和两个支撑分区到类型化 `ProjectSpec` 的逐字段映射测试；
4. 将旧字段和 URL/path alias 统一集中在 resolver 兼容层，不允许消费者继续兼容；
5. 实现本地部署的 health-first、固定启动脚本、项目锁、启动超时和复用合同；
6. 实现 `verifier.attribution.enabled` 主链开关和不改配置的幂等手动 run override；
7. 实现分区 `extra` 注解、项目 schema、消费者登记和标准字段升级检查；
8. 选择一个 existing-service 项目和 `uploaded_output_evaluation` 项目做 pilot；
9. 对 pilot 比较迁移前后的 resolved `ProjectSpec`、adapter 行为和最小 run-chain；
10. pilot 稳定后冻结项目模板和 scaffold 输入合同。

推荐 pilot 为 `client_search` 与 QA 上传输出项目：前者覆盖 live API、endpoint、外部源码和本地启动包装，后者证明无 live API 的模式不会被错误阻断，并覆盖 `verifier.attribution.enabled: false`。

退出条件：两个 pilot 均只通过 `ProjectSpec` 驱动，模板字段不丢失，且不同 mode 的必填规则准确。

### P3. 完成知识路由、evals 和全项目迁移

交付顺序：

1. 建立并迁移 `ProjectKnowledgeRoute` schema、稳定文档 ID 和文档类型最低合同；
2. 修正 evals 对旧 `common.api` 等字段的假设；
3. 实现路由目标可达性、越界和外部变量登记检查；
4. 让 scaffold 从知识路由生成符合 P2 schema 的项目配置初稿；
5. 已有项目只产生可审核 diff、冲突和 source revision；
6. 按项目迁移其 impl 配置并逐个运行配置、adapter、mock 和最小链路回归；
7. 为确需本地托管的项目建立标准 `scripts/start.sh`，其余项目显式保持 `local_deployment.enabled: false` 或省略该区；
8. 为每个项目审核归因默认值，并迁移、注解或删除现有特殊字段；
9. 每个项目迁移完成后，删除该项目消费者中的 fallback，但保留集中兼容层直至全部项目完成。

退出条件：每个项目都能从唯一知识入口完成接入，并由唯一 impl 项目配置驱动运行；AI 重跑不会覆盖人工决策。

### P4. 收敛剩余可调策略和工具 promotion 边界

交付内容：

- 收敛上下文、attribute 预算、并发、重试、存储、数据根目录等公共或项目可调项；
- 明确公共 cap 与项目 override 的允许方向；
- 为 Draft/Skill/hook/OpenSpec/search-test-case 等独立工具登记单次输入、artifact 和持久行为 promotion 的类型与边界；
- 将 promotion 后的 role asset、启用开关和生产选择写回正式项目配置；
- 汇总跨项目 `extra`，将语义一致或被公共 core 消费的字段提升为正式 schema；
- 对保留在代码中的协议常量和算法不变量添加分类测试，避免以后再次当作配置搬运。

退出条件：静态扫描发现的每个可疑常量、环境变量和 sidecar 都有明确归属、消费者和验证结论。

### P5. 强制门禁并退出兼容层

交付内容：

- 将 `config-check` 纳入 CI、onboarding 和发布前检查；
- 阻断未知字段、未知环境变量、秘密、个人路径、直接 YAML/Markdown/env 旁路；
- 阻断本地部署缺少脚本/healthcheck、归因开关缺失以及未注解/无 schema/无 consumer 的 `extra`；
- 报告 resolved config 指纹、实际 alias 使用和 schema version；
- 在全部调用方与项目迁移后删除 `load_simple_yaml`、旧字段 alias、旧环境变量别名和集中 fallback；
- 更新 README、evals Skill、模板和接入说明；
- 执行全量配置、协议、adapter、mock 和 run-chain 回归。

退出条件：第一章协议无需任何永久兼容逻辑即可独立运行。

## 6. 建设重点

### 6.1 第一重点：消费者接线，而不是文件搬家

最危险的失败是配置看似已集中，但 direct client、项目 client 或某个角色仍使用代码默认。验收必须读取 resolver 输出并观察真实消费者；仅检查 YAML 文本、常量是否删除或单元测试是否通过都不充分。

### 6.2 第二重点：执行模式条件化

项目配置覆盖全项目不代表所有项目字段相同。schema 必须以 mode 表达差异，尤其不能让上传输出测评为了通过校验伪造 live URL、timeout 或 endpoint。

### 6.3 第三重点：默认值和覆盖方向唯一

每个字段只允许一个默认来源。公共配置、角色策略、项目配置、环境和 CLI 的关系必须是预先登记的有向覆盖，不允许消费者自行选择优先级。

### 6.4 第四重点：秘密和迁移顺序

秘密不能进 YAML，但这不意味着可以让每个模块各读环境变量。统一登记和 bootstrap 是唯一入口；新秘密通道可用并验证后，旧 `env.md` 等来源才能删除。

### 6.5 第五重点：独立验证与可追踪性

AI 生成、人类审核、loader 执行和 config-check 验证各有职责。每次运行应能说明最终非敏感配置值来自 YAML、环境、CLI 还是兼容 alias，并用指纹关联 Trace；否则跨机器迁移失败时无法复现。

### 6.6 第六重点：公共字段优先，特殊字段可升级

项目首先复用正式字段，确有差异才进入所属分区的已注解 `extra`。`extra` 必须可定位到 schema 和消费者；一旦形成跨项目共性，就回收为正式字段，而不是让多个项目复制相似私有 key。

## 7. 关键验收场景

### 7.1 公共模型切换

将 `impl/config.yaml` 的公共 model 改为 `deepseek-v4-flash`，不修改任何消费者代码。验收必须证明：

- `RuntimeConfig` 的 resolved model 为新值；
- judge、attribute、mock、context analyzer 和普通项目 client 中所有继承公共策略的消费者均为新值；
- 已登记的 `LLM_MODEL` 临时覆盖仍遵守优先级并显示来源；
- live stub 等显式 role policy 若未继承公共模型，则保持自己的配置并在证据中可见；
- reasoning、JSON、tool calling 和上下文能力检查通过；
- `env.md`、direct client、checklist 和项目代码不能把 model 或 Key 改回旧值；
- 历史 Trace/report 中的旧模型名保持历史真实性，不被批量改写。

### 7.2 服务型项目迁移

迁移 `client_search` 或同类项目后，改变项目配置中的规范 API URL/timeout/source 字段，`ProjectSpec` 和 live adapter 必须同步采用新值；旧 alias 和代码 fallback 不得改变最终结果。

### 7.3 上传输出项目迁移

`uploaded_output_evaluation` 项目在不提供 live API URL 的情况下应通过 schema，并能从上传/既有输出完成评价；服务型字段不得被伪造为占位配置。

### 7.4 环境与跨机器迁移

在没有开发者绝对路径和 `env.md` Key 的新机器上，仅提供仓库、根目录 `.env` 或同名 Secret Manager 值、项目外部源码 mount，即可通过 config-check 并启动最小链路。未登记变量不能影响行为，秘密不出现在日志和 resolved config。

### 7.5 本地服务按需启动与复用

对 `runtime.local_deployment.enabled: true` 的 pilot，服务已健康时不得重复执行脚本；服务未启动时必须只执行一次固定 `scripts/start.sh`，在配置时限内等待健康并继续测评；并发请求不得重复拉起；测评完成后服务保持运行。对 false、缺失或无 live service 的项目，运行时不得调用任何项目启动脚本。

### 7.6 归因开关、手动覆盖与特殊字段

同一失败用例分别在 `verifier.attribution.enabled: true` 和 `false` 下运行时，前者自动产生归因阶段，后者主链跳过；对后者发起手动归因只影响该 run，项目配置保持不变且重复请求幂等。带 `extra` 的 pilot 必须证明注解、项目 schema 和声明消费者一致，删除或改名未声明字段时门禁能够阻断。

## 8. 非目标

本次配置建设不负责：

- 重写历史 Trace、报告或 fixture 中记录的旧模型和旧路径；
- 把所有独立 hook、Skill、OpenSpec、Draft 配置合并进 verifier YAML；
- 把 adapter 协议、算法实现和业务评价标准改造成可调配置；
- 借配置迁移改变项目业务行为、judge 边界或 attribute 算法；
- 在没有消费者合同测试的情况下追求一次性删除全部兼容逻辑。

## 9. 改造完成验收

全部一次性改造完成时，必须同时满足：

- `impl/config.yaml` 的每个公共参数只有一条 resolver 和消费者链；
- 所有公共 LLM/embedding 调用消费统一配置，不再读取 `env.md` Key 或代码模型默认；
- role policy 和项目覆盖均由 schema 明确登记，模型能力兼容检查通过；
- 公共、知识路由、项目和独立工具环境变量均先登记后消费；
- 根目录 `.env` 被 Git 忽略并按受限语法字面解析，`.env.example` 可确定性生成，生产 Secret Manager 使用同名登记；
- 所有人类项目知识路由遵循同一 schema，资料可达且 verifier 运行时不读取它；
- 所有业务项目配置按 execution mode 通过 schema，并能无损构造 `ProjectSpec`；
- 所有项目显式解析归因 boolean；本地托管项目通过统一 health/start/reuse 合同，其他项目不会误触发启动；
- 所有项目特殊字段均位于所属分区的已注解 `extra`，跨项目共性字段已完成标准化评审；
- 所有运行消费者只接收类型化配置，不自行解析 YAML、Markdown、dotenv 或环境变量；
- 模板、schema、resolver、类型对象、实际项目和消费者合同相互一致；
- hooks、Skill、OpenSpec、Draft 等自治配置只由所属工具显式加载；单次输入和 artifact 走各自协议，持久默认行为 promotion 回到公共或项目配置；
- 配置生成只提交 diff，人类批准、loader 执行和独立门禁证据可追踪；
- config-check 已进入 CI/onboarding，能阻断秘密、个人路径、旁路和过期 alias；
- adapter、protocol、mock、双模式 pilot 和最小 run-chain 回归通过；
- 旧字段、旧环境变量别名、简化 parser、consumer fallback 和其他临时兼容代码已删除。
