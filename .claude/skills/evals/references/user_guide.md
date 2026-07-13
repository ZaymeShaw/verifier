# Evals Skill 使用指引 — 新建项目

本文档面向**想要接入一个新业务项目到 verifier 评测系统**的用户。按顺序走完 6 个阶段，项目即可纳入评测回归。

---

## 前置认知

**verifier 评测系统是什么**：把业务系统的输入输出"具现化"成 trace，让 judge 判定对错、attribute 定位根因。每个项目接入后，能跑 `live → judge → attribute → check` 全链路。

**两层项目目录**（重要，别搞混）：
- `verifier/projects/<project>/` —— **用户侧**：你写业务资料、需求文档、project.yaml 索引
- `verifier/impl/projects/<project>/` —— **实现侧**：AI 生成和填充的代码（adapter/live/judge/attribute 等）

**接入流程的角色分工**：
- **你（用户）负责**：写业务资料、确认场景、验收
- **evals skill 负责**：scaffold 骨架、指导填充、跑门禁

---

## 阶段 1：准备用户侧资料

在 `verifier/projects/<project_id>/` 下准备以下文件（参考 `projects/QA/`）：

### 1.1 project.yaml（必需，唯一事实源）

```yaml
project_id: <你的项目id>          # 如 my_project
name: <项目显示名>
description: <这个项目测什么>

common:
  source:
    repo:                          # 业务系统源码路径（可选，供 AI 分析参考）
  api:
    base_url:                      # 业务系统 API 地址（如 http://localhost:8000）
    endpoint:                      # API 端点（如 /api/v1/xxx）
    method: POST
    timeout: 60
  start:
    command:                       # 启动命令（如 ./start.sh）
  ready:                           # 数据流模式（关键决策，见下方说明）

extra: {}
```

**`common.ready` 怎么填**（决定数据流路径）：
- `ready: []` —— 业务系统有真实服务可调，output 由 live 真实调用产生；reference 由 judge 生成
- `ready: [output, reference]` —— 评估已产出的数据（如上传数据集），case 自带 output 和 reference
- `ready: [reference]` —— output 走真实调用，但参考答案由你提供

### 1.2 业务资料（按项目类型）

至少提供一份**业务需求文档**，说明：
- 业务系统做什么、API 输入输出长什么样
- 评估的场景分类（如"单条件查询"、"多条件组合"、"边界值"等）
- 判定对错的业务标准

参考 `projects/QA/QA-demand.md`、`projects/client_search/readme.md`。

---

## 阶段 2：触发 evals skill 接入

在 Claude Code 里对 evals skill 说：

> "接入一个新项目 `<project_id>`"

evals skill 会按 SKILL.md 的 11 步主流程执行。**每步完成后会向你汇报，你确认后再进入下一步**。

---

## 阶段 3：scaffold 生成骨架（skill 自动）

skill 跑：
```bash
bash run.sh python scripts/scaffold_project.py --project <project_id>
```

会在 `impl/projects/<project_id>/` 下生成 8 个文件：
- `adapter.py` / `live.py` / `mock.py` / `tools.py` / `judge.py` / `attribute.py`
- `live_schema.py` / `schema/__init__.py`

每个文件是带 docstring 的 stub（方法签名 + 协议基类的语义契约 + `raise NotImplementedError`）。

---

## 阶段 4：冻结 live_schema（关键决策点）

这是接入的**核心决策**——live_schema 定义"业务系统在评测侧的契约"，后续所有代码依赖它。

参考 `spec/live.md` 的原则：**live_schema 是对业务系统的描述，业务系统是客观事实**。

### 4.1 填充 `schema/__init__.py` 的 dataclass

- `<Prefix>Request` —— 真实 API 请求体形状（字段从业务 API 文档来）
- `<Prefix>ExtractOutput` —— 真实 API 响应形状（看一两条真实响应来定）

### 4.2 填充 `live_schema.py`

- `SCENARIO_ENUM` —— 从业务需求文档抽取的评估场景列表
- `READY` —— 与 project.yaml 的 `common.ready` 一致
- `check` —— `LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)`

参考 `impl/projects/QA/live_schema.py`（最简样板）。

---

## 阶段 5：填充各角色 stub（skill 指导）

skill 按 live → mock → tools → judge → attribute → adapter 顺序指导填充。

每个 stub 方法都带协议基类的 docstring（说明该扩展点的定位/目标/参数），按 docstring 填业务逻辑即可。

**关键原则**：
- `judge/attribute` 只搭基础设施（实现 `build_context` 返回必要上下文），**质量优化走 attribute skill 的 draft 机制**，接入阶段不做
- `tools.py` 可用协议默认实现（空实现）
- `adapter.py` 的 `_load_*` 由 scaffold 已生成，确认齐全即可

参考现有最简项目 `impl/projects/QA/` 各角色实现。

---

## 阶段 6：验收（硬门禁）

skill 跑 4 项门禁命令，全部通过才算接入完成：

```bash
# 1. adapter 静态合规（只允许 _load_*，禁止业务方法）
bash run.sh python scripts/check_adapter_compliance.py --project <id>

# 2. 协议符合性探针（角色齐全 + 实例化校验）
bash run.sh python scripts/verify_protocol_compliance.py --project <id>

# 3. mock 数据 schema 校验
bash run.sh cli mock-check --project <id>

# 4. 单链跑通（live → judge → attribute → check）
bash run.sh cli run-chain --project <id> --input '<REQUEST_SCHEMA 形状的 JSON>'
```

通过后：
- **mock 固化**：生成 `impl/data/<id>/mock_cases.json`
- **纳入回归**：更新 `impl/checklist/check1.py` 的 CONFIG

---

## 已知过渡期缺口（可能遇到）

1. **纯新协议 `ProjectAdapter` 的 run-chain 失败**：core 的 `trace_from_live_result` 仍调 `adapter.to_run_trace()`（旧方法），纯新协议 ProjectAdapter 没该方法。**过渡期解法**：adapter 暂用 `LegacyProjectAdapter`（spec 允许）；core 完成迁移后改回。
2. **marketting-planning 等存量项目**：工作目录里有未完成的迁移改动，不影响新项目接入。

---

## 速查清单

| 阶段 | 你要做什么 | skill 做什么 |
|------|-----------|-------------|
| 1 | 写用户侧 project.yaml + 业务资料 | — |
| 2 | 对 skill 说"接入项目 X" | 启动主流程 |
| 3 | — | scaffold 生成 8 个 stub |
| 4 | 确认场景分类、API 形状 | 指导冻结 live_schema |
| 5 | 确认每个角色的业务逻辑 | 指导填充 stub |
| 6 | 确认验收结果 | 跑 4 项门禁 + mock 固化 + 纳入回归 |

参考文档：
- `spec/evals.md` — evals skill 设计方案
- `spec/live.md` — live 模块和 live_schema 的设计原则
- `spec/adapter.md` — 协议分层和 adapter 中转站设计
- `impl/projects/QA/` — 最简接入样板
