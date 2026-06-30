# 配置对齐设计

日期：2026-06-30

## 目标

统一本项目的运行时配置，让服务启动、Python 执行环境、LLM 设置、UAT/E2E 端口都从一个项目级配置入口读取，并且具备清晰、可预期的覆盖规则。

第一版采用最小改造的方案 A：

- 新增 `impl/config.yaml`，作为非敏感运行配置的统一默认值来源。
- 新增 `impl/core/config.py`，作为唯一的运行配置加载层。
- API key 等敏感信息仍然只从环境变量读取。
- 尽量保持现有行为兼容，包括现有 DeepSeek 环境变量名和 `env.md` fallback。

## 非目标

本设计第一版不包含：

- `local` / `uat` / `ci` 这类 profile 机制。
- 迁移或重设计 `impl/projects/*/project.yaml`。
- 在 `impl/config.yaml` 中保存 API key 或其他 secret。
- Docker、CI、部署流水线重构。
- 完整迁移 adapter / 被测业务服务配置。
- 移除现有 `env.md` 兼容路径。

## 配置文件

新增 `impl/config.yaml`：

```yaml
python:
  executable: python

server:
  host: 127.0.0.1
  port: 8020

uat:
  host: 127.0.0.1
  port: 8021

llm:
  provider: deepseek
  model: deepseek-v4-pro
  base_url: https://api.deepseek.com/v1/chat/completions
  api_key_env:
    - DEEPSEEK_API_KEY
    - LLM_API_KEY
```

`impl/config.yaml` 只保存非敏感默认值。它可以声明 secret 应该从哪些环境变量读取，但不能保存真实 secret 值。

## 覆盖优先级

运行时配置按以下顺序解析：

```text
CLI 参数 > 环境变量 > impl/config.yaml > 代码默认值
```

第一版支持这些环境变量覆盖：

```text
PYTHON_EXECUTABLE
VERIFIER_HOST
VERIFIER_PORT
VERIFIER_UAT_HOST
VERIFIER_UAT_PORT
LLM_PROVIDER
LLM_MODEL
LLM_BASE_URL
DEEPSEEK_BASE_URL
DEEPSEEK_API_KEY
LLM_API_KEY
```

LLM API key 按 `impl/config.yaml` 中的 `llm.api_key_env` 顺序读取，默认顺序是：

```text
DEEPSEEK_API_KEY > LLM_API_KEY > env.md fallback
```

## 新增配置模块

新增 `impl/core/config.py`，提供轻量 typed API：

```python
get_runtime_config()
get_python_config()
get_server_config()
get_uat_config()
get_llm_config()
```

该模块负责：

- 加载 `impl/config.yaml`。
- 当配置文件或某些配置项缺失时，应用代码默认值。
- 应用支持的环境变量覆盖。
- 将端口字符串转换为整数。
- 校验 host / port 的基本形态。
- 按配置声明的环境变量顺序解析 LLM API key。
- 对 YAML 格式错误、非法配置值给出清晰错误信息。

第一版保持轻量，不引入重型 schema 框架。

## 服务启动

`impl/server.py` 当前有硬编码 parser 默认值：

```python
parser.add_argument("--port", type=int, default=8020)
parser.add_argument("--host", default="127.0.0.1")
```

改为从 `get_server_config()` 读取默认值：

```text
impl/config.yaml
  -> 环境变量覆盖 VERIFIER_HOST / VERIFIER_PORT
  -> CLI 参数覆盖 --host / --port
  -> uvicorn.run(...)
```

期望行为：

```bash
python -m impl.server
```

默认使用配置里的 `server.host` 和 `server.port` 启动，除非环境变量覆盖它们。

```bash
VERIFIER_PORT=8022 python -m impl.server
```

使用端口 `8022`。

```bash
python -m impl.server --port 8023
```

使用端口 `8023`，覆盖环境变量和配置文件。

## Python 启动环境

`start_server.sh` 当前硬编码了本机 Conda Python 路径。改为可移植启动脚本：

```bash
#!/bin/bash
set -euo pipefail

PYTHON_BIN="${PYTHON_EXECUTABLE:-python}"
exec "$PYTHON_BIN" -m impl.server "$@"
```

这样 shell 启动保持简单、可移植。脚本本身不解析 YAML。如果用户本地需要指定 Python 解释器，通过 `PYTHON_EXECUTABLE` 覆盖：

```bash
PYTHON_EXECUTABLE=/path/to/python ./start_server.sh
```

`impl/config.yaml` 中的 `python.executable` 保留为 Python 侧工具和未来启动 helper 的配置项；第一版 shell launcher 为了可移植性只直接读取环境变量。

## LLM 配置

`impl/core/llm_client.py` 当前自己维护 model/base URL 默认值，并直接读取环境变量。改造后，运行时默认值解析统一放到 `impl/core/config.py`。

`LlmClient()` 默认值等价于：

```text
model = get_llm_config().model
base_url = get_llm_config().base_url
api_key = get_llm_config().api_key
```

以下兼容行为保持不变：

- `DEEPSEEK_API_KEY` 和 `LLM_API_KEY` 继续可用。
- `DEEPSEEK_BASE_URL` 和 `LLM_BASE_URL` 继续可用。
- `env.md` fallback 保留，用于兼容本地旧用法。
- Agno/OpenAI 兼容桥保留，但应收敛到清晰的 helper，例如 `ensure_openai_compat_api_key(api_key)`。

缺少 key 时仍不让进程崩溃，而是返回结构化 missing-key 结果。错误文案可以泛化为提示当前配置支持的 key 环境变量名。

## UAT 和 E2E 端口

将运行服务端口和 UAT/E2E 目标端口分开：

- `server.port`：verifier UI/backend 的默认启动端口。
- `uat.port`：UAT/E2E 测试默认访问的目标端口。

现有硬编码 `8020` 的测试或 smoke check，应改为从 `get_uat_config()` 构造 URL，并允许 `VERIFIER_UAT_PORT` 覆盖。

如果现有测试假设 server 已经提前启动，第一版保持该假设不变。第一版只改目标 URL 的构造方式。

## 文档更新

更新 `README.md`，标准启动方式改为：

```bash
python -m impl.server
```

说明默认值位置：

```text
impl/config.yaml
```

说明常见覆盖方式：

```bash
VERIFIER_PORT=8022 python -m impl.server
python -m impl.server --port 8023
export DEEPSEEK_API_KEY="..."
```

删除或替换暗示“机器特定 Python 路径是标准启动方式”的示例。

## 错误处理

配置层对本地配置问题给出清晰错误：

- YAML 格式错误：提示 `impl/config.yaml` 和解析错误。
- 缺少 PyYAML：说明运行配置需要项目环境安装 `pyyaml`。
- 非法端口：指出具体字段，并要求取值在 `1..65535`。
- 非法 `api_key_env`：要求它是非空字符串列表。

LLM 缺少 key 仍保持为运行时 LLM 结果，不作为进程级崩溃处理。

## 测试

新增或更新测试覆盖这些行为：

1. 配置加载
   - 默认值从 `impl/config.yaml` 加载。
   - 配置文件缺少部分字段时回退到代码默认值。
   - 环境变量覆盖 YAML 值。
   - 非法端口值给出清晰失败。
   - LLM key 解析遵循 `api_key_env` 顺序。

2. 服务启动
   - 默认 host/port 来自 config。
   - `VERIFIER_PORT` 覆盖 config。
   - CLI `--port` 覆盖 env/config。
   - 通过 monkeypatch `uvicorn.run` 避免测试中真正启动 server。

3. LLM client
   - 默认 model/base URL 来自 config。
   - `DEEPSEEK_BASE_URL` / `LLM_BASE_URL` 覆盖 config。
   - 缺少 key 返回现有结构化错误。
   - OpenAI 兼容环境变量桥仍按预期设置请求 API key。

4. UAT URL 构造
   - URL 使用 `uat.host` / `uat.port`。
   - `VERIFIER_UAT_PORT` 覆盖 config。

## 迁移影响

现有用户仍可运行：

```bash
python -m impl.server --port 8020
```

现有 LLM 环境变量继续可用。主要可见变化是，直接运行：

```bash
python -m impl.server
```

会从 `impl/config.yaml` 获取默认 host 和 port；`start_server.sh` 不再假设某个开发者本机的 Conda 路径。
