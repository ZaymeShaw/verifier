# 通用 LLM 上下文追踪体系方案

## 核心定位

**一个独立的、通用的上下文追踪体系**，不绑定任何特定 agent，覆盖整个 LLM 调用链路。新 schema、新 API、新前端都是独立的，但设计上保证泛化通用——任何 agent、任何项目、任何未来的扩展都自动接入，零改动。

---

## 1. Schema：`ContextRecord`（通用记录，不绑定 agent 语义）

新增 `impl/core/schema/context.py`：

```python
@dataclass
class ContextRecord:
    """通用 LLM 上下文追踪记录。不绑定任何特定 agent 的字段结构。"""
    record_id: str              # 主键，调用时生成
    trace_id: str               # 关联的 run trace（定向追踪主键之一）
    project_id: str             # 项目标识
    caller: str                 # 调用方标识："judge"|"attribute"|"live"|"cluster"|"check"|...（开放字符串，非枚举）
    messages: List              # 完整 llm messages
    response: Any               # LLM 原始返回（Any，兼容 JSON/纯文本/未来形态）
    created_at: str             # ISO8601 时间戳
    prompt_size: int            # system+user 总字符数（用于预算审计）
    llm_model: str = ""         # 调用的模型标识
    elapsed_ms: int = 0         # 调用耗时
    error: Optional[str] = None # 调用失败时的错误信息
```

**泛化性体现**：
- `caller` 是开放字符串而非枚举 → 新增 agent 不需要改 schema
- `messages` 是message列表 → 兼容任何 openai协议输入
- `response` 是 llm输出 → 兼容 JSON、纯文本、未来多模态
- 不预设"judge 的 context 有哪些字段" → schema 与 agent 语义解耦

---

## 2. 拦截点：LlmClient 唯一出口（不改任何 agent 代码）

所有 agent 调 LLM 都走 `LlmClient.complete_json()`。在这一层统一拦截记录：

```python
# impl/core/llm_client.py
class LlmClient:
    def __init__(self, ..., context_tracker=None):
        self._context_tracker = context_tracker
        self.role = role          # 已有：构造时传入 "judge"/"attribute"/...
        self.project_id = project_id  # 已有：构造时从 spec 取

    def complete_json(self, system, user, trace_id=None, **kw):
        # 调用前记录
        record = ContextRecord(
            record_id=...,
            trace_id=trace_id or "",
            project_id=self.project_id,
            caller=self.role,       # 天然就是调用方标识，无需 agent 传
            system_prompt=system,
            user_prompt=user,
            ...
        )
        # 调 LLM
        response = self._call(...)
        record.response = response
        record.elapsed_ms = ...
        if self._context_tracker:
            self._context_tracker.save(record)
        return response
```

**泛化性体现**：
- 拦截点在唯一出口，所有 agent 自动接入
- `caller` 来自 `self.role`（构造时已传），agent 调用时无需多传任何参数
- 新增 agent 只要走 `LlmClient`，上下文就被记录，零改动
- agent 代码不被调试逻辑污染

---

## 3. 存储：复用现有模式，三级目录

`impl/core/context_store.py`，参照 `case_pool.py` 的 JSON 文件读写模式：

```
impl/data/context_store/{project_id}/{trace_id}/{caller}-{timestamp}.json
```

按 项目 → 用例 → agent 三级目录组织。一次 LLM 调用一个文件。

接口：
```python
def save_context(record: ContextRecord) -> str
def load_contexts_by_trace(project_id, trace_id) -> List[ContextRecord]
def load_context(project_id, trace_id, caller) -> Optional[ContextRecord]
def list_recent_contexts(project_id, limit=20) -> List[ContextRecordSummary]
```

**泛化性体现**：存储路径按 `project_id/trace_id/caller` 组织，这三个维度都是通用标识，不绑定具体 agent。

---

## 4. API：通用查询，caller 是开放参数

新增 `impl/server/routes.py` 路由：

- `GET /api/context/{trace_id}` — 某次 trace 的完整上下文链（judge→attribute→...，按 created_at 排序）
- `GET /api/context/{trace_id}/{caller}` — 某次 trace 中某个 agent 的上下文
- `GET /api/context/summary?project_id=X&caller=Y&limit=20` — 最近 N 条记录摘要（不含 prompt 全量，只含 record_id/caller/project_id/trace_id/size/created_at）

**泛化性体现**：
- `{caller}` 是路径参数，不是枚举校验 → 新 agent 自动可查
- API 语义是"查询上下文记录"，不是"查询 judge 的 prompt"
- 不需要为新 agent 加新路由

---

## 5. 前端：独立新页面，index 加引用

新增 `impl/frontend/context.html`，专门做 LLM 上下文追踪可视化：
- 按 `project_id` / `trace_id` / `caller` 三级筛选
- 时间线展开某次 trace 的完整调用链（judge→attribute→...）
- 点击单条记录展开 system/user prompt 全文 + response
- prompt_size 可视化（预算审计）

在 `impl/frontend/index.html` 加引用入口，跟现有 live/summary 并列，不混进现有页面。

**泛化性体现**：
- 页面渲染逻辑只认 `ContextRecord` 结构，不关心是哪个 agent
- 新 agent 的记录自动出现在时间线和过滤选项里
- 跟 `report/api-check/` 的独立报告页模式一致，每个关注点一个独立页面

---

## 三个"不"——泛化性的核心保证

1. **Schema 不绑定特定 agent 语义**：`ContextRecord` 字段都是通用维度（trace_id/project_id/caller/prompt/response），不预设 agent 内部结构。
2. **API 不硬编码 agent 枚举**：`caller` 是开放字符串路径参数，不是固定枚举。
3. **拦截点不散落在 agent 代码里**：只在 `LlmClient` 出口拦截一次，agent 零改动。

## 定向追踪能力

靠已有的三元组定位，不引入新概念：
- `trace_id` → 某次 run 的完整上下文链
- `trace_id + caller` → 某次 run 中某个 agent 的上下文
- `project_id + caller` → 某项目所有某 agent 的调用历史
- `project_id + limit` → 某项目最近的上下文记录

## 信息密度损失预估

- 拦截在 LLM 出口：**0 损失**（完整 system/user/response 都记录）
- 存储为文件：单次调用一个文件，无截断，**0 损失**
- API summary 不含 prompt 全量：仅摘要接口省略，明细接口全量返回，**0 损失**
- 前端展示：prompt 全文可展开，**0 损失**

## 落地步骤

1. `impl/core/schema/context.py` — 定义 `ContextRecord`
2. `impl/core/context_store.py` — 文件存储读写
3. `impl/core/llm_client.py` — 在 `complete_json` 出口加拦截
4. `impl/server/routes.py` + `service.py` — `/api/context/*` 路由
5. `impl/frontend/context.html` — 独立可视化页面
6. `impl/frontend/index.html` — 加引用入口
7. 跑 api-check 验证不破坏现有链路