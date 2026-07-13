---
name: evals
description: verifier 业务测评系统生命周期管理 skill。核心职责是新项目接入：从 user-side project.yaml 出发，动态发现协议要求，scaffold 项目骨架，填充并验证到纳入回归。也覆盖归因优化、代码审查、回归测试等阶段的调度。
---

# Evals Skill

verifier 项目级 skill，管理业务测评项目的生命周期。和 verifier 强耦合，**引用工程能力而非自建**——工程有的脚本/模板只引用，工程缺的才补。

## 阶段路由

根据用户意图判断当前阶段，加载对应流程：

| 用户意图 | 阶段 | 执行 |
|---------|------|------|
| "新增项目"/"接入项目"/"onboard" | 接入 | 走本文件的「项目接入主流程」 |
| "归因优化"/"draft"/"attribute" | 归因优化 | 调用 attribute skill 的 draft 机制 |
| "代码审查"/"标准化"/"check" | 审计 | 调用 `agents/specialized/check.md` |
| "回归测试"/"check1" | 回归 | 执行 `impl/checklist/check1.sh` |

## 项目接入主流程

新项目接入分 11 步，按序执行，每步完成后汇报用户确认再进入下一步。

### 三层架构（接入即补项目扩展层）

verifier 分三层（见 `spec/adapter.md`），接入时**只补项目扩展层**：

| 层 | 位置 | 职责 | 接入时是否动 |
|----|------|------|------------|
| 通用层 | `impl/core/<role>.py` | 可复用工具函数 | ❌ 不动 |
| 协议层 | `impl/core/<role>_protocol.py` | `_XxxProtocol` 主流程（模板方法，禁止覆盖）+ `ProjectXxx` 扩展点定义 | ❌ 不动 |
| 项目层 | `impl/projects/<project>/<role>.py` | 实现 `ProjectXxx` 定义的扩展点（`@abstractmethod`） | ✅ 只动这里 |

**接入 = 在项目层实现协议层定义的扩展点**。协议层已锁定主流程和扩展点清单，项目层只填空，不改流程。项目层需要通用能力时调用通用层函数，不复制逻辑。

### 通用发现规则（贯穿全程）

**不写死方法名/基类文件名**。每个角色要实现什么，从协议层现场发现：
- 角色基类：`impl/core/<role>_protocol.py` 中的 `Project<Role>` 类（操作层扩展点基类）
- 必须实现项：该类中被 `@abstractmethod` 标记的方法（协议层定义的扩展点）
- adapter 加载方法：中转站 `ProjectAdapter` 的 `@abstractmethod`，命名规范 `_load_<role>`
- live_schema 导出：按命名规范（`REQUEST_SCHEMA` / `EXTRACT_OUTPUT_SCHEMA` / `SCENARIO_ENUM` / `check`）

协议演进（新增抽象方法、新增角色、基类改名）时，scaffold 和 verify 脚本按搜索路径现场读取，自动覆盖，无需改 skill。

### Step 0: 信息收集
- **输入**：`verifier/projects/<project>/project.yaml`（用户提供）
- **操作**：理解业务场景、API 配置、`common.ready` 声明
- **验收**：能正确读取 project.yaml 关键字段
- **边界**：project.yaml 是唯一事实源，skill 不自动生成
- **其他**：live没有启动时请根据yaml指引启动live背后的业务系统

### Step 1: 跑 scaffold 生成骨架
- **命令**：`bash run.sh python scripts/scaffold_project.py --project <id>`
- **产出**：`impl/projects/<id>/` 下 live/mock/tools/judge/attribute/adapter/live_schema/schema 的 stub
- **验收**：8 个文件生成成功
- **说明**：stub 只含 `@abstractmethod` 的 `raise NotImplementedError`，可选扩展点不生成，项目按需覆盖

### Step 2: 冻结 live_schema（不变量）
- **输入**：project.yaml 的 `common.api` + 业务需求文档
- **操作**：填充 `schema/__init__.py` 的 dataclass + `live_schema.py` 的 SCENARIO_ENUM/check
- **验收**：`LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)` 可实例化
- **参考**：`impl/projects/QA/live_schema.py`（最简样板）

### Step 3-8: 填充各角色 stub
按顺序填充 live → mock → tools → judge → attribute → adapter：
- 每步的搜索路径：`impl/core/<role>_protocol.py` → `Project<Role>` 的 `@abstractmethod`
- 参考现有最简项目：`impl/projects/QA/<role>.py`
- tools.py 可用协议默认实现（空实现即可）
- judge/attribute 只搭基础设施（实现 build_context），质量优化走 attribute skill draft
- adapter 的 `_load_*` 由 scaffold 已生成，确认齐全即可

### Step 9: 验证（门禁）
四项硬门禁，全部通过才算接入完成：
```bash
bash run.sh python scripts/check_adapter_compliance.py --project <id>
bash run.sh python scripts/verify_protocol_compliance.py --project <id>
bash run.sh cli mock-check --project <id>
bash run.sh cli run-chain --project <id> --input '<REQUEST_SCHEMA 形状的 JSON>'
```
- `check_adapter_compliance`：adapter 静态合规（只允许 `_load_*`，禁止业务方法）
- `verify_protocol_compliance`：协议符合性探针（角色发现 + 实例化校验，协议演进自动卡）
- `mock-check`：mock 数据 schema 校验
- `run-chain`：单链跑通 live → judge → attribute → check

> **已知过渡期缺口**：core 的 `trace_from_live_result` 仍调 `adapter.to_run_trace()`，该方法只在旧版 `ProjectAdapter` / `LegacyProjectAdapter` 上。纯新协议 `ProjectAdapter`（v2）暂未提供该委托，导致纯新协议项目的单链 `run-chain` 会在 `to_run_trace` 处 AttributeError。在 core 完成新协议迁移前，接入项目可暂用 `LegacyProjectAdapter`（spec/adapter.md 迁移过渡期允许）；core 迁移完成后改回 `ProjectAdapter`。这是 core 层待办，不在接入 skill 边界内。

### Step 10: mock 固化
- **操作**：遍历 SCENARIO_ENUM，调 mock_build_intent 生成 case，写入 `impl/data/<project>/mock_cases.json`
- **验收**：mock_cases.json 存在且 mock-check 通过

### Step 11: 纳入回归
- **操作**：更新 `impl/checklist/check1.py` 的 CONFIG，加入新项目
- **验收**：check1 能识别新项目

## 项目侧引用清单

区分两类依赖，避免重复造轮子产生两套口径：

**引用工程（不复制不重写，口径以工程为准）**：
- `scripts/scaffold_project.py` — 动态生成项目骨架
- `scripts/verify_protocol_compliance.py` — 协议符合性探针
- `scripts/check_adapter_compliance.py` — adapter 合规检查
- `bash run.sh cli mock-check` — mock 数据 schema 校验
- `bash run.sh cli run-chain` — 单链跑通
- `templates/new_project/adapter.md` — 模板用法说明

**skill 自带**：无。脚本和模板都在工程侧，skill 只引用。

## 关键边界

- **只改 `impl/projects/<project>/`**：不碰 core、protocols、其他项目、前端
- **新项目用 `ProjectAdapter`**：不用 `LegacyProjectAdapter`（存量项目过渡用）
- **接入不碰算法层质量**：judge/attribute 只搭基础设施，质量优化通过 attribute skill 的 draft
- **project.yaml 是唯一事实源**：用户提供，skill 不自动生成
- **不写死方法名/基类文件名**：靠命名规范 + 搜索路径动态发现，协议演进自动覆盖

## Specialized agents

- `agents/specialized/attribute-analyzer.md`：归因质量审查
- `agents/specialized/check.md`：代码质量审查、标准化、协议对齐

## 验收清单

见 `references/onboarding_acceptance.md`，接入完成后逐项跑过。
