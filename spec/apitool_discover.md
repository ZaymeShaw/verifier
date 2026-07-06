懂。你的核心诉求是：**每个项目都能快速发现 API 端点，但不想每个项目从零写一遍发现逻辑**。

这就是典型的"通用引擎 + 项目薄配置"的分工，和 VerifiableTool 的设计思路一致：

## 通用层（写一次，所有项目复用）

`impl/core/endpoint_discovery.py` 提供发现引擎，做这些事：
- 扫描源码找装饰器（`@app.route`、`@router.post`、`@app.get` 等）
- 扫描配置找已声明 API（读 `project.yaml` 的 `api` 字段）
- 从 adapter 的 `build_request` / `call_or_prepare` 反查 live 入口
- 解析类型注解推导入参/出参形状
- 判断每个 endpoint 可不可调用（直接调 / 远程调 / 不能调）
- 把发现的 endpoint 自动构建成 VerifiableTool

这部分所有项目共用，不写项目名分支。

## 项目层（每个项目只写一份薄配置）

每个项目在 `project.yaml` 里加几行配置，告诉通用引擎"去哪扫、扫什么、排除什么"：

```yaml
endpoint_discovery:
  source_roots:
    - ../../../projects/client_search           # 业务系统源码根
  scan_patterns: ["*.py"]
  exclude_patterns: ["*/test/*", "*/migrations/*"]
  framework: fastapi                            # 用的什么 web 框架，决定扫什么装饰器
```

就这么多。项目层只声明"去哪扫、用什么框架"，发现逻辑全在通用引擎里。

## 换一个新项目时

只需要在它的 `project.yaml` 里填 `source_roots` 和 `framework`，通用引擎自动扫出它的 endpoint 并构建成 tool。**不需要写任何 Python 代码，不需要从零实现。**

## 为什么这样能满足你的诉求

- **快速发现**：通用引擎一次写好，新项目填几行 yaml 就能用
- **不从零实现**：项目层只配置，不写代码；发现逻辑、tool 构建逻辑都在通用层复用
- **项目差异通过配置吸收**：不同项目用不同框架（fastapi/flask/grpc）、不同源码结构，通过 `framework` 字段和 `exclude_patterns` 配置覆盖，不需要为每个项目写专门的扫描器

这个分工和 `field_provider`（通用协议 + 项目级 provider）、`VerifiableTool`（通用协议 + 项目级 execute_fn）是同一套范式——通用层管引擎，项目层只填薄数据。你新接一个项目，照着填一份 yaml 配置就能发现它的 API 端点。




--------


好的，我调整一下表述，确保通用可泛化。

## 1. 启动时扫描 + 模板

`project.template.yaml` 里加一段：

```yaml
# ---- 可选：API 端点自动发现 ----
# 不配置此字段则跳过扫描，完全兼容现有项目。
# 配置后，启动时通用引擎自动扫描业务系统源码中的 API 端点，
# 构建为可调用 VerifiableTool，注册到 ToolRegistry。
# endpoint_discovery:
#   source_roots:               # 业务系统源码根路径（相对于项目根目录）
#     - ../../../projects/your_project
#   framework: fastapi           # 使用的 Web 框架：fastapi | flask | grpc | generic
#   scan_patterns: ["*.py"]      # 扫描文件类型，默认 *.py
#   exclude_patterns:            # 排除路径，默认排除 test/migrations/venv
#     - "*/test/*"
#     - "*/migrations/*"
#     - "*/venv/*"
```

没配置 `endpoint_discovery` 的项目不受影响，启动逻辑是完全的 add-on。

## 2. 单独文件夹放扫描结果

每个项目的扫描结果统一放在 `impl/projects/<project>/tools/api_discover/` 下：

```
impl/projects/<project>/
  tools/
    __init__.py              # 导出所有 tool（手工 + api_discover）
    ...                      # 手工写的 tool
    api_discover/            # 自动生成的 tool（扫描器产出，不手工编辑）
      __init__.py
      ...
```

加载逻辑：
- `tools/__init__.py` 同时导出手工 tool 和 `api_discover/` 下的自动生成 tool
- `api_discover/` 下的文件每次扫描全量覆盖，不和手工 tool 混

## 3. 通用化描述

整套方案适用于任何项目，不绑定 client_search：

- **通用引擎**（`impl/core/endpoint_discovery.py`）：根据 `project.yaml` 配置扫描源码，查找装饰器/路由注册/API 声明，自动构建 VerifiableTool。所有项目复用同一套扫描逻辑。
- **项目配置**（`project.yaml` 的 `endpoint_discovery` 字段）：每个项目只需声明"去哪扫 + 用什么框架"，不需要写任何扫描代码。
- **扫描产物**（`impl/projects/<project>/tools/api_discover/`）：每个项目独立的自动生成 tool 目录，管理清晰。

新项目接入流程：复制 `project.template.yaml`，填 `source_roots` 和 `framework` 两行，启动即自动发现端点。