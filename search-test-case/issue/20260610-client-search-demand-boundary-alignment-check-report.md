# 20260610 client_search 最新需求与边界对齐审核报告

## 背景

用户更新了 `demand.md` 和 `projects/client_search/judge_boundary-template.md` 后，要求按 `check.md` 全面审核当前 `impl`：不能只看输出文档，要检查 judge/check/adapter/frontend/pipeline 的产生机制是否与最新需求一致，并尽量修复差异。

本次重点边界：client_search judge 的核心不是机械比对 prompt/config 或历史标准答案，而是判断 parser 输出的 `conditions/query_logic` 是否能在依赖 ES/下游客户搜索能力内检索到用户想要的客户。上游 ES 字段、枚举、实际数据缺失属于系统外能力边界；模型、prompt、配置、项目代码、字段映射、值归一化、后处理、pipeline 等当前系统可优化部分仍是可评价错误。

## 审核发现的问题

1. judge source references 不够通用
   - 发现：`impl/core/judge.py` 原先只固定读取 `source_readme/source_config/source_prompt/source_judge_boundary`，即使 `project.yaml` 增加原业务字段/枚举/映射/规则文件，judge 也拿不到。
   - 风险：最新边界要求“数据库信息从原项目配置/枚举值文件中获取”，但实际 judge 只能看到静态摘要，容易退化成 prompt/config 形态比对。
   - 处理：改为动态加载所有 `documents` 中 `source_*` 文档，避免 generic core 硬编码 client_search 文档类型。

2. 原业务配置文件没有进入项目协议
   - 发现：`impl/projects/client_search/project.yaml` 未列出原业务项目的 `field_definitions_args.yaml`、`field_enums_args.yaml`、`value_mappings_args.yaml`、`enhanced_rules_args.yaml`。
   - 风险：judge/check 无法稳定追踪 ES/search 字段、枚举、值映射和增强规则的真实来源。
   - 处理：补充上述 `source_*` 文档，并修正相对路径层级，确保 check 能验证文件存在。

3. trace 中缺少外部边界来源提示
   - 发现：下游搜索 payload/result 已进入 trace，但原业务字段/枚举配置文件路径没有进入 client_search 项目字段。
   - 风险：attribute/check 追踪边界时只能看 judge prompt 输入，难以从当前 trace 看出判断依据来自哪些外部配置。
   - 处理：在 client_search adapter 中加入 `external_boundary_sources.config_paths`，把原业务 config source 路径写入 `RunTrace.project_fields`。

4. client_search 文档还没有完全表达“内部实现不是绝对标准”
   - 发现：`evaluation.md`、`judge.md`、`checklist.md` 已说明下游不可用时要做 ES 查询语义等价判断，但对“prompt、生成配置摘要、项目代码、后处理、pipeline 可能出错，不能作为绝对标准”的表达不够明确。
   - 风险：judge 容易把内部 prompt/config 中间形态当最终答案。
   - 处理：同步更新三份项目文档，明确原业务字段/枚举/值映射/规则配置是能力边界证据，prompt/config 摘要和项目内部实现只是辅助证据。

5. check runtime 只做协议形状检查，不会抓住最新边界问题
   - 发现：`.claude/skills/evals/agents/specialized/check.md` 对机制审查要求较完整，但 `impl/core/check.py` 运行时缺少两类检查：
     - `source_*` 文档是否真的存在；
     - 下游不可用时 judge 是否误标 `result_set_verified=true`，或是否缺少 ES 查询语义等价判断标记。
   - 风险：文档看起来对齐，但 batch/check 仍可能放过关键边界错误。
   - 处理：在 `impl/core/check.py` 增加项目 source 文档存在性检查和 downstream boundary consistency 检查。

## 已修改位置

- `impl/core/judge.py`
  - 新增 `_source_documents(spec)`。
  - judge prompt 中的 `project_source_references` 改为动态包含所有 `source_*` 项目文档。

- `impl/projects/client_search/project.yaml`
  - 增加：
    - `source_field_definitions`
    - `source_field_enums`
    - `source_value_mappings`
    - `source_enhanced_rules`
  - 修正相对路径为可从 `impl/projects/client_search` 正确解析到原业务项目。

- `impl/projects/client_search/adapter.py`
  - 增加 `external_boundary_sources.config_paths`，把原业务配置来源写入 trace。

- `impl/projects/client_search/judge_boundary_protocals.md`
  - 明确原业务字段定义、枚举、值映射、增强规则是外部/上下游能力边界的重要来源。

- `impl/projects/client_search/evaluation.md`
  - 明确 prompt、生成配置摘要、项目代码、后处理、pipeline 是内部实现证据，不是绝对标准。

- `impl/projects/client_search/judge.md`
  - 明确边界依据优先级：真实 ES/下游语义与原业务配置优先，prompt/config 仅辅助。

- `impl/projects/client_search/checklist.md`
  - 增加 judge 必须读取原业务字段/枚举/值映射/规则 source documents 的检查项。

- `impl/core/check.py`
  - 增加 `source_*` 文档存在性检查。
  - 增加 downstream search 与 judge boundary_decision 的一致性检查。

## 验证结果

### 静态验证

```bash
python -m compileall -q impl
python -m impl.cli projects
```

结果：通过，项目列表包含 `QA` 和 `client_search`。

### source documents 加载验证

```python
from impl.core.project_loader import load_project
from impl.core.judge import _source_documents
spec = load_project('client_search')
docs = _source_documents(spec)
print({key: len(value) for key, value in docs.items()})
```

结果确认 judge 能加载：

```json
{
  "source_config": 1113,
  "source_enhanced_rules": 251731,
  "source_field_definitions": 132481,
  "source_field_enums": 5172,
  "source_judge_boundary": 865,
  "source_prompt": 3327,
  "source_readme": 3249,
  "source_value_mappings": 5347
}
```

### batch/check 验证

执行 `client_search` 前 2 条 mock case 的 live batch：

```json
{
  "total": 2,
  "verdicts": ["correct", "correct"],
  "downstream_statuses": ["unavailable", "unavailable"],
  "external_source_keys": [
    ["source_enhanced_rules", "source_field_definitions", "source_field_enums", "source_value_mappings"],
    ["source_enhanced_rules", "source_field_definitions", "source_field_enums", "source_value_mappings"]
  ],
  "check_passed": true,
  "check_issues": []
}
```

说明：8081 下游客户搜索仍不可用，但 trace 保留 downstream payload/status，并且 check 确认 judge 未伪装结果集验证。

### 按 `projects/client_search/start.md` 重启/验证

- 8000 业务服务已启动，当前监听 PID：`99298`。
- 8020 verifier 服务健康检查通过：`{"status":"ok"}`。
- 已调用 reindex：

```json
{
  "success": true,
  "started": true,
  "message": "索引重建已提交后台执行",
  "reload_running": true,
  "last_reload_error": null,
  "last_reload_result": null
}
```

重启后单条 live smoke：

```json
{
  "status": "ok",
  "downstream_status": "unavailable",
  "external_source_keys": ["source_enhanced_rules", "source_field_definitions", "source_field_enums", "source_value_mappings"],
  "verdict": "correct",
  "result_set_verified": false,
  "check_passed": true,
  "check_issues": []
}
```

## 仍然存在的边界/限制

1. 8081 下游客户搜索服务本地仍不可用
   - 当前 impl 已按边界要求保留 `downstream_search.status=unavailable`、payload 和错误，不会声称真实结果集已验证。
   - judge 只能基于 ES 查询语义、字段/枚举/操作符语义和业务意图做等价判断。

2. 原业务 source 文档较大
   - `source_enhanced_rules` 和 `source_field_definitions` 较大，但当前 smoke/batch 能跑通。
   - 后续如果 LLM 上下文或成本成为问题，应在项目 adapter 或 project docs 层生成稳定的字段/枚举摘要，而不是回退到只读 prompt/config。

3. attribute 的“可执行局部链路验证”仍主要依赖 trace 和 LLM 分析
   - 当前 check 文档已经要求归因必须给出 evidence_chain、trace_analysis、suspected_locations、verification_steps、patch_direction。
   - runtime 尚未为每个项目自动执行业务函数级验证脚本；这属于更高阶能力，未在本次 client_search judge boundary 对齐中强行扩展。

## 结论

本次已按 `check.md` 把最新 client_search judge boundary 从文档要求推进到运行机制：judge 能读取原业务字段/枚举/值映射/规则 source docs，trace 能暴露外部边界来源，check 能发现 source 缺失和下游结果集验证状态错误。当前验证通过；8081 不可用时仍按要求标记 `result_set_verified=false` 并要求 ES 查询语义等价判断。
