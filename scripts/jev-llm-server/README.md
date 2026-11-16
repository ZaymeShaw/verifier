# JEV LLM 服务

将普通聊天模型包装为 `POST /v1/systemone` 服务。复用 JEV 模板的判断标准，接收已经填充 state 的请求，返回 `model + answers + usage`。不处理 Excel、traceid、材料映射或分类表格，不写死业务标签。

```text
现有 pipeline → JEV 请求 → 本服务 → Chat Completions → 校验响应 → 现有 pipeline 的结果表
```

## 安装与启动

需要 Python 3.11+。依赖沿用仓库已有版本，可使用已有 Python 环境，也可在此目录创建独立环境：

```bash
cd scripts/jev-llm-server
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# 首次使用且 .env 不存在时：
cp -n .env.example .env
# 编辑 .env 后：
python server.py
```

本服务复用上一级 `jev_build_requests.py` 的文本协议校验。独立部署时保留这个相对关系：

```text
scripts/
├── jev_build_requests.py
└── jev-llm-server/
    ├── server.py
    ├── .env
    ├── .env.example
    ├── requirements.txt
    └── README.md
```

它不依赖 verifier 服务或 `verifier-jevcls`。原实验 `run_original_model.py` 保持原位；本服务沿用其“questions/state 转聊天请求”的思路，移除了写死的保险意图、供应商限制、布尔输出及已完成 ID 跳过逻辑。

## 配置

只从本目录 `.env` 读取配置，不读取父目录或用进程变量补齐配置，不做变量插值。文件与密钥不提交。编辑后重启服务。

| 配置 | 含义 |
|---|---|
| `SERVER_HOST` | 监听地址，本机使用 `127.0.0.1` |
| `SERVER_PORT` | 监听端口，例如 `8040` |
| `SERVER_API_KEY` | 调用此服务的 Bearer 密钥，由你设置 |
| `LLM_BASE_URL` | 上游基础地址，例如 `https://gateway.example/v1`；SDK 追加 `/chat/completions` |
| `LLM_API_KEY` | 上游服务密钥，和调用本服务的密钥分开 |
| `LLM_TIMEOUT_SECONDS` | 整次上游调用的超时秒数，例如 `120` |
| `LLM_ENABLE_THINKING` | `false`（默认）关闭思考，`true` 开启；仅接受这两个值，修改后重启 |

模型名直接使用每个请求的 `model`。没有默认模型或别名映射。上游需支持非流式 Chat Completions、system/user 消息和 `response_format={"type":"json_object"}`，并返回实际模型、完整 JSON 内容和 token usage。不支持 JSON 模式时明确失败，不自动降级。

服务每次通过 SDK 的 `extra_body` 传入 `enable_thinking`，实际 HTTP JSON 中是顶层布尔字段，未配置时也显式发送 `false`。这是上游扩展参数，不是通用的 OpenAI/JEV 协议字段；当前采用与原实验一致的 `enable_thinking` 约定，参见 [上游参数文档](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)。上游必须支持并遵守这个字段，不能仅凭请求发出就保证服务端已关闭思考。开启时还须支持 thinking 与非流式 JSON 输出同时使用；不支持时明确失败，不删除参数重试，不向业务模板插入 `/no_think` 等提示词。该配置只属于本服务，不改变调用方的 JEV 请求。

## 接入现有分类工作流

启动服务后，仅修改 `verifier-jevcls/.env` 的连接信息：

```dotenv
JEV_API_URL=http://127.0.0.1:8040/v1/systemone
JEV_API_KEY=与服务的SERVER_API_KEY一致
JEV_MODEL=上游支持的模型名
```

调用方 `JEV_TIMEOUT_SECONDS` 应大于服务的 `LLM_TIMEOUT_SECONDS`，留出传输及校验时间。材料、字段字典、模板和输出配置不变，仍运行现有 `pipeline.py`。切回原生 JEV 时改回地址、密钥和模型。

## 请求与响应边界

接口要求 `Authorization: Bearer <SERVER_API_KEY>` 和 `Content-Type: application/json`。

支持现有组装器的文本协议子集：字符串/对象/数组 state，Choice、Noul、Score，可混合多个独立问题；明确拒绝 assets、Box、multipart 和未知协议字段。空 state、重复 JSON 键、非有限数字、未知输出字段或问题遗漏均报错。

协议结构依据 [System One 官方文档](https://docs.typesafe.ai/api/system-one.md)，核对日期 2026-11-14：

- Choice：LLM 返回原始选项名、confidence、覆盖全部选项的概率；选项必须是概率最高者。
- Noul：LLM 返回 0–1 数值，不接受布尔值或字符串。
- Score：LLM 返回等级概率、期望分数和 confidence；服务检查分数与概率加权结果一致，按原 criteria 构造 legend。
- 概率范围 0–1，概率和与 1 的绝对误差最多约 0.001；Score 加权值允许同样的舍入误差。不自动归一化、补选项或修复 JSON。
- `model` 使用上游实际返回值，usage 从真实 `prompt_tokens`/`completion_tokens` 转换；缺失就失败，不用请求模型或估算 token 数补齐。

**这是协议适配，不是原生 JEV 推理。** 概率、confidence、Noul 和 Score 来自 LLM 自评，不是 logits 读出或已校准的准确率，不能直接沿用原生 JEV 的分数阈值。响应头标注 `X-JEV-Backend: llm` 和 `X-JEV-Score-Source: llm-self-report`，响应 JSON 保持协议字段。当前分类 pipeline 保存实际模型和答案，但不保存这两个 HTTP 头；跨服务对比时同时记录使用的端点。

一次请求只调用上游一次，不调用业务工具，不截断 state，不缓存或跳过历史记录，不重试、不跟随重定向、不自动切换模型。没有落盘请求日志；现有 pipeline 继续保存 JEV 请求和响应。服务持有的 HTTP 连接池只是复用连接，不复用结果。

错误：401 为本服务鉴权失败，415 为非 JSON 请求，422 为无效 JEV 输入，502 为上游 HTTP/连接错误或无效输出，504 为超时。上游错误文本不会透传，以免泄漏请求或密钥。

## 测试

在仓库根目录使用安装了 pytest 和现有工作流依赖的环境：

```bash
python -m pytest scripts/jev-llm-server/tests tests/test_verifier_jevcls_pipeline.py -q
```

包含协议与异常检查，以及真实本地 HTTP 的端到端测试：原样复制现有 pipeline 到临时目录，通过本服务连接模拟上游并生成含主表和分类概率明细的 Excel。测试不会修改实际 `.env`、材料或结果，也不消耗真实模型额度。它证明接口能接通，不代表内网上游已实测或标注质量已验证。
