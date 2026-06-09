# verifier

通用评测与验证工具，用于把项目配置、实时请求、judge、归因、聚类、check 和前端视图串成一套可验证流程。

## 目录

- `impl/`：核心实现、项目适配、协议和前端页面。
- `impl/projects/`：各项目的评测配置与 adapter。
- `impl/frontend/`：本地分析界面。
- `.claude/skills/`：Claude Code skill 定义。
- `projects/`、`data/`、`search-test-case/`：项目资料、样例数据和历史验证记录。

## 环境要求

- Python 3.9+
- 可访问被测业务服务
- DeepSeek API Key，通过环境变量提供：

```bash
export DEEPSEEK_API_KEY="你的 key"
```

也支持 `LLM_API_KEY`、`DEEPSEEK_BASE_URL`、`LLM_BASE_URL`。

## 启动前端分析服务

在项目根目录执行：

```bash
python -m impl.server --port 8020
```

启动后访问：

- `http://127.0.0.1:8020/frontend/index.html`
- `http://127.0.0.1:8020/frontend/live.html`
- `http://127.0.0.1:8020/frontend/summary.html`

健康检查：

```bash
curl http://127.0.0.1:8020/health
```

## CLI 用法

列出项目：

```bash
python -m impl.cli projects
```

查看项目分析：

```bash
python -m impl.cli analysis --project client_search
```

执行 mock 单例链路：

```bash
python -m impl.cli run-chain --project client_search --mock --input '{"query":"示例查询"}'
```

执行批量 mock：

```bash
python -m impl.cli batch-run --project client_search --mock --inputs '[{"query":"示例查询"}]'
```

## client_search 本地验证流程

1. 启动业务服务，确保业务接口在 `8000` 端口可访问。
2. 启动 verifier 前端分析服务，默认使用 `8020` 端口。
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
