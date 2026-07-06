# verifier

通用评测与验证工具，用于把项目配置、实时请求、judge、归因、聚类、check 和前端视图串成一套可验证流程。
本项目的核心目标是旨在通过构建一些模拟case案例，对业务系统进行模拟交互、输出评估、问题归因，从而看到业务系统当前有哪些问题（包括业务系统功能、算法能力，特别是算法能力方面）


## 目录

- `impl/`：核心实现、项目适配、协议和前端页面。
- `impl/projects/`：各项目的评测配置与 adapter。
- `impl/frontend/`：本地分析界面。
- `.claude/skills/`：Claude Code skill 定义。
- `projects/`、`data/`、`search-test-case/`：项目资料、样例数据和历史验证记录。

## 环境要求

- Python 3.11+（推荐通过 conda agno 环境提供，见 `impl/config.yaml` 的 `python.executable`）
- 可访问被测业务服务
- DeepSeek API Key，通过环境变量提供：

```bash
export DEEPSEEK_API_KEY="你的 key"
```

非敏感运行默认值统一放在 `impl/config.yaml`。也支持 `LLM_API_KEY`、`DEEPSEEK_BASE_URL`、`LLM_BASE_URL` 等环境变量覆盖。

### Python 解释器选择

verifier 依赖 agno，**必须用 `impl/config.yaml` 中 `python.executable` 指定的解释器**（通常是 conda 的 agno 环境）。直接 `python -m ...` 可能误用系统默认 python（缺 agno 或版本不对）。

为此提供统一入口 `run.sh`，自动从 `config.yaml` 读取正确的解释器，无需手动 `conda activate`：

```bash
bash run.sh help              # 查看所有子命令
bash run.sh server            # 启动 verifier 服务（端口 8020）
bash run.sh uat               # 启动 UAT 服务（端口 8021）
bash run.sh cli projects      # 跑 impl.cli
bash run.sh check1            # 跑 checklist check1
bash run.sh api-check         # 跑 api-check（自动启动/复用 UAT 服务）
bash run.sh python <args>     # 用正确解释器跑任意 python 命令
```

环境变量 `PYTHON_EXECUTABLE` 可覆盖 config.yaml 的解释器（最高优先级）。

## 启动前端分析服务

在项目根目录执行：

```bash
bash run.sh server
```

默认 host/port 从 `impl/config.yaml` 读取。临时覆盖端口：

```bash
bash run.sh server --port 8023
VERIFIER_PORT=8022 bash run.sh server
```

启动后访问：

- `http://127.0.0.1:8020/frontend/index.html`
- `http://127.0.0.1:8020/frontend/live.html`
- `http://127.0.0.1:8020/frontend/summary.html`

以上地址对应 `impl/config.yaml` 中默认的 `server.host` / `server.port`。

健康检查：

```bash
curl http://127.0.0.1:8020/health
```

## CLI 用法

列出项目：

```bash
bash run.sh cli projects
```

查看项目分析：

```bash
bash run.sh cli analysis --project client_search
```

执行 mock 单例链路：

```bash
bash run.sh cli run-chain --project client_search --mock --input '{"query":"示例查询"}'
```

执行批量 mock：

```bash
bash run.sh cli batch-run --project client_search --mock --inputs '[{"query":"示例查询"}]'
```

## client_search 本地验证流程

1. 启动业务服务，确保业务接口在 `8000` 端口可访问。
2. 启动 verifier 前端分析服务，默认端口来自 `impl/config.yaml` 的 `server.port`。
3. 如果项目依赖 ES，先执行业务项目的 reindex 接口。
4. 在前端或 CLI 中执行实时请求、judge、归因和 check，确认链路可用。

## 新增项目

在 `impl/projects/<project_id>/` 下补齐：

- `project.yaml`
- `adapter.py`
- `application.md`
- `evaluation.md`
- `judge.md`
- `attribution.md`
- `checklist.md`
- `mock.md`

协议说明见 `impl/protocols/`。
