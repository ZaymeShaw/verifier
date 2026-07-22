# Verifier 路径前缀与可移植引用协议

本文是 [config.md](./config.md) 的路径补充协议。config.md 继续负责配置归属、环境变量、知识路由和加载优先级；本文只负责文件路径如何书写、解析、持久化和审核，不新增配置层。config.md 中 start.md 等相对路径示例的目标含义不变；本文把它们规范化为 route://start.md 等显式前缀，属于表达升级，不改变配置所有权或业务语义。

# 第一章：Spec 标准

## 1. 一条完整路径链

路径只允许沿以下链路进入正式运行：

    三份 YAML 声明逻辑路径或机器根绑定
      -> .env / 进程环境 / Secret Manager 提供机器根实际值
      -> 统一 loader 构造 PathRoots
      -> PathResolver 解析显式前缀
      -> 运行时使用物理 Path
      -> 派生产物保存 LogicalPathRef
      -> config-check / writer guard 审核

三份 YAML 的职责保持不变：

| 文件 | 路径职责 |
|---|---|
| impl/config.yaml | verifier 公共命令、公共资源和跨项目路径 |
| impl/projects/<project>/project.yaml | 项目业务源码引用、运行资源和 verifier 项目资产 |
| projects/<project>/project.yaml | evals/harness AI 的知识文档与业务源码路由 |

根目录 .env、进程环境和 Secret Manager 只提供已登记变量的机器实际值，不成为第四份配置事实源。

## 2. YAML 路径前缀

### 2.1 固定前缀

所有正式 YAML 中的文件或目录引用必须显式带逻辑前缀：

| YAML 前缀 | 逻辑根 | 物理来源 | 典型用途 |
|---|---|---|---|
| business:// | business_source | 项目 source.repository 绑定的已登记环境值 | 业务源码内部文件和目录 |
| verifier:// | verifier_repo | 当前 verifier 仓库自动发现 | verifier 公共脚本、fixture 和仓库资源 |
| project:// | project_package | impl/projects/<project>/ | 当前项目 adapter、role、tool、investigation 和 draft 资产 |
| route:// | knowledge_route | projects/<project>/ | 知识路由文档 |
| artifact:// | artifact_package | 当前运行上下文显式传入 | active state、receipt、report 和 package 内产物 |

前缀不是 URL，也不是新的物理路径。它只告诉 resolver 应当在哪个逻辑根下解析后面的相对位置。

### 2.2 机器根绑定

机器绝对路径只允许存在于根目录 .env、进程环境、Secret Manager 和运行时内存。

项目 YAML 只引用已登记变量：

    project:
      resources:
        source:
          repository: ${DEERFLOW_REPO}

    environment:
      variables:
        DEERFLOW_REPO:
          bind: project.resources.source.repository
          type: path
          required: true
          secret: false

机器 A：

    DEERFLOW_REPO=/Users/example/work/deer-flow

机器 B：

    DEERFLOW_REPO=/srv/work/deer-flow

换机器时只修改机器值；business:// 路径不变。

禁止在 YAML 中拼接环境变量：

    # 禁止
    ${DEERFLOW_REPO}/src/api.py

应改为：

    business://src/api.py

### 2.3 非文件路径

以下值不使用文件前缀：

- python、chromedriver 等 command name，由系统 PATH 查找；
- http://、https:// 等 URL/API endpoint；
- provider、model、protocol、asset ID；
- inline 文本或 payload。

字段 schema 必须先区分 filesystem path、command、URI、ID 和普通文本，不能只根据字符串中是否包含斜杠判断。

### 2.4 语法要求

前缀路径格式固定为：

    <prefix>://<relative-location>

relative-location 必须：

- 使用 POSIX / 分隔符；
- 不以 /、盘符、UNC、~ 或 file:// 开头；
- 不包含变量展开；
- 规范化后仍位于声明逻辑根内；
- 符号链接解析后仍位于声明逻辑根内。

新协议不允许无前缀的裸相对文件路径。旧的 start.md、src、draft/tool.py 等标量只作为第二章中的迁移输入，不是长期标准。

## 3. 三份 YAML 的完整写法

假设：

    verifier 仓库 = /work/verifier
    DEERFLOW_REPO = /work/deer-flow

### 3.1 公共配置

    # impl/config.yaml
    python:
      executable: python

    browser:
      driver_path: chromedriver

python 和 chromedriver 是 command name，不是文件路径。如果以后新增公共脚本字段，应写：

    maintenance:
      script: verifier://scripts/maintenance.py

解析结果：

    /work/verifier/scripts/maintenance.py

### 3.2 项目运行配置

    # impl/projects/deerflow/project.yaml
    project:
      resources:
        source:
          repository: ${DEERFLOW_REPO}
          paths:
            lead_agent_prompt: business://backend/packages/harness/deerflow/agents/lead_agent/prompt.py

    verifier:
      roles:
        attribute:
          draft:
            module: project://draft/attribute.py

      assets:
        - asset_id: attribute_investigation
          production_path: project://investigation/attribute
          candidate_path: project://draft/investigation/attribute

      endpoint_discovery:
        source_roots:
          - business://src
          - business://app

解析结果：

| YAML 值 | 运行时物理路径 |
|---|---|
| business://backend/.../prompt.py | /work/deer-flow/backend/.../prompt.py |
| project://draft/attribute.py | /work/verifier/impl/projects/deerflow/draft/attribute.py |
| project://investigation/attribute | /work/verifier/impl/projects/deerflow/investigation/attribute |
| business://src | /work/deer-flow/src |

### 3.3 人类知识路由

    # projects/deerflow/project.yaml
    documents:
      startup:
        path: route://start.md
      api:
        path: route://live.md
      requirements:
        path: route://project.md

    source:
      repository: ${DEERFLOW_REPO}

解析结果：

| YAML 值 | 运行时物理路径 |
|---|---|
| route://start.md | /work/verifier/projects/deerflow/start.md |
| route://live.md | /work/verifier/projects/deerflow/live.md |
| route://project.md | /work/verifier/projects/deerflow/project.md |

### 3.4 如何改变路径所属根

配置作者直接修改前缀：

    # 原来读取业务源码
    path: business://src/check.py

    # 改为读取 verifier 仓库
    path: verifier://fixtures/check.py

字段 schema 必须声明 allowed_prefixes。若 verifier:// 在该字段的允许集合中，修改 YAML 即可生效；若不允许，loader/config-check 报 PATH_PREFIX_NOT_ALLOWED。此时需要先修改字段 schema 和消费者合同，不能通过裸路径或文件存在性绕过限制。

新路径字段必须在所属 schema 中声明：

    type: path
    allowed_prefixes:
      - business
      - verifier

这不是另一份人工配置登记表；它是字段 schema 的一部分。

## 4. 运行时解析

### 4.1 PathRoots

统一 bootstrap 在内存中构造：

    PathRoots(
      verifier_repo=/work/verifier,
      business_source=/work/deer-flow,
      project_package=/work/verifier/impl/projects/deerflow,
      knowledge_route=/work/verifier/projects/deerflow,
      artifact_package=<当前产物包>,
    )

其中：

- verifier_repo 自动发现；
- business_source 由项目 YAML 的 source.repository 和已登记环境值产生；
- project_package、knowledge_route 根据当前 project 确定；
- artifact_package 由当前运行上下文传入。

PathRoots 不落盘，也不新增 YAML 配置。

### 4.2 PathResolver

统一接口概念上为：

    resolve(prefixed_path, allowed_prefixes, expected_type) -> ResolvedPath

解析顺序：

1. schema 判定字段是文件路径；
2. 解析 business://、verifier://、project://、route:// 或 artifact://；
3. 校验字段 allowed_prefixes；
4. 从 PathRoots 取得唯一根；
5. 规范化 relative-location；
6. 检查越界、symlink、存在性和目标类型；
7. 返回运行时物理 Path。

resolver 不得尝试多个根目录，不得使用 cwd fallback，也不得根据 Path.exists() 猜前缀。下游只能消费 resolved config、ProjectSpec、ProjectKnowledgeRoute 或 ResolvedPath，不再直接读取 YAML、.env 和路径环境变量。

## 5. 派生产物中的路径

### 5.1 LogicalPathRef

YAML 中的前缀路径只面向配置作者。manifest、state、receipt、context、case、可继续读取的 report、endpoint discovery 结果、Draft 产物和 promotion 输入必须保存结构化 LogicalPathRef：

    {
      "location_scope": "business_source",
      "location": "src/api/server.py"
    }

前缀到 scope 的映射固定为：

| YAML 前缀 | LogicalPathRef.location_scope |
|---|---|
| business:// | business_source |
| verifier:// | verifier_repo |
| project:// | project_package |
| route:// | knowledge_route |
| artifact:// | artifact_package |

LogicalPathRef 核心 schema：

| 字段 | 必填 | 含义 |
|---|---:|---|
| location_scope | 是 | 固定逻辑根 |
| location | 是 | 根目录内的 POSIX 相对位置 |
| symbol | 条件必填 | function/class/method 标识 |
| revision | 条件必填 | 仓库或资产版本 |
| sha256 | 条件必填 | 文件或产物内容指纹 |

scope 和 location 永远必填。symbol 只在定位代码符号时填写。revision 和 sha256 不是路径配置，也不要求配置作者手写。

### 5.2 revision 和 sha256

revision 回答“调查或验证针对哪一版源码”，通常是 Git commit 或资产版本。

sha256 回答“这个具体文件或产物内容是否完全一致”。

普通运行引用只需要：

    {
      "location_scope": "business_source",
      "location": "src/api/server.py"
    }

定位函数时增加 symbol：

    {
      "location_scope": "business_source",
      "location": "src/api/server.py",
      "symbol": "create_app"
    }

形成 validation receipt、正式验证结论或 promotion 证据时，由 verifier 自动计算并补充适用的 revision、sha256。目录引用可以使用 repository revision、tree hash 或 manifest hash，不强制伪造单文件 sha256。

### 5.3 覆盖范围

除三份 YAML、.env/进程环境/Secret Manager 和模块内部未持久化的临时 Path 外，所有正式模块在持久化或跨模块传递文件/目录引用时必须使用 LogicalPathRef。

各产物可以增加业务字段，但不能分别发明 source_root、module_path、file_path、run_report 等含义相似却不声明逻辑根的裸路径字段。

URL、command name、ID、inline payload 和不会被正式消费者读取的历史展示字符串不包装成 LogicalPathRef。

## 6. 生命周期

| 生命周期 | 物理绝对路径 | 正式消费者可读取 | 路径格式 |
|---|---:|---:|---|
| config_input | 仅机器值通道和内存允许 | 是 | YAML 显式前缀或已登记根绑定 |
| derived_active | 否 | 是 | LogicalPathRef |
| historical | 可保留既有环境事实 | 否 | 不能重新作为当前资源引用 |
| machine_local | 可以 | 仅所属工具/进程 | 不进入正式 artifact 图 |

历史 report、Trace、case 若要进入 promotion、重新验证或 active state，必须先把其中的资源引用转换为 LogicalPathRef。

hooks、Skill、OpenSpec 可以维护 machine-local 私有路径；其产物进入 verifier 正式链路时必须转换。

## 7. 写入与审核

### 7.1 PortableArtifactWriter

所有进入 active artifact 图的 JSON、YAML、state、manifest、receipt、context、case、可继续读取的 report 和 promotion 输入统一经过：

    schema 校验
      -> LogicalPathRef 校验
      -> 递归 physical-path guard
      -> lifecycle 校验
      -> 脱敏与稳定序列化
      -> 原子写入

正式 producer 不得绕过 writer。

### 7.2 config-check

config-check 是本地、CI 和 onboarding 的统一入口，必须检查：

1. 三份 YAML 中所有 filesystem path 都带已知前缀；
2. root binding 只引用已登记变量；
3. 字段前缀属于 allowed_prefixes；
4. prefix location 不越界、不逃逸；
5. 正式消费者不直接读取路径环境变量；
6. 正式消费者不手工拼根、不猜 cwd、不多根探测；
7. active artifact 的路径字段全部使用 LogicalPathRef；
8. 正式 producer 不绕过 PortableArtifactWriter；
9. tracked/untracked active 文件、symlink 和运行后生成目录均被扫描；
10. 未知 artifact schema、未知路径字段和扫描失败全部 fail closed。

即使实现完全不调用 PathResolver 或 PortableArtifactWriter，也必须通过静态 sink 扫描、changed-file 扫描、active artifact schema 扫描和命令结束后的生成目录扫描发现旁路。

普通 Python 路径操作、临时日志和测试不是错误；只有它们构造正式运行依赖或 active 引用时绕过本协议才阻断。native extension、动态代码或仓库外隐藏写入若进入正式范围，需要额外文件系统 sandbox/audit hook。

### 7.3 错误码

| issue code | 含义 |
|---|---|
| PATH_PREFIX_REQUIRED | YAML 文件路径缺少显式前缀 |
| PATH_PREFIX_UNKNOWN | 使用未知前缀 |
| PATH_PREFIX_NOT_ALLOWED | 字段 schema 不允许该前缀 |
| PATH_ABSOLUTE_CONFIG | 正式 YAML 保存机器绝对路径 |
| PATH_ROOT_UNBOUND | 前缀对应的逻辑根没有绑定 |
| PATH_TRAVERSAL | 规范化后越出逻辑根 |
| PATH_SYMLINK_ESCAPE | symlink 目标越出逻辑根 |
| PATH_ENV_BYPASS | 消费者绕过 loader 直接读取路径变量 |
| PATH_CONSTRUCTION_BYPASS | 消费者绕过 resolver 手工构造正式路径 |
| PATH_SCHEMA_BYPASS | active 产物未使用 LogicalPathRef |
| PATH_WRITER_BYPASS | producer 绕过 PortableArtifactWriter |
| PATH_SCAN_FAILED | 门禁无法完整读取、解析或分类目标 |

错误至少报告配置/产物文件、字段或 JSON pointer、前缀、location 和源码构建位置；不得打印秘密值。

## 8. 跨机器验收

必须证明：

1. verifier 和业务源码移动到不同目录后，只修改已登记机器值即可完成配置加载和最小运行；
2. 三份 YAML 中不存在无前缀文件路径和机器绝对路径；
3. 修改 business:// 为 verifier:// 时，允许字段正确换根，禁止字段报 PATH_PREFIX_NOT_ALLOWED；
4. 同名文件同时存在于多个根时，只按显式前缀解析；
5. business_source 未绑定时明确报 PATH_ROOT_UNBOUND，不回退 verifier；
6. active artifact 不保存物理绝对路径或裸相对路径；
7. 新增未调用 resolver/writer 的旁路 producer 时，门禁必须阻断；
8. URL、API endpoint、command name 和模型 ID 不被误判为文件路径；
9. historical 事实不被重新解释成当前资源。

# 第二章：Changes——现状差异与一次性改造任务

## 9. 当前差异

### 9.1 三份 YAML 仍使用无前缀标量

现有 start.md、src/main/python、draft/attribute.py、investigation/attribute 等路径依赖字段位置和消费者代码才能判断根目录，配置作者无法直接看出含义。

### 9.2 多个消费者仍自行解析路径

Investigation、endpoint discovery、Draft、knowledge/context 和部分项目 adapter 仍存在 cwd fallback、多根候选、直接 Path 拼接或直接环境变量读取。

### 9.3 active 产物仍有裸路径或物理路径

部分 manifest、receipt、Draft state、metadata 和 report 保存 source_root、module_path、run_report 等绝对或无 scope 路径。

### 9.4 writer 与 config-check 尚未覆盖全部旁路

当前检查不能稳定覆盖所有 active artifact、未跟踪文件、symlink、跨平台路径形式和 raw persistence sink。

### 9.5 `20260721` 路径语义基线尚未形成迁移台账

`20260721` 分支记录了迁移前已经被项目配置和消费者使用的路径语义。它是识别“这个值原来指向哪个根、被谁消费、改变后会影响什么”的参照，不是要求恢复的历史文件结构。路径迁移不得把旧 YAML、旧绝对路径或旧多根猜测重新定义为标准，也不得因旧字段位置不合理就直接丢弃其仍被正式链使用的资源引用。

每个历史路径按最小语义单元建立台账：

```text
20260721 字段或产物引用
  -> 原逻辑根和生命周期
  -> 原消费者与当前消费者
  -> 新 YAML 前缀或 LogicalPathRef
  -> PathResolver 解析结果
  -> 消费者采用证明
  -> 跨机器行为回归
  -> 删除旧值、旧拼接或旧猜测
```

历史记录只能得到以下四种处理结论：

1. **迁移**：仍是正式路径事实，进入显式前缀或 LogicalPathRef；
2. **拆分**：旧字段混用了业务源码、verifier 项目、知识路由或产物根，按实际引用拆开；
3. **删除**：只是重复 alias、失效占位或无消费者路径，并有行为证据证明删除安全；
4. **转交**：实际是 URL、command、symbol、ID、历史文本或非路径配置，交回对应 schema，不包装成文件路径。

不得以“YAML 能解析”或“目标文件在当前机器存在”作为迁移完成证据。

### 9.6 历史路径表达与新协议的对照盘点

| 历史表达 | 实际语义 | 新协议处理 | 迁移保护点 |
|---|---|---|---|
| `impl/config.yaml.python.executable` 中的个人绝对路径 | 本机 Python 命令或 executable | 仓库默认使用可移植 command；本机绝对值由已登记 `PYTHON_EXECUTABLE` 注入 | `python` 既可能是 command 也可能是文件路径，resolver 不得把普通 command 错判为仓库相对路径 |
| `source_project`、`application.external_repo`、`common.source.repo` | 业务源码根 | 合并为已登记机器根绑定；仓库内子路径使用 `business://` | 不再保存个人根，不再由消费者多根探测 |
| `documents.source_*` 中的业务仓库绝对路径 | 业务源码文件 | `business://<repo-relative>` 或派生产物中的 `business_source` LogicalPathRef | 不能错误解析为 impl 项目文档 |
| `documents` 中的 `application.md`、`judge.md` 等 | verifier 项目实现文档 | `project://<relative>` | 以 `impl/projects/<project>` 为根，不能与人类知识路由混读 |
| `../../../projects/<project>/*.md` | 人类知识路由文档 | `route://<relative>`，只允许知识路由/evals 消费 | 正式 verifier 运行时不得为了兼容重新跨层读取 |
| `endpoint_discovery.source_roots` | 业务源码扫描根 | `business://<relative>` | 所有扫描、黑名单和 endpoint 证据使用同一个业务根 |
| draft module、role asset、investigation package | verifier 项目实现资产 | `project://<relative>` | candidate/production 仍受 draft 与 role asset 协议控制，前缀不能绕过启用条件 |
| `application.startup_command` 中的外部绝对脚本 | 本地服务启动入口 | 固定执行 `project://scripts/start.sh`；包装脚本内部使用已注入业务根 | PathResolver 只定位 verifier 包装脚本，不重新开放任意 command 配置 |
| manifest、receipt、state 中的 `location`、`module_path`、`source_root` | 可继续读取的证据或工具引用 | 按生命周期改为 LogicalPathRef | active 产物不得保存当前机器物理根；symbol 与路径分字段表达 |
| `base_url`、API endpoint、模型 ID、shell command name | 非文件路径 | 保持 url/endpoint/id/command 类型 | 前缀扫描不得误报或包装成 LogicalPathRef |

### 9.7 各项目当前路径迁移复核事项

| 项目 | 已正确处理或方向正确 | 尚未闭环 |
|---|---|---|
| `QA` | uploaded-output 项目不再伪造 HTTP API 路径；人类需求资料归知识路由 | 旧 `source_project: ../../../projects/QA` 删除后，不得由运行时 fallback 重新读取 route 根 |
| `client_search` | 业务 repo 已由 `CLIENT_SEARCH_REPO` 绑定；四个业务配置文件已转为 repo 内命名子路径 | 当前仍依赖字段位置判断这些子路径属于业务根；旧 `source_readme/source_prompt/source_judge_boundary` 退出运行时后的知识差异需单独确认，不得通过路径兼容偷偷恢复跨层读取 |
| `deerflow` | `DEERFLOW_REPO`、业务 prompt 子路径和固定 `scripts/start.sh` 已建立 | attribute/mock investigation manifest 仍保存业务仓库及 verifier 源码绝对路径；源码变化后 sha256/line range 已出现失效实例 |
| `marketting-planning` | 业务 repo 改为环境绑定 | Attribute 仍保留遍历旧 `spec.documents` 中 `source_*` 的消费分支；active manifest 仍保存业务源码绝对路径 |
| `marketting-planning-intent` | 业务 repo 改为环境绑定 | 与 planning 使用两套 repo 环境变量但当前值相同，是否允许独立根尚无明确语义；active manifest 同样保存绝对路径 |

marketing 两个评测项目的业务根必须在迁移前明确为以下一种关系：完全独立、强制共享，或默认共享但允许显式覆盖。路径协议不根据两个 `.env` 值当前相同来推断共享，也不能为了解决重复值让一个项目运行时读取另一个项目的 YAML。

### 9.8 路径迁移必须保护但不得顺带修改的非路径行为

基线复核同时发现若干非路径问题。它们记录在这里是为了约束路径迁移 diff，不表示由本协议定义其最终 schema：

- 旧 `implementation_standard.judge_boundary` 没有进入当前新类型，而 Judge 仍强制消费；路径迁移不得通过放宽 Judge 校验、空 fallback 或恢复旧容器掩盖该断链；
- 当前 resolver 将 `verifier.presentation`、`verifier.extra` 和 `verifier.check_rules` 重新合并为 `ProjectSpec.frontend_extensions`；这是配置类型分层问题，不得借路径前缀改造扩大兼容 mapping；
- `interactive_scenarios`、`event_aliases`、`terminal_events`、`score_dimensions` 等字段会影响 Live、Interaction 或 Judge，不是路径，也不是单纯展示字段；
- 从各项目 `live_schema.py` 删除重复的 `READY/API_ENDPOINT/SCENARIO_ENUM` 可以属于配置去重，但新增 Mock seeds、改变 stage/output 推断或修改 request/output schema 必须拆成独立改动；
- 某个 service `method`、timeout 或 Judge contract 未被消费者采用时，路径回归通过也不能声称整个配置迁移行为等价。

### 9.9 当前审核机制的具体盲区

当前 `config-check --full` 可以发现三份正式 YAML 和部分 Python 消费者中的个人路径，但尚不能保证发现：

1. active manifest、receipt、state、report 中的绝对路径；
2. producer 在未跟踪目录或动态文件中绕过正式 writer；
3. manifest 路径可解析但 revision、sha256 或 symbol 已失效；
4. 消费者直接 `Path(root) / relative`，没有经过 PathResolver；
5. 同一个无前缀相对值在不同消费者中被解析到不同根；
6. symlink、大小写、Windows drive/UNC、macOS/Linux 根差异；
7. 路径字段被藏在通用 `extra`、metadata 或任意 JSON payload 中；
8. 历史只读产物重新进入 active/promotion 链时仍携带旧物理路径；
9. 配置字段已经改写，但消费者继续使用旧 compatibility view 或硬编码路径。

因此，静态文本扫描只能作为一层证据，不能替代 schema、writer、active artifact 图和消费者探针。

## 10. 一次性改造任务

### 10.1 实现前缀 schema

1. 为 filesystem path 字段增加 allowed_prefixes；
2. 实现 business、verifier、project、route、artifact 五个固定前缀；
3. command、URI、ID 和普通文本继续使用各自类型；
4. 新 schema 拒绝无前缀路径、未知前缀和不允许的前缀。

### 10.2 迁移三份 YAML

按字段语义一次性转换：

| 旧值 | 新值 |
|---|---|
| backend/.../prompt.py | business://backend/.../prompt.py |
| src/main/python | business://src/main/python |
| investigation/attribute | project://investigation/attribute |
| draft/attribute.py | project://draft/attribute.py |
| start.md | route://start.md |

source.repository 的已登记环境变量引用保持不变。迁移必须覆盖模板和所有存量项目。

### 10.3 实现统一 PathRoots 与 PathResolver

1. bootstrap 只构造一次 PathRoots；
2. 所有正式消费者只使用 resolver；
3. 删除 cwd fallback、多根探测和直接路径变量读取；
4. 相同前缀在所有消费者中使用相同解析和错误码。

### 10.4 固化 LogicalPathRef

1. 建立公共 schema；
2. 核心字段固定为 location_scope、location；
3. symbol、revision、sha256 按用途条件化；
4. EvidenceRef、manifest、state、receipt、report 和 promotion 输入统一迁移。

### 10.5 迁移 producer 与存量 active 数据

至少覆盖：

- Investigation manifest 和 validation receipt；
- endpoint discovery 结果；
- Knowledge/Context metadata；
- Draft asset、state、iteration report 和 review evidence；
- active Markdown 中被机器解析的文件引用。

历史只读事实不要求批量伪装成新 schema，但不得被正式消费者继续解析。

### 10.6 建立 PortableArtifactWriter

所有正式 structured artifact writer 接入统一 schema、LogicalPathRef、physical-path guard 和原子写入。删除或阻断 raw json/yaml/state sink。

### 10.7 完善 config-check 与 CI

实现前缀检查、allowed_prefixes、active artifact 图、changed-file、static sink、运行后扫描、symlink 和 fail-closed 错误处理。

新增负向测试：

- YAML 裸相对路径；
- YAML 绝对路径；
- 未知/不允许前缀；
- 多根探测；
- producer 绕过 writer；
- active payload 裸路径；
- 动态生成旁路文件；
- scan error。

### 10.8 删除迁移兼容

迁移和回归完成后，删除：

- 无前缀标量兼容；
- 旧 scope 猜测；
- 绝对 EvidenceRef；
- source_root、绝对 run_report 等旧消费；
- 未登记路径环境变量读取；
- 正式 raw writer。

### 10.9 建立逐项目基线保护台账

每个项目开始路径迁移前，必须提交或生成一份不含秘密和个人物理根的审查台账，至少记录：

| 字段 | 内容 |
|---|---|
| historical_location | `20260721` 中的字段或产物位置 |
| semantic_scope | business、verifier、project、route、artifact 或 non-file |
| lifecycle | config、runtime-only、derived-active、derived-historical |
| canonical_target | 新 YAML 字段、LogicalPathRef 或非路径 schema |
| consumers | 当前正式消费者和预期迁移消费者 |
| behavior_probe | 证明目标资源、symbol、service 或文档仍被采用的探针 |
| disposition | migrate、split、delete、handoff |
| deletion_condition | 旧入口何时可以删除 |

台账比较规范化语义和消费者行为，不比较旧新 YAML 文本，也不保存原始个人绝对路径作为新的正式数据。确需审计历史物理位置时，只能作为不可执行、不可 promotion 的历史说明。

## 11. 改造顺序与完成判据

顺序固定为：

    前缀/schema
      -> 三份 YAML 迁移
      -> PathRoots/Resolver
      -> LogicalPathRef
      -> producer/active 数据迁移
      -> PortableArtifactWriter
      -> config-check/CI
      -> 删除兼容
      -> 跨机器回归

完成必须同时满足：

1. 三份 YAML 的文件路径全部显式带前缀；
2. 机器绝对路径只存在于允许的机器值通道和运行时内存；
3. 正式消费者全部通过 PathResolver；
4. derived_active 路径全部使用 LogicalPathRef；
5. 正式 producer 全部通过 PortableArtifactWriter；
6. config-check 对未知路径、未知 artifact 和扫描失败 fail closed；
7. 跨机器回归通过；
8. 旧路径兼容已删除或有明确删除期限。
9. 每个 `20260721` 正式路径引用都有 migrate、split、delete 或 handoff 结论；
10. 每个迁移路径都有消费者采用探针，不能只证明目标文件存在；
11. active manifest/receipt/state 的 LogicalPathRef、revision、sha256 和 symbol 校验通过；
12. 与路径无关的 LiveSchema、Judge、Attribute、Mock 行为变化已从路径迁移 diff 中拆分。

## 12. 本次不处理

本文不修改 config.md 的配置事实源、环境变量优先级、知识路由职责和独立工具自治边界，也不规定业务项目自身如何组织源码或部署平台如何挂载目录。
