# Context Runtime 可接入骨架设计

日期：2026-07-19  
状态：待实施  
依据：`spec/adapter/context.md`  
选择方案：方案 B（可运行的公共 Runtime 骨架）

## 1. 背景

`spec/adapter/context.md` 定义了一套 Agno-first 动态上下文协议：公共层负责 ContextUnit 注册、治理、检索、加载和预算控制；项目层通过稳定知识配置及动态对象 Adapter 提供 `ContextUnitRecord`。

本次目标不是立即接入 QA、deerflow、client_search 等现有项目，而是先建设一套可运行、可测试、接入点明确的公共 Context Runtime。后续项目接入应主要完成配置、项目 `context_adapter.py` 和 Agno Tool 挂载，而不需要重写 Registry、Vector Index、Policy、Search 或 Load 主链。

仓库已有的 `ContextRecord`、`ContextRecordSummary` 和 `impl/core/context_store.py` 属于 LLM 调用审计系统，与本协议的 `ContextUnitRecord` 不是同一概念。本次不修改、不迁移，也不为二者建立兼容层。

## 2. 目标

本次骨架必须做到：

1. 落地且只公开 `ContextUnit`、`ContextUnitRecord` 两个领域 schema；
2. 提供可运行的 SQLite Registry 和本地持久化 Vector Index；
3. 提供 Embedding、Content Resolver、Adapter 等替换边界；
4. 实现稳定 ID 幂等注册、更新、失效和向量复用；
5. 实现 role + operation + project_id 驱动的确定性 Policy；
6. 实现多 query Search、批量 Load、二次鉴权和累计预算；
7. 提供可包装为 Agno Tool 的纯函数入口；
8. 提供 `python -m impl.context init --project <id>` 初始化命令；
9. 没有项目配置或项目 Context Adapter 时安全退出，不修改项目运行链；
10. 通过单元测试证明基础功能和隔离边界可工作。

## 3. 非目标

本次不实施：

- 任何现有项目的 ContextUnit 注册；
- 对 Mock、Judge、Attribute、Check 现有 Agent 或 Prompt 的修改；
- Agno Agent Tool 的实际挂载；
- 真实阿里 Embedding 网络请求或密钥配置；
- Prompt 上下文组装策略；
- Oracle Context、前向增加、后向消融等效果实验；
- 前端页面；
- 旧 `ContextRecord`、`context_store.py` 或 `impl/data/context_store` 的迁移；
- 项目回归配置修改。

## 4. 设计原则

### 4.1 最小公共概念

公共领域模型仅包含：

```python
@dataclass(frozen=True)
class ContextUnit:
    id: str
    name: str
    description: str
    content: str


@dataclass(frozen=True)
class ContextUnitRecord:
    id: str
    name: str
    description: str
    content: str | None
    content_ref: str | None
    project_id: str
    scope: str
    roles: tuple[str, ...]
    unit_type: str
    source_type: str
    status: str
    tags: Mapping[str, str]
```

Search 候选、注册结果、Policy 解析结果、索引条目和调试记录都是 Runtime 内部值或瞬时 JSON，不新增公共领域 schema。

### 4.2 安全默认值

- 未明确允许即不可检索、不可加载；
- 项目配置只能收窄公共 Policy，不能扩大权限；
- Search 与 Load 使用同一份 Run Policy；
- Load 必须重新读取权威 Record 并二次鉴权；
- 批量 Load 先整批校验，再返回内容，禁止部分泄漏；
- 未配置真实 Embedding Provider 时不得静默伪装成生产检索。

### 4.3 可替换但不过度抽象

第一版只为存在明确替换需求的组件定义端口：

- Registry；
- Vector Index；
- Embedding Provider；
- Content Resolver；
- Context Adapter。

SQLite 是默认本地实现。未来替换向量数据库不得改变 Runtime 对外的 register/search/load 接口。

## 5. 模块布局

新增公共包：

```text
impl/core/context/
├── __init__.py
├── models.py
├── errors.py
├── policy.py
├── ports.py
├── registry.py
├── vector_index.py
├── runtime.py
├── adapters.py
├── tools.py
└── bootstrap.py
```

职责如下：

| 模块 | 职责 |
|---|---|
| `models.py` | `ContextUnit`、`ContextUnitRecord` 及构造校验 |
| `errors.py` | 注册冲突、权限、预算、内容解析和配置错误 |
| `policy.py` | 公共与项目 Policy 限制性合并，生成单次 Run 的不可变策略 |
| `ports.py` | Registry、Vector Index、Embedding、Content Resolver 的 Protocol |
| `registry.py` | SQLite Record 权威存储和确定性过滤 |
| `vector_index.py` | SQLite embedding 持久化及过滤后相似度计算 |
| `runtime.py` | register、invalidate、search、load 主链 |
| `adapters.py` | 公共和项目 Context Adapter 协议及发现逻辑 |
| `tools.py` | 可包装为 Agno Tool 的 JSON 兼容 Search/Load 函数 |
| `bootstrap.py` | 数据目录、SQLite、Provider、Resolver 和 Runtime 的统一装配 |

新增 CLI 包：

```text
impl/context/
├── __init__.py
└── __main__.py
```

现有以下模块保持原样：

```text
impl/core/schema/context.py
impl/core/context_store.py
impl/frontend/context.html
impl/data/context_store/
```

## 6. 数据模型约束

### 6.1 ContextUnitRecord

构造或注册前必须满足：

- `id`、`name`、`description`、`project_id` 非空；
- `content` 和 `content_ref` 必须且只能存在一个；
- `roles` 至少包含一个非空角色；
- `scope`、`unit_type`、`source_type`、`status` 非空；
- tags 的键和值标准化为字符串；
- 模型值不可变，避免注册后调用方修改权限字段。

### 6.2 ContextUnit

仅在 Load 成功后构造，只有：

- `id`；
- `name`；
- `description`；
- 已解析的完整 `content`。

治理字段、向量分数、存储位置和生命周期不得进入 `ContextUnit`。

## 7. SQLite 存储

默认路径：

```text
impl/data/context_runtime/<project_id>/context.sqlite3
```

测试和调用方可显式传入其他根目录，避免测试污染仓库。

### 7.1 Registry 表

`context_units` 保存：

- ContextUnitRecord 的全部字段；
- 内部 `source_hash`；
- 内部 `description_hash`；
- 内部 `embedding_model`；
- 创建和更新时间；
- 索引状态。

roles 和 tags 以稳定 JSON 编码保存。Registry 是 Record 权威来源。

### 7.2 Vector 表

`context_vectors` 保存：

- ContextUnit ID；
- embedding model；
- `name + description` 对应的向量；
- 供 SQL 预过滤使用的 project、scope、status、unit_type 等派生字段；
- description hash 和更新时间。

Vector Index 不保存完整 content，不成为事实源。

### 7.3 事务

注册流程由 Runtime 控制：

1. 校验 Record；
2. 读取既有 Record 和 hash；
3. 判断新增、复用、治理字段更新或内容更新；
4. 必要时调用 Embedding；
5. 在同一 SQLite 事务中更新 Registry 与 Vector Index；
6. 提交后返回内部统计字典。

若 Registry 与 Vector Index 后续替换为不同后端，端口必须支持补偿或重建索引，但第一版不提前实现分布式事务。

## 8. 注册与向量复用

`register_context_unit(record)` 的行为：

- 新 ID：写入 Registry，并生成 embedding；
- 相同 ID 且来源、描述、模型均不变：直接复用；
- 只变更 roles、scope、status、tags 等治理字段：更新 Registry 和索引过滤字段，不重新 embedding；
- name 或 description 变化：重新 embedding；
- content/content_ref 指向的权威来源变化但描述不变：更新 Registry，不重新 embedding；
- embedding model 变化：只重建向量；
- `invalidate_context_unit(id)`：标记失效，并使其退出默认 Search 空间。

稳定 ID 冲突、跨项目复用同一 ID 等违反协议的情况必须显式报错。

## 9. Embedding Provider

定义批量接口：

```python
class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...
```

骨架提供：

1. 测试使用的确定性 Hash Embedding；
2. 未配置 Provider，调用 Search 或需要新向量时抛出明确配置错误；
3. 阿里 Embedding Provider 的独立扩展位置，但不实现网络访问。

确定性 Hash Embedding 只用于测试和本地结构验证，不能作为生产默认值。

## 10. Content Resolver

inline `content` 直接返回。

`content_ref` 通过 Resolver 链解析。第一版提供：

- `file://` Resolver，限制在显式允许的项目根目录内；
- 可注册 Resolver 的组合入口；
- 未知 scheme 明确拒绝；
- Resolver 返回后仍受 Load 预算约束。

RunTrace、LiveExchange、Agno Run 等专用 Resolver 只定义接入点，本次不连接现有存储。

## 11. Policy

一次 Run 根据 `project_id + role + operation` 解析一份不可变 Policy。内部字段至少包括：

- allowed/forbidden scopes；
- allowed/forbidden unit types；
- allowed statuses；
- mandatory IDs；
- candidate limit；
- load count limit；
- cumulative content budget；
- query count limit。

Policy 合并规则：

- forbidden 取并集；
- allowed 取交集；
- 数量和预算取更小值；
- mandatory 必须同时通过公共和项目权限；
- 项目层不能删除公共 forbidden，也不能提高公共预算。

Policy 不作为公共 schema 导出。

## 12. Search

入口：

```python
search_context_units(queries, policy) -> list[dict]
```

流程：

1. 校验 query 数量和非空值；
2. 由 Runtime 根据 Policy 生成固定过滤条件；
3. Registry/SQL 先过滤 project、role、operation、scope、type、status；
4. 为多个 query 生成 embedding；
5. 在允许候选中分别计算相似度；
6. 按 ContextUnit ID 融合去重；
7. 应用候选上限；
8. 仅返回 `id/name/description` 和必要的瞬时检索信息。

模型输入不能携带自定义 scope、role 或 project 过滤器，从而不能扩大 Search Scope。

## 13. Load

入口：

```python
load_context_units(ids, policy) -> list[ContextUnit]
```

流程：

1. 规范化并去重 ID；
2. 检查批量数量；
3. 从 Registry 重新读取全部权威 Record；
4. 使用与 Search 相同的 Policy 对整批 Record 二次鉴权；
5. 任意 ID 不存在、失效或越权时整批失败；
6. 解析 inline content 或 content_ref；
7. 检查累计内容预算；
8. 全部通过后构造 ContextUnit 列表。

该顺序保证猜测 ID、历史 ID 或混合合法/非法 ID 都不能产生部分内容泄漏。

## 14. Adapter 扩展

不修改现有只承担角色加载的 `ProjectAdapter`，也不在 `impl/projects/<project>/adapter.py` 中添加业务方法。

新上下文层定义独立协议：

```python
class ContextAdapter(Protocol):
    def iter_stable_context_units(self, context) -> Iterable[ContextUnitRecord]: ...
    def adapt_dynamic_context(self, event, context) -> Iterable[ContextUnitRecord]: ...
```

后续项目按需提供：

```text
impl/projects/<project>/context_adapter.py
```

公共协议对象 Adapter 与项目 Adapter 均只产出 `ContextUnitRecord`，再统一调用 Runtime 注册入口；不得直接写 Registry 或 Vector Index。

Adapter 发现失败、模块不存在表示“该项目尚未接入 Context Runtime”，不是项目运行错误。

## 15. CLI 初始化

命令：

```bash
python -m impl.context init --project <project_id>
```

行为：

1. 校验 project ID；
2. 装配项目 Runtime；
3. 加载公共稳定知识 Adapter；
4. 尝试发现项目 `context_adapter.py`；
5. 遍历稳定 ContextUnitRecord 并统一注册；
6. 输出新增、复用、更新、失效、向量重建和错误统计。

如果没有公共记录且项目 Adapter 不存在，命令应成功退出并明确输出“项目尚未配置上下文单元”，不得修改项目文件或项目运行配置。

## 16. Agno 接入预留

本次提供 JSON 兼容的 guarded Tool 函数：

```python
search_context_units_tool(...)
load_context_units_tool(...)
```

Tool 函数只能接收 queries 或 ids；project、role、operation 和预算由 Runtime Context 注入，不能由模型参数覆盖。

同时提供构造 `context_debug` 字典的辅助函数，字段包含：

- policy；
- mandatory IDs；
- search queries；
- candidate IDs；
- loaded IDs；
-内容预算；
- content hashes。

本次不修改现有 Agno Run metadata。后续挂载时将该字典合并到 Agno Run metadata，而不新增审计领域对象。

## 17. 测试策略

单元测试至少覆盖：

1. `content/content_ref` 严格二选一；
2. 模型字段不可变；
3. 稳定 ID 幂等注册；
4. 内容变化但描述不变时复用 embedding；
5. 描述或模型变化时重建 embedding；
6. 仅治理字段变化时不重算 embedding；
7. 状态失效后退出 Search；
8. 多 query 融合、去重与候选上限；
9. project、role、operation、scope、type、status 隔离；
10. Search 和 Load 使用同一 Policy；
11. 猜测禁止 ID 无法加载；
12. 批量 Load 整批失败且不泄漏合法子集；
13. inline content 和允许根目录内的 `file://` content_ref；
14. 未知或越界 content_ref 被拒绝；
15. 累计内容预算；
16. 未配置 Adapter 时 CLI 安全退出；
17. 现有 `ContextRecord/context_store` 测试和调用行为不受影响。

测试使用临时目录和确定性 Embedding，不写入 `impl/data/context_runtime`。

## 18. 验收标准

骨架完成必须满足：

- 新 Context Runtime 测试全部通过；
- 现有相关 core 测试无新增失败；
- CLI 无项目 Adapter 时可安全运行；
- 未产生任何现有项目的 ContextUnit 数据；
- 未修改任何 `impl/projects/<project>/` 文件；
- 未修改 Mock、Judge、Attribute、Check 的执行链；
- 未访问外部 Embedding 服务；
- 旧 `ContextRecord` 和旧 context store 保持原样；
- 后续项目接入只需提供配置/Adapter、真实 Provider，并挂载 Tool。

## 19. 后续接入顺序

骨架完成后，建议独立变更按以下顺序推进：

1. 选择一个最小项目，编写稳定知识配置和 `context_adapter.py`；
2. 配置真实 Embedding Provider，执行人工 init；
3. 将 guarded Search/Load 挂入单个角色的 Agno Run；
4. 写入 `context_debug` metadata；
5. 在固定失败 case 上比较 Current 与 Oracle Context；
6. 验证角色隔离和未见 case 无退化后，再扩大项目和角色范围。

本次设计不提前实施上述步骤。
