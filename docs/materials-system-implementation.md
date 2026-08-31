# 资料系统实施文档

状态：V1 已实施；V1.5 物化导出器已实施。本文档是 2026-08-28 数轮设计讨论的完整收敛，
覆盖协议、可行性核查结论、现状盘点与分期实施计划。
协议运行时合同见 `impl/protocols/materials.md`。

槽位声明落在 `impl/projects/<id>/materials.yaml`，**不**写进 `project.yaml`
（`project_config.py` 拒绝未知键）。V1 API 另含 `/api/material/get`（正文读取）。

## 0. 背景与目标

verifier 已支持远程部署（外网服务器 + SSH 隧道，见 `docs/external-eval-deployment.md`）。
远程形态下用户无法手改服务器文件，"资料怎么进系统"成为硬需求。资料的真实来源有三类：

1. 用户手头的领域知识：能力口径、字段口径表、业务规则、接口说明；
2. 系统调查产物：从业务源码/接口提炼的信息（endpoint 清单、trace 图、key index）；
3. 深度项目 judge 的运行依赖：如 client_search judge 的 authority key index，
   当前锚定业务源码，远程不可用——资料系统是这类 judge 走向远程可用的唯一通路。

目标：一套统一的资料管理机制——项目声明需求（槽位）、用户在页面上填充与管理、
调查产物经显式采纳进入生产、全链路可校验、远程环境明确降级而不假装全能。

## 1. 概念与边界

### 1.1 用户资料 vs 系统资产

| | 用户资料 | 系统资产 |
|---|---|---|
| 定义 | "评什么"：口径、规则、接口语义 | "怎么评"：evaluation.md、judge_boundary.md 等 |
| 管理者 | 用户，经资料页 CRUD | 项目维护者，随代码版本管理 |
| 治理 | 本协议 | 现有 assets + draft/promotion 体系 |

资料系统只覆盖左列。系统资产不开放页面编辑——用户改了"怎么评"，评测结果失去可比性。

### 1.2 资料的三种消费模式（挂在每份资料上，可组合，不做全局二选一）

| 模式 | 语义 | 确定性 | 适用 |
|---|---|---|---|
| binding | 注入指定角色的上下文；required=true 时缺失拒跑 | 高 | judge 评估依据（口径表、key index） |
| reference | 惰性；被 `material://` 引用才展开 | 高 | capability 预设引文档、case 级资料 |
| queryable | 暴露描述给带工具的角色，模型自主查询 | 低 | 大体量领域资料；限调查类角色，不用于 judge 核心依据 |

### 1.3 draft 与生产

调查产物属于 draft，不是资料。二者物理分离、形状不同、生命周期不同：

```
draft 区（现状已有，不动）              资料库（本协议新建）
draft/investigation/<role>/...    →    impl/data/<project>/materials/<id>/
引用形：路径+源哈希+摘要            采纳     自包含形：内容+manifest
锚定业务源码，离开代码即失效        (物化)    锚定内容哈希，哪里都有效
机器写入，哈希链保护                        用户/采纳动作写入，内容哈希封口
```

## 2. 协议

### 2.1 资料实体

```
impl/data/<project>/materials/<id>/
  manifest.json
  content.md            # 正文，仅纯文本（md/txt/yaml/json）
```

manifest 核心字段：

```yaml
id: policy-field-glossary        # 槽位资料 = slot_id；自由资料 = 系统生成
project: client_search
title: 字段口径表
media_type: text/markdown
sha256: <content.md 的内容哈希>    # 防篡改封口
size_chars: 18432
created_at: ...
provenance:
  source: user_upload | investigation | derived
  # investigation：附调查回执引用、source_revision、执行地（local/external）
  # derived：基于哪份调查产物人工修改
consumption:
  binding: { roles: [judge], required: true }   # 可选
  reference: true                               # 可选
  queryable: { enabled: false, description: "" } # 可选
```

引用 scheme：`material://<project>/<id>`，实现为 `CompositeContentResolver`
（`impl/core/context/resolvers.py`）的新 resolver。

### 2.2 槽位：项目声明需求，用户填充内容

槽位由项目维护者在 `impl/projects/<project>/materials.yaml` 声明，
随代码版本管理。终端用户不创建槽位；用户自发资料走自由区（reference/queryable）。
自由资料反复出现 → 项目契约演进，由维护者升格为槽位。

```yaml
materials:
  slots:
    - slot_id: field_glossary
      title: 字段口径表
      description: judge 判断字段映射对错的依据；应包含字段名、业务含义、合法取值
      required: true                    # 缺失时该项目评测 preflight 拒跑
      roles: [judge]
      fill: [upload]                    # 只能人提供
    - slot_id: api_schema
      required: false
      fill: [investigate_http, upload]  # 可通过隧道探测接口自动生成，也可人传
    - slot_id: prompt_templates
      fill: [source_bind, upload]       # 内容锚定业务源码某处
      source: business_source://app/prompts/   # 逻辑路径（path_contract），非绝对路径
```

填充方式语义：

- `upload`：人上传，任何环境可用；
- `investigate_http`：只需 HTTP 可达（如探测 /openapi.json），隧道环境可用；
- `source_bind`：内容锚定源码路径，代码可达的环境支持"从源码刷新"+ staleness 亮灯；
  代码不可达时降级为 upload，source 声明留作"这份资料该从哪来"的文档。

用户回答"必填怎么控制"：不靠用户起 id 再匹配——资料页把槽位渲染成清单
（必填标红、未填显示缺、附 description），点槽位上传即填充；评测启动时 preflight
检查必填槽位，缺失即拒跑并报槽位名。页面即需求清单，运行时即门禁。

### 2.3 生命周期与操作权限

调查产物（draft 区）对用户只暴露四个操作：**查看 / 重新调查 / 采纳 / 丢弃**。
不可编辑——手改破坏哈希链，registry 校验直接拒绝（现状已如此）。

**采纳 = 物化**（新增的导出动作，现状不存在）：

1. 前置校验：跑现有 staleness 校验，源文件哈希不符 → 拒绝导出（"先重新调查"）；
2. 物化：解析每个引用，把真实内容内联——evidence_refs 已带行号区间，读出行段快照；
   静态配置类工具依赖的配置文件（yaml）打成数据快照；
3. 封口：内容 + manifest 一体打包，内容哈希写入 manifest；
4. 出生证明：source_revision、调查回执、各源文件哈希作为声明性元数据保留。

采纳时允许编辑内容，但 provenance 强制降级 `investigation → derived`，
出生证明保留并标注"内容已非原样"。改了却冒充原装，机械上做不到。

### 2.4 两种哈希，两种职责（不混用）

| | 来源哈希（source_revision、源文件 sha256） | 内容哈希（资料自身 sha256） |
|---|---|---|
| 职责 | 防腐："代码变了没" | 防篡改："文件改没改" |
| 校验地点 | 只在代码所在地，由调查/导出流程执行 | 任何机器 |
| 服务器上 | 声明性元数据，展示不校验 | 上传时强制校验，不符拒收 |

校验链四步闭合：导出验源哈希 → 内容封口 → 上传验内容哈希 + manifest schema →
消费时资料 sha256 记入 trace/judge 元数据（对齐 config_hash/source_revision 的既有纪律，
保证"改了口径重跑分数变化"可归因到资料版本）。

### 2.5 信任分档（诚实展示，不假装能防伪造）

服务器无法证明上传的调查包出自未篡改的调查（无签名基础设施；内容哈希防无意破坏，
不防蓄意伪造）。分档标注、页面如实展示：

本机调查（链完整） > 外部调查（声明性） > derived（人工修改） > 纯上传。

多人对抗性使用出现前不上签名。

### 2.6 预算

binding/reference 展开时校验字符预算（复用 config 的 char budget 体系），
超预算报错让用户裁剪或转 queryable，不静默截断（对齐 struct_output"不放行假货"）。
单份资料上限沿用 capability 的 20000 字符量级，槽位可声明覆盖。

## 3. 环境模型

原则：**调查跟着代码走，产物作为文件旅行**。远程不承诺任何涉及本地源码的自动化。

| 能力 | 本机/内网（代码可达） | 远程服务器（仅隧道） |
|---|---|---|
| upload 填充 | ✅ | ✅（走 -L 隧道的前端上传） |
| investigate_http 填充 | ✅ | ✅（走 -R 隧道打 API） |
| source_bind 刷新 / 源码级调查 | ✅ 可一键刷新 + staleness | ❌ 显示"请在有代码的环境生成后上传" |
| 调查工具：API 类（search_api） | ✅ | ✅ |
| 调查工具：静态配置类（field_capability 等） | ✅ | ⚠️ 物化配置快照后可用 |
| 调查工具：重放类（case_route_replay、l4_replay） | ✅ | ❌ 永不支持（需执行业务代码） |
| staleness 检测 | 自动（哈希比对） | 声明性（展示"基于 revision X 生成于某日"，靠重新上传刷新） |

远程工作流：本地跑源码级调查 → 本地采纳/物化成自包含资料包 → 隧道前端上传进槽位 →
服务器验内容哈希、标 provenance=investigation(external) → 评测消费。
服务器全程不需要业务代码；`.env` 路径差异由逻辑路径（`business_source://`）吸收。

## 4. 可行性核查结论（2026-08-28 实测）

对 client_search 真实调查产物（`impl/projects/client_search/draft/investigation/attribute/`）核查：

1. **体积无障碍**：调查产物本体 ~64K（manifest 12K + trace 文档 40K）；
   吓人的 62M 是 `draft/.state` 循环迭代历史，不参与物化。
   对照预算：context 注入 10 万字符/prompt、attribute 终稿 16 万，选择性注入放得下。
2. **产物是三种形状的混合**，物化承诺按类型收缩：
   - 内容文档（trace .md/.mmd/.trace.json）：自包含，原样 travel ✅
   - evidence_refs（路径+symbol+行号区间+sha256+摘要）：可物化为行段快照 ✅
   - tool_requirements：API 类 ✅ / 静态配置类可物化数据快照 ⚠️ / 重放类不 travel ❌
3. **judge 工具查证**：
   - 重放类工具全部 `applicable_scenario: attr`，judge 从不执行业务代码；
   - llm_probe judge 零工具，远程完整可用（当前外网主场景无隐患）；
   - client_search judge 带查询型 authority 工具，其运行环境
     （`impl/core/authority_environment.py`）按 `business_source` scope 解析源码路径
     且默认 `staleness_policy=strict` → **现状远程跑不了**；
     出路即本协议：key index 物化进 `binding+required` 槽位。
4. **改动量**：物化是新增导出动作，现有 draft/investigation 的 schema、哈希链、
   writer 契约、promotion 全部不动。

## 5. 现状盘点

已有（直接复用）：

- draft/investigation 全家：manifest schema v2、LogicalPathRef+sha256、staleness、
  writer 契约（`impl/core/active_artifacts.py`、`path_contract.py`、`source_staleness.py`）
- portable artifact 写入器（规范化 JSON + 校验，`portable_artifact.py`）
- 用户数据 CRUD 模式（`case_pool.py` + `/api/case_pool/*` + artifact family）
- capability 预设 CRUD（2026-08-28 上线：`capability_store.py`、`/api/capability/*`、
  `frontend/materials.html`、`capability_map_store` family）——资料系统的第一个
  结构化资料类型；其 capability 字段将成为文档资料的第一个 reference 消费方
- context resolver 体系（`CompositeContentResolver`，可插 `material://`）
- 隧道部署形态（上传走 -L 隧道，无需新通道）

待建（全部为新增件）：

- 资料实体存储 + `materials_store` artifact family（内容哈希 + manifest schema 校验）
- 槽位声明解析（project.yaml `materials.slots`）+ preflight 门禁
- 资料页改造：槽位清单区（状态：已填/缺/过期）+ 自由资料区 + 待采纳区
- 上传 API（multipart 或 JSON 内联文本）
- `material://` resolver + binding 注入点（judge/mock prompt 组装处）
- 物化导出器（本地 CLI：读 draft 产物 → 内联 → 封包）
- investigate_http 填充器（探测 /openapi.json 等）

## 6. 分期实施计划

### V1：资料库 + 槽位 + 上传 + 门禁（最小闭环）

1. `impl/core/materials_store.py`（照 capability_store 模式）+ artifact family；
2. project.yaml 槽位声明解析（llm_probe 先不声明槽位；client_search 声明
   field_glossary 作为第一个 required 槽位）；
3. API：`/api/materials`（列表含槽位状态）、`/api/material/get|upload|delete`；
4. preflight：live_run/run_chain/batch 入口检查 required 槽位，缺失拒跑并报槽位名；
5. 资料页改造：槽位清单 + 自由资料 + 上传交互；
6. binding 注入：judge prompt 组装处按 roles 注入槽位资料，sha256 记入 trace。

验收：client_search 未填口径表 → 评测拒跑且报错指向资料页；填了 → judge 上下文
含口径表内容，trace 记录资料 sha；llm_probe 全链路回归不受影响。

### V1.5：物化导出器（已实施）

本地 CLI：`bash run.sh cli materialize --project X --role {attribute,judge,mock} [--apply] [--candidate] [--slot ID]`。

- 只内联 `business_source` 证据（远程看不到的就是这些文件）。
- 源哈希不符或源码不可达 → 整次导出拒绝。
- `--apply` 写入自由资料，provenance=`investigation` / `execution=local`。不绑定 judge。
- 上传通道复用 V1；要保留调查 provenance，拷贝 `impl/data/<project>/materials/<id>/`，不要经页面重新粘贴。

验收：本地物化 client_search 调查产物 → 同步资料目录到评测机 → 远程资料页能打开业务配置正文，服务器无业务代码。

### V2：source_bind 槽位 + investigate_http 填充

代码可达环境的"从源码刷新"+ staleness 亮灯；隧道环境的接口探测填充。

### V3：queryable + material 检索工具

第一份超预算资料出现时再做；限调查类角色。

### 明确不做

- 重放类工具远程化（物理不可行）
- 签名/防伪造（信任分档代替，对抗性使用出现前不做）
- PDF/Word 解析（只收纯文本，用户自行转换）
- 多租户隔离（与现部署形态一致）
- 终端用户自建槽位（契约归项目维护者）

## 7. 风险与开放问题

- **远程 staleness 盲区**：服务器无法感知业务代码变更，物化资料可能过期而不自知。
  缓解：页面醒目展示生成时间与 revision；未来可在本地调查 CLI 里加"对账提醒"。
- **binding 注入的 prompt 膨胀**：多个槽位同时 binding 到 judge 时可能挤占预算。
  缓解：注入时预算硬校验；槽位声明 roles 尽量收窄。
- **capability 预设与文档资料的引用打通**（capability 字段写 `material://`）放 V1 还是
  V2：倾向 V1 一并做（改动小，闭环价值大），实施时定。
- **采纳交互的落点**：远程模式下"采纳"发生在本地（导出即采纳）；本机模式下资料页
  是否直接提供"采纳"按钮，V1.5 实施时定。
