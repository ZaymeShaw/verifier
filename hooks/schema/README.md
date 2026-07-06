# Schema Hook

`hooks/schema` 是 schema 传播审计 hook。它的目标不是替代业务测试，而是全局扫描代码，发现：

- `impl/core/schema` 中声明了 schema，但 runtime 没有使用；
- 核心边界函数仍然用 `Dict[str, Any]` / `Any` / 缺失类型注解传播 trace、judge、attribute、view、table 等概念；
- schema-like 函数的输入和输出没有显式复用 schema 数据类；
- 新 schema 类没有从 `impl.core.schema` 导出；
- `demand/schema.md` 要求的关键 schema layer 没有注册；
- Summary 前端表格读取了 `TraceTableRow` 外的 `row.*` 字段；
- table payload 没有 schema-first 读取路径；
- `project_fields` / `schema_protocol_extensions` 被当成 reference、scenario、execution_mode、output_source、application_boundary 等主协议事实来源。

## 文件

- `config.yaml` — 声明 required layers、扫描模式、扫描文件模式、schema 源头白名单、允许的兼容 wrapper 和阻断级别。`scan_modes.core/full` 中的 `python_files` / `frontend_files` 支持 `*` / `**` 通配模式。
- `schema_audit.py` — 全局静态扫描器，输出结构化 JSON。
- `schema-hook.sh` — hook/check 入口。
- `test_schema_hook.py` — hook 自测。

## 运行

```bash
bash hooks/schema/schema-hook.sh                 # 默认 core 模式
bash hooks/schema/schema-hook.sh --mode full     # 全量模式
python hooks/schema/schema_audit.py --mode core
python hooks/schema/schema_audit.py --mode full
pytest hooks/schema/test_schema_hook.py
```

审计结果会写入配置项 `audit.report_file` 指定的文件，默认：

```text
hooks/schema/schema-audit-report.json
```

命令行只打印报告路径和摘要，不把完整 issue 列表刷到终端。

## 是否调用大模型

不调用。`schema_audit.py` 是本地静态扫描脚本，只读取仓库文件、解析 Python AST / 文本 / YAML，并输出 JSON 报告。它不会调用 Claude、OpenAI 或任何外部服务。

## Schema 源头白名单

`schema_source_whitelist` 用于声明 schema 源头文件，例如：

```yaml
schema_source_whitelist:
  - impl/core/schema/*.py
  - impl/core/schema/**/*.py
```

这些文件是标准定义本身，不参与函数输入/输出合规扫描。即使 `full` 模式通过 `impl/**/*.py` 匹配到了它们，也会自动过滤。

注意：这只影响函数输入/输出扫描。schema 注册、导出、运行时使用情况等元检查仍然会读取 `impl/core/schema/`。

## 扫描模式

- `core`：核心扫描模式，只扫描当前定义的数据流核心边界文件。
- `full`：全量扫描模式，按通配模式扫描项目内匹配文件，例如 `impl/**/*.py`、`hooks/**/*.py`。

扫描结果怎么处理由后续模块决定；本 hook 只负责产出结构化报告。

每条函数问题按函数聚合，只写不满足要求的输入/输出，以及这些输入输出分别是什么格式：

```json
{
  "file": "impl/core/pipeline.py",
  "line": 217,
  "function": "_batch_case",
  "inputs": ["case: Dict[str, Any]"],
  "outputs": ["return: Dict[str, Any]"]
}
```

字段格式统一为：

```text
字段：当前字段数据类型
```

报告不输出 `recommended_fix`，也不在函数项里写修复建议。非函数输入/输出类问题放在 `schema_issues`。

## 结果分级

- `error`：默认阻断。通常表示 schema layer 缺失、schema 类未导出、前端读取 schema 外字段等。
- `warning`：提醒。通常表示 schema 已声明但 runtime 使用少、核心函数仍返回 literal dict 等迁移风险。
- `info`：兼容层记录。比如 `normalize_*`、`*_from_run` 这类允许存在的 dict 边界。

## 设计原则

- 先复用现有 schema，不自动新增 schema。
- 如果发现现有 schema 无法表达数据流，hook 只报告建议，不擅自创建新 schema。
- dict 可以存在于 HTTP/file/legacy compatibility 边界，但不应该成为核心传播标准。
