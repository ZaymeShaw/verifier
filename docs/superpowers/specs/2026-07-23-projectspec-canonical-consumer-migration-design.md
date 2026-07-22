# ProjectSpec 规范消费者迁移设计

## 目标

在不修改 `spec/adapter/config.md`、不修改三份正式 YAML，也不改变
LiveSchema、Judge、Attribute、Mock 业务判断语义的前提下，把所有正式
Python 消费者从 `ProjectSpec` 的旧形状兼容字段迁移到规范的
`project`、`runtime`、`verifier` 分区和精确访问器，最终删除兼容字段及其
构造逻辑。

本次处理的是类型化配置对象的消费接口，不处理 active manifest/receipt
内容陈旧问题；后者继续由现有完整性门禁独立阻断。

## 当前问题

项目 YAML 已经使用规范结构，但 `ProjectConfigResolver` 仍从规范字段派生
以下只读兼容视图：

- `common`
- `api`
- `application`
- `frontend_extensions`
- `documents`
- `source_project`
- `endpoint_discovery`
- `attribute_draft`、`judge_draft`、`mock_draft`、`live_draft`

core、项目实现和工具仍有消费者直接读取这些字段。这不会产生第二份 YAML
权威，却保留了旧字段语义，并把 `verifier.presentation`、`verifier.extra`
和 `verifier.check_rules` 再次压平为 `frontend_extensions`，使配置分区边界在
类型化对象之后丢失。

## 迁移原则

1. 配置事实仍只来自规范 YAML 和现有 resolver，不增加 sidecar、fallback
   或新的环境变量入口。
2. 消费者读取规范分区或一个职责单一的访问器，不增加新的万能字典视图。
3. 路径消费者继续使用 `PathResolver` 支撑的访问器，不从字符串根目录自行
   拼接。
4. 先迁移消费者并证明行为等价，最后删除兼容字段；不能先删字段再用隐式
   fallback 修复报错。
5. 项目业务默认值不得在迁移中改变。发现旧消费者自带 fallback 时，先用
   测试冻结当前行为，再判断它属于协议默认还是待单独处理的问题。
6. 不修改 active evidence 的 revision、sha256、symbol 或 receipt，不以刷新
   证据掩盖消费者迁移回归。

## 规范映射

| 旧消费入口 | 规范入口 |
|---|---|
| `spec.common["ready"]` | `spec.ready` 或 `spec.runtime["ready"]` |
| `spec.common["mock_cases"]` | `spec.runtime["mock_cases"]` / 精确 mock accessor |
| `spec.api` | `spec.service("primary")` / `spec.require_service("primary")` |
| `spec.application["mode"]` | `spec.runtime_mode` |
| `spec.application` 依赖服务 | `spec.runtime["services"]["dependencies"]` / `spec.service(id)` |
| `spec.documents` | `spec.project["resources"]["documents"]`；文件读取使用 `project_document_path()` |
| `spec.source_project` | `source_root_path()`；禁止作为展示字符串之外的运行输入 |
| `spec.frontend_extensions` 展示项 | `spec.presentation` |
| `spec.frontend_extensions` 项目规则 | `spec.verifier["extra"]` 中对应注解值的精确 accessor |
| `spec.frontend_extensions["check_rules"]` | `spec.verifier["check_rules"]` |
| `spec.endpoint_discovery` | `spec.verifier["endpoint_discovery"]` / `endpoint_source_paths()` |
| `spec.<role>_draft` | `spec.role_draft(role)` / `role_draft_path(role)` |

`project.resources.documents` 中保留的是带 `project://` 前缀的逻辑路径。需要
物理文件时必须调用 `project_document_path()`，不得把逻辑值当作本地相对路径。

## 类型接口调整

`ProjectSpec` 保留规范字段和已有的精确访问器，并只补充实际出现两次以上、
含义明确的访问器。允许补充的类型接口包括：

- 文档 ID 和逻辑文档映射；
- primary/dependency service；
- role draft 配置与 module path；
- `verifier.presentation`；
- `verifier.check_rules`；
- 已注解 `extra` 的按分区、按字段读取。

访问器必须直接读取规范分区，不缓存第二份值。禁止增加
`legacy_config`、`extensions`、`flattened_config` 等重新混合职责的接口。

## 分批实施

### 第一批：core 语义消费者

迁移 interaction、pipeline、HTTP client、project loader、analysis、check、
frontend view、judge、live protocol 和 source retrieval。先覆盖 ready、service、
documents、presentation/check rules、role draft 和路径访问。

### 第二批：项目实现和项目工具

迁移 QA、client_search、deerflow、marketting-planning、
marketting-planning-intent 下的正式消费者。只替换取值接口，输出 schema、判断
分支、默认值和错误语义保持不变。

### 第三批：测试、诊断和开发探针

测试 fixture 应通过规范字段构造 `ProjectSpec`，不再直接修改
`mock_draft` 等兼容属性。生产无关的历史 Markdown 和只读报告不批量改写。

### 第四批：删除兼容层

当静态扫描确认没有 Python 消费者后：

1. 从 `ProjectSpec` 删除旧兼容字段；
2. 从 `_build_project_spec` 删除 `common`、`api`、`application`、
   `frontend_extensions` 等派生构造；
3. 删除 `_legacy_endpoint_discovery`、`_legacy_role_draft` 等仅为兼容视图存在
   的转换；
4. 更新测试，证明规范 YAML 到规范 `ProjectSpec` 字段无损；
5. 在 `config-check` 增加旧字段消费者静态阻断。

## 行为保护

每一批迁移都必须保留以下行为：

- uploaded-output 项目不要求 live service；
- existing-service 项目的 URL、method、timeout 和 dependency service 不变；
- ready contract、mock case 场景、interaction 场景和终止事件不变；
- Judge、Attribute、Check 使用的业务规则和文档集合不变；
- role draft 的启用状态、module、tool limit 和 asset 选择不变；
- 所有路径仍通过显式 prefix 和 `PathResolver` 解析；
- 本地服务 health/start/reuse 与 attribution 开关行为不变。

若旧 `frontend_extensions` 中混入了实际影响 Live/Judge 的字段，本次只把它
迁到其已经存在的规范归属，不把它误判为纯展示，也不调整字段定义。

## 门禁与测试

新增或加强以下验证：

1. 静态扫描生产 Python，拒绝 `spec.common`、`spec.api`、
   `spec.application`、`spec.frontend_extensions`、`spec.source_project`、
   `spec.documents`、`spec.endpoint_discovery` 和 `spec.<role>_draft`；
2. 项目配置合同测试证明每个规范分区到消费者的取值结果；
3. 路径测试证明文档、source、draft、asset、endpoint discovery 仍经过
   resolver；
4. 聚焦测试覆盖 interaction、HTTP、check/judge、project loader、五个项目
   adapter/live/attribute/mock；
5. 全量 `pytest` 与 `config-check --full`。

当前仓库已有的 active manifest/receipt 陈旧错误允许在迁移前后保持同一组
已知失败，但不得新增失败。兼容字段迁移完成的结构性判据不依赖刷新这些证据；
正式发布验收仍要求它们另行修复并使全量门禁通过。

## 完成条件

- 正式 Python 消费者不再引用旧兼容字段；
- `ProjectSpec` 不再声明或构造旧兼容字段；
- config-check 能阻断重新引入旧字段消费；
- 三份 YAML、配置 schema 和路径协议没有被放宽；
- 聚焦回归全部通过；
- 全量回归与迁移前相比没有新增失败；
- 没有修改 LiveSchema、Judge、Attribute、Mock 的业务判断语义或 active
  evidence 完整性事实。
