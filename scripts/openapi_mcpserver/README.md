# HTTP 接口 → MCP 服务

使用 FastMCP `from_openapi()` 生成工具，通用执行器负责上游路由、鉴权请求和字段注入。鉴权结果绑定为本次调用的 `${token}`，由 Header 或 body 显式引用。
已按原 `insurance-tools-mcp` 的 10 类业务 HTTP 请求配置 `projects/insurance-tools`。

## 本次已配置的内容

- 根 `.env` 选择 insurance-tools 项目，默认 stdio；原 dev 的 10 个业务 URL 直接填在项目 `config.local.yaml`。
- 项目 `config.local.yaml` 的 10 个操作均使用内联 `auth.curl` 与 `token_path`，每次业务调用前请求一次 Ark Token，不缓存、不共享 Token。复杂鉴权仍支持 `脚本.py:函数名`。
- **原 dev 配置没有启用鉴权，也没有真实 Token 地址、凭据、接口标识或可用于本次部署的可信身份。** Token 地址、凭据和身份在 `.env` 中留空，`auth_curls/*.txt` 的 grant_type、invokeInterface 标为“待填写”，使用前必须填写；不会使用模拟身份或匿名请求代替。
- 已安装锁定依赖到本目录 `.venv`。未请求原 dev 或新环境的真实业务服务。

## 文件职责

```text
openapi_mcpserver/
├── .env                         # 本机实际启动配置和凭据；Git 忽略
├── .env.example                 # 可复制的环境变量模板，无真实凭据
├── server.py                    # 统一启动入口
├── generate_openapi.py          # 从 curls/ 批量生成 OpenAPI 和 YAML 草稿（离线）
├── curl_mcp/                    # 通用实现
├── pyproject.toml / uv.lock      # 锁定依赖
├── projects/insurance-tools/
│   ├── openapi.json             # 工具名称、描述、业务参数 Schema
│   ├── config.local.yaml        # 路由、身份注入和鉴权配置
│   ├── auth_curls/              # 获取 Token 的 cURL；填写 grant_type、invokeInterface
│   ├── curls/                  # 一个 tool_name.txt 对应一个接口的 cURL
│   └── draft/                  # 模板输出，引用外层已有鉴权文件
└── tests/                       # 请求对照、鉴权和启动集成测试
```

`config.local.yaml` 直接填写业务 URL、鉴权配置和调用规则，不含实际密钥，可以随项目提交。实际凭据仅放 `.env` 或启动进程的环境中。

## 启动真实项目

需要 Python 3.11–3.14 和 uv。首次在本目录运行：

```bash
uv sync --frozen
# 只有 .env 不存在时，才从模板创建，避免覆盖已有凭据
# cp .env.example .env
```

编辑根 `.env`：

```dotenv
MCP_CONFIG=projects/insurance-tools/config.local.yaml
MCP_CLIENT_CONFIG_DIR=projects/insurance-tools/draft
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8000
MCP_PATH=/mcp

MCP_AGENT_NUMBER=
MCP_AUTH_SUBJECT=
ARK_TOKEN_URL=
ARK_CLIENT_ID=
ARK_CLIENT_SECRET=
# grant_type、invokeInterface 在 auth_curls/*.txt；业务 URL 在 config.local.yaml
```

填写值之后检查并启动：

```bash
uv run --frozen python server.py --check
uv run --frozen python server.py
```

`--check` 校验业务配置、模板变量和鉴权 cURL，缺少其引用的环境变量时启动失败；鉴权 cURL 的路径相对于 YAML 所在目录。它不会发送鉴权或业务请求，也不会判断写死的 grant_type、invokeInterface 是否符合上游契约，标为“待填写”的值必须人工补齐。脚本鉴权会加载模块并检查异步函数签名，不执行函数、不检查函数内部凭据；自定义脚本应保持模块加载无网络副作用。

路径与优先级：

- 默认只读取 `server.py` 旁的 `.env`，不搜索父目录，不依赖当前工作目录。
- `MCP_CONFIG` 的相对路径以该 `.env` 的目录为基准。
- YAML 的 `openapi` 相对路径以 YAML 所在目录为基准。
- 将 `.env` 解析成字符串字典；其中声明的键可以被同名进程环境变量覆盖，包括显式空值。未在 `.env` 声明的进程变量不会传给脚本，也不会作为运行配置。读取不会修改进程环境；修改配置后需重启。
- 可用 `--env-file /absolute/path/.env` 选择另一份启动环境；`--config` 可覆盖 `MCP_CONFIG`，相对路径仍以所选 `.env` 的目录为基准。
- `python -m curl_mcp` 与 `python server.py` 使用同一实现。

## MCP 客户端接入

每次运行 `server.py`（包括 `--check`、`--client-config`）会在 `.env` 的 `MCP_CLIENT_CONFIG_DIR` 指定目录生成或更新本次模式的连接配置。此项必填，支持绝对路径；相对路径以所选 `.env` 所在目录为基准，目录不存在时自动创建。例如 `MCP_CLIENT_CONFIG_DIR=projects/insurance-tools/draft`：

- stdio：`mcp.client.stdio.json`，包含当前 Python 解释器、`server.py`、`.env` 和 YAML 的绝对路径。
- HTTP：`mcp.client.http.json`，包含本次监听地址、端口和 MCP 路径对应的 URL。

文件采用常见的 `mcpServers` JSON 结构，可将相应条目合入支持此格式的客户端；其他客户端按其设置界面填写 command/args 或 URL。生成器不会修改任何客户端设置。文件名固定，每次只整体覆盖当前传输方式的同名文件，另一份不变，不合并已有内容。不同项目或正式/草稿需要分别保存时，指定不同目录；同一目录里的 stdio 文件始终指向最后一次导出时选择的 YAML。不要在生成文件中维护手工修改；这些本机路径文件已加入 Git 忽略。

正常 stdio 启动时，stdout 只用于 MCP 协议，配置文件路径和说明输出到 stderr。HTTP 模式另外提示连接 URL。生成配置不代表服务已经启动成功：YAML/OpenAPI 加载成功后就会导出，后续仍可能因凭据缺失或端口占用而失败。

只想获取配置、不启动服务时：

```bash
.venv/bin/python server.py --config projects/insurance-tools/draft/config.draft.yaml --client-config
```

这个命令会写出文件，同时在 stdout 输出可复制的 JSON；它不检查上游凭据，也不发请求。若希望导出另一种传输方式，可用 `--transport` 覆盖 `.env`：

```bash
.venv/bin/python server.py --config projects/insurance-tools/draft/config.draft.yaml --transport http --client-config
```

stdio 配置显式包含 `--transport stdio` 和本次选中的 `.env`、YAML，不依赖客户端 cwd，也不会因为 `.env` 改成 HTTP 而意外启动 HTTP 进程。stdio 由客户端拉起，不需要提前手动启动或端口。HTTP 则需要先运行服务，再让客户端连接；导出配置不会留下后台服务。

输出不包含 Ark Token、凭据或调用身份，只引用 `.env` 文件。若本次凭据来自 shell 环境覆盖，客户端也需要具备相同环境，或先将部署值填写到对应 `.env`；导出器不会将 shell 凭据复制到客户端 JSON。

当 HTTP 监听 `0.0.0.0` 或 `::` 时，生成的是本机可连接的 `127.0.0.1` 或 `[::1]` 地址。跨机器连接需将 URL 的主机部分换成实际可达地址；生成器不猜公网域名、反向代理或 HTTPS 地址。

**HTTP 模式当前未配置客户端 → MCP 的访问认证，默认仅监听本机。** 所有连接共用本进程的上游身份；Ark 配置只负责 MCP → 业务接口鉴权。跨机器共享部署需要另行配置访问控制和网络入口。

## 批量粘贴 cURL，生成工具定义和运行配置

每个接口一个文件，放在项目的 `curls/` 中，每个文件只粘贴一条完整的 Bash 风格 JSON POST cURL：

```text
projects/insurance-tools/curls/
├── customer_query.txt
├── customer_detail.txt
├── policy_query.txt
└── ...
```

文件名（不含 `.txt`）同时作为 OpenAPI 的 `operationId`、YAML 的 `operations` 键和 MCP 工具名。采用小写 snake_case，最多 56 个字符，不允许连续下划线，避免 FastMCP 自动改名或截断。目录只读取当前层的 `*.txt`，不递归。

例如 `policy_query.txt`：

```bash
curl 'https://example.internal/api/v1/policy-search/query' \
  --header 'Content-Type: application/json' \
  --data-raw '{
    "filter": {"type": "PREDICATE", "field": "polno", "operator": "EQ", "value": "示例保单号"},
    "pageNo": 1,
    "pageSize": 5
  }'
```

在本目录运行（输出目录应尚未包含这两份草稿）：

```bash
uv run --frozen python generate_openapi.py projects/insurance-tools/curls
```

默认在 `curls/` 的父目录生成：

- `openapi.draft.json`：合并所有接口的路径、方法、参数结构，描述为“待补充”。
- `config.draft.yaml`：同名操作、从 cURL 提取的真实 URL，以及自动关联的鉴权、Header、字段注入和超时；`openapi` 自动指向配套草稿。无法确定的鉴权仍标为“待填写”。

也可以指定另一个输出目录：

```bash
uv run --frozen python generate_openapi.py projects/insurance-tools/curls --output-dir projects/insurance-tools/draft
```

本仓库 `draft/` 和 `draft-noauth/` 已按正式 `openapi.json` 人工同步了工具约束、默认值和固定字段注入；三份 OpenAPI 当前一致。`draft/` 保留鉴权引用，`draft-noauth/` 的 auth 全为 null 且无 token Header；不复制 `auth_curls/`。再次生成到相同目录会拒绝覆盖，请选择新目录。`curls/` 的 10 份脱敏请求样例来自现有地址配置和保存的测试请求；示例身份、客户号、保单号不代表真实可用数据。

自动关联规则：

- 如果 `curls/` 的父目录有 `config.local.yaml`，按同名 operationId 复用其中已确认的 `auth`、`headers`、`inject_body` 和超时。URL 仍取本次 cURL；正式 OpenAPI 的描述和业务约束不会被复制，生成结果仍需人工检查。
- 从生成的模型参数中移除 `inject_body` 提供的字段，嵌套对象中其余查询字段保留。已确认的规则与 cURL 显式占位符冲突时直接报错，不静默覆盖。
- 对未配置的新工具，如果存在同名 `auth_curls/tool_name.txt`，自动填写 `auth.curl`。Token 的响应位置不能从请求推断；可用 `--token-path /access_token` 明确指定新工具的共同位置，否则 `token_path: 待填写` 会阻止启动。此选项不覆盖已有配置中的鉴权规则。
- `draft/` 仅输出 OpenAPI 和 YAML 模板，不打包项目。鉴权 cURL 使用相对于输出 YAML 的路径，例如 `../auth_curls/policy_query.txt`；直接引用原文件，不复制。修改原鉴权文件后，下一次启动会读取新内容。移动 YAML 时需相应调整文件引用路径。
- 脚本鉴权可能依赖其他模块，因此生成器不会猜测或复制脚本依赖。含脚本鉴权时，在原项目目录生成草稿；如需独立部署，再完整整理其脚本依赖。

新项目统一 Token 位置的例子：

```bash
uv run --frozen python generate_openapi.py projects/new-service/curls --token-path /data/access_token
```

已配置好身份和凭据的项目，生成后可直接检查草稿：

```bash
uv run --frozen python server.py --config projects/insurance-tools/draft/config.draft.yaml --check
```

当前真实 Ark 配置仍缺地址和凭据，必须填好才能通过此检查。缺少真实接口编号等业务参数也仍需补齐，生成器不会猜测这些值。

不传输入目录时读取当前工作目录的 `curls/`。旧的单文件入口、`--name` 和 `--output` 已删除。只有一个接口时，也将它放入 `curls/tool_name.txt`。

生成器不会发网络请求。批量流程为：

```text
curls/tool_name.txt
    ├─ 方法、路径和 body → OpenAPI paths，operationId = tool_name
    └─ 真实 URL          → YAML operations.tool_name.url
```

同一个 POST 路径出现两次会报错，即使主机不同，因为当前封装按方法和路径识别操作。所有输入校验通过才写出草稿；任意一个输出文件已存在就拒绝生成，保护人工修改。新增接口可放到一个新的输入目录中，只生成新增接口草稿，再按 operationId 合入正式文件；不自动覆盖或合并已编辑内容。

生成后需要人工完成：

1. 检查字段类型，补充描述、必填项、默认值、枚举和业务限制。单个样例不能推断这些含义，草稿不设置字段 `required/default/enum`；`null`、空数组和空对象会提示补充实际结构。
2. 检查自动复用的 `inject_body` 和已移除的参数；新接口需确认哪些字段由服务端提供。未显式配置的普通样例值不会自动成为默认值，也不会自动猜测哪些字段需要隐藏。
3. 已自动关联的鉴权无需重复填写；对剩余 `auth: 待填写` 改为 `{curl: auth_curls/xxx.txt, token_path: /access_token}` 或实际的 `脚本.py:函数名`；只有确认无需鉴权时才改为 `null`。原 cURL 的 Token、Cookie、用户名密码不会复制到草稿，也不能用于推断 Token 获取与刷新逻辑。未填写鉴权的草稿无法通过启动检查。
4. 新项目检查完成后，将两份草稿采用为项目目录中的 `openapi.json`、`config.local.yaml`，并把 YAML 的 `openapi` 改成 `openapi.json`。已有项目则只合入需要的操作，保留正式描述和配置。鉴权 cURL 或脚本放在同一项目目录内，路径相对于 YAML 解析。
5. 在 `.env` 指定正式 YAML，填写身份和凭据，执行 `server.py --check`，通过后再启动或由 stdio 客户端拉起。

运行时的数据链路：

```text
.env → config.local.yaml → openapi.json → FastMCP 发布工具
工具名 + 业务参数 → 对应 operationId → YAML 同名配置
    → 获取本次 Token → 替换 ${token} 并注入字段 → 真实 URL → 原样返回业务 JSON
```

`curls/` 和草稿目录只是导入素材与候选结果，服务启动不会扫描它们；运行读取的是 `.env` 选定的 YAML、它引用的 OpenAPI，以及配置引用的鉴权 cURL 或脚本。多个接口独立成为工具，不自动安排先后调用或在工具之间传递数据。

输入支持常见的单引号/双引号、参数之间的反斜杠换行，以及：

- URL 直接填写，或用 `--url`；`-X POST` / `--request POST` 可省略，带 body 时按 POST 处理。
- `-d` / `--data` / `--data-raw` / `--data-binary` / `--json`，一次只填一个内联 JSON 对象。
- `-H` / `--header`，以及常见的 `--location`、`--compressed`、Cookie、用户凭据、超时等复制项。

**脚本只解析文本，不执行 shell、不发请求、不读取 `@file`。** 真实 URL 只写入 YAML，OpenAPI 保持内部占位地址。含 `${token}` 或 `${env.NAME}` 等显式占位符的 Header 会保留到 YAML 的 `headers`；body 中显式占位符所在字段会移到 `inject_body`，不暴露给模型。含占位符的数组作为一个整体注入。普通 Header、Cookie、现成凭据及网络选项不会导入，超时按需要填写。原始 cURL 可能包含真实凭据，请使用脱敏样例。

当前不支持单个文件内多条 cURL、查询串、表单、文件上传、GET/path 参数、shell 变量展开、管道和 PowerShell/cmd 引号语法。未知选项或不支持的输入会明确报错，不忽略后继续生成。请求 body 不能推断响应结构；未声明 Content-Type 时需确认接口是否接受 JSON，明确声明非 JSON 类型时拒绝生成。

解析使用 Python 标准库 `shlex/argparse`，Schema 推断使用 [GenSON](https://github.com/wolverdude/GenSON)。cURL 参数语义参考 [官方手册](https://curl.se/docs/manpage.html)。

业务响应只检查 HTTP 状态和 JSON 格式，JSON 内容原样返回；不要求包含 `code`，也不判断它是否为 `0`。请求不全局添加追踪字段；`policy_parse` 的上游要求 `trace_id`，已在该操作的 `inject_body` 中显式配置 `trace_id: ${trace_id}`。保留项目配置中的身份、会话和时间字段注入。

## 补充请求字段

`inject_body` 直接按请求 JSON 的结构填写，普通值原样写入：

```yaml
inject_body:
  session_id: ${session_id}
  source: askbob
  user_action: write
  action_scenario: customerSearch
  extra_input_params: {}
  user_id: ${env.MCP_AUTH_SUBJECT}
```

- `${env.变量名}`：从启动时读取的 `env` 字典取字符串；缺失或空白值在启动检查时报错。
- `${token}`：本次鉴权结果，只有该操作配置了 `auth` 才能引用；不写入进程环境或 `.env`。
- `${trace_id}`：本次调用生成的独立 UUID，只有配置引用时才发给上游。
- `${session_id}`：本次调用生成的 UUID，并非跨调用共享的对话会话。
- `${time_utc8}`：本次调用的 UTC+8 时间，格式为 `YYYY-MM-DD HH:MM:SS`。
- 普通字符串、数字、布尔值、空值、数组和对象保持 JSON 类型。

body 占位符只支持完整字段值，不支持字符串拼接或表达式；包含 `${` 却不符合上述格式的配置会报错。数组内也可以使用占位符，取出的环境变量值不会再次展开。

嵌套对象按层级合并，保留请求中未配置的字段；同名标量、数组及显式空对象 `{}` 由配置覆盖。嵌套目标原来不是对象时会报错。比如补充工号和时间，同时保留模型提供的查询条件：

```yaml
inject_body:
  extra_input_params:
    policySearchParseArgs:
      currentTime: ${time_utc8}
      agentCode: ${env.MCP_AGENT_NUMBER}
```

固定的数据源属于部署配置，不交给模型选择：`faq_search` 注入 `source: askbob`，`product_retrieve` 注入 `source: product_wiki`，`benefit_search` 注入 `source: quanyi_wiki`。三套 YAML 均通过 `inject_body` 补充；三套 OpenAPI 和工具调用样例都不包含该输入参数。业务 cURL 样例仍保留 source，因为它展示的是实际发给上游的完整请求。批量生成器复用正式配置的注入规则，会自动从工具 schema 中移除 source，无需修改生成器或增加环境变量。

```yaml
operations:
  benefit_search:
    # 其余配置省略
    inject_body:
      source: quanyi_wiki
```

字段名直接写，不使用 `/xxx/yyy` 路径。旧的 `source/value/name` 取值配置已删除。这里是本项目的配置语法，不是 OpenAPI 标准。

## cURL 鉴权与 Token 传递

鉴权直接写在对应操作内：

```yaml
operations:
  policy_query:
    url: https://business.example/query
    auth:
      curl: auth_curls/policy_query.txt
      # 从鉴权响应中提取，固定绑定为本次调用的 ${token}
      # 不写入 .env，不在不同调用之间共享
      token_path: /data/access_token
    headers:
      # 左边是业务 Header 名；右边是上面 auth 提取的结果
      token: ${token}
```

`token_path` 使用 JSON Pointer：`/data/access_token` 表示响应 JSON 的 `data.access_token`；数组可用 `/data/0/token`，键中的 `/` 和 `~` 分别写 `~1`、`~0`。当前 Ark 项目实际配置为 `/access_token`。

`auth_curls/policy_query.txt` 的 Ark 模板：

```bash
curl --request POST '${env.ARK_TOKEN_URL}' \
  --url-query 'client_id=${env.ARK_CLIENT_ID}' \
  --url-query 'client_secret=${env.ARK_CLIENT_SECRET}' \
  --url-query 'grant_type=待填写' \
  --url-query 'invokeInterface=待填写'
```

固定参数可以直接写在 cURL 中；凭据引用 `.env`。鉴权 cURL 只允许 `${env.NAME}` 变量，不能引用尚未产生的 `${token}`。请求在程序内部解析和构造，不执行 shell；查询、表单参数在替换后编码，凭据里的 `&`、`=` 等不会变成额外参数。

支持 GET（无 body）和 POST、URL 查询串、`--url-query name=value`、JSON body（`--json` 或 JSON Content-Type 加 `-d`）、表单（`--data-urlencode name=value` 或表单 `-d`）、Header、显式 `-u user:password` Basic Auth。JSON body 里的变量必须占据整个值，Header 可写 `Bearer ${env.KEY}`。不支持 shell 管道、文件读取、`-k`、`-L`、cURL 独立超时；操作的 `timeout_seconds` 同时约束鉴权和业务请求。未知参数会报错。

鉴权成功后可以放到不同位置：

```yaml
headers:
  Authorization: Bearer ${token}
# 如果接口要求 Token 在 body 中，改用或按需增加：
inject_body:
  credentials:
    access_token: ${token}
```

不再自动注入默认 Token Header，旧的 `auth_header/auth_prefix` 配置已删除，必须明确写出放置位置。Header 允许前缀拼接，body 按 JSON 类型和结构注入；不支持表达式或二次展开。请求 URL 不支持 `${token}` 替换。

本版 cURL 鉴权每次调用都会重新请求 Token，不缓存、不读取有效期、不按业务 `code` 判定成功。只接受 HTTP 2xx、合法 JSON，以及 `token_path` 中的非空合法 Token 字符串；任何一步失败就停止，不请求业务接口、不复用旧 Token，错误中不返回响应正文或凭据。

业务导入样例也可直接标记位置：

```bash
curl https://business.example/query \
  -H 'Authorization: Bearer ${token}' \
  --json '{"query":"查询样例","user_id":"${env.MCP_AUTH_SUBJECT}"}'
```

批量生成器会保留 Header 引用，并将 `user_id` 移到 YAML 的 `inject_body`；OpenAPI 只暴露 `query`。鉴权关系优先复用已有配置，新工具按同名 `auth_curls` 文件约定关联；响应 Token 位置仍需明确指定。多个工具可显式引用同一个鉴权 cURL，但各次调用独立获取 Token。

## 自定义脚本鉴权

需要签名、多步请求或特定缓存规则时，可以选择脚本方式：

```yaml
auth: auth.py:get_token
headers:
  Authorization: Bearer ${token}
```

```python
async def get_token(env: dict[str, str]) -> str:
    return env["API_TOKEN"]
```

函数名由项目自定。函数接收启动配置字典的副本，返回 Token 字符串，结果同样绑定为本次调用的 `${token}`。多个函数可放在同一个文件，多个工具也可共用函数。脚本支持项目内相对导入；每个服务实例有独立模块空间，关闭时卸载。脚本自行决定是否缓存；加载模块时不要发请求。明确不鉴权的操作写 `auth: null`，此时不能引用 `${token}`。

## 已配置的操作与来源

| operationId | 原 HTTP 路径 | 鉴权配置 |
| --- | --- | --- |
| product_parse | /product_query_parse | `auth_curls/product_parse.txt` |
| product_retrieve | /chunk_context_search | `auth_curls/product_retrieve.txt` |
| faq_search | /faq_context_search | `auth_curls/faq_search.txt` |
| benefit_search | /service_benefit_search | `auth_curls/benefit_search.txt` |
| customer_parse | /llm_ai_agent/client_search_query_parse_no_encipher | `auth_curls/customer_parse.txt` |
| customer_query | /api/v1/customer-search/search | `auth_curls/customer_query.txt` |
| customer_detail | /api/v1/customer-search/detail-info | `auth_curls/customer_detail.txt` |
| policy_parse | /api/v1/policy-search/policy-search-parse | `auth_curls/policy_parse.txt` |
| policy_query | /api/v1/policy-search/query | `auth_curls/policy_query.txt` |
| policy_detail | /api/v1/policy-search/detail | `auth_curls/policy_detail.txt` |

URL 来源：原 `llmtracing/integrations/insurance-tools-mcp/app/conf/tool/tool_config_dev_args.yaml`。参数基线来自原 `insurance-qa-agent/docs/接口文档/mcp迁移基线-v1` 的静态盘点，已保留独立请求快照，运行不依赖原仓库。

工具名不是上游 `invokeInterface` 的实际值；必须填写部署方提供的标识，不能根据表格猜测。`MCP_AUTH_SUBJECT` 用于客户解析的 `user_id`，与 `MCP_AGENT_NUMBER` 的关系也需按业务身份确认。

保留原始 HTTP 参数结构：客户详情 `clientMainIdSet`、保单查询 `filter`；`agentNo`、`agentno`、`empno` 等由可信配置注入。每个 HTTP 操作独立发布，未复制原 MCP 的解析到查询字段转换、尾号定位、候选选择和 facts/evidence 包装。

## 新建另一个项目

1. 在 `projects/<项目名>/` 准备 `openapi.json` 和 `config.local.yaml`。
2. OpenAPI 每个 `operationId` 必须对应 YAML 中同名的 `operations` 项。
3. 准备鉴权 cURL（复杂情况编写脚本），在 YAML 配置 `auth`，通过 `headers` 或 `inject_body` 引用 `${token}`；Token 与模型业务参数不要混入同一 Schema。
4. 修改根 `.env` 的 `MCP_CONFIG`，填写新项目需要从 `env` 获取的值；固定参数可直接写在鉴权 cURL 或脚本中。
5. 执行 `server.py --check`，通过后重启服务或 MCP 客户端。

无需为普通接口新增 Python 工具函数。当前支持固定路径业务 JSON POST、cURL 响应提取 Token 或 Python 函数返回 Token，以及批量 JSON POST cURL 生成关联的 OpenAPI/YAML 草稿。尚未实现外部命令鉴权、请求体签名、文件上传、业务 GET/path 参数、外部/递归请求 Schema 引用。

## 本地 mock 鉴权完整流程

没有真实 Ark 凭据时，在本目录执行：

```bash
.venv/bin/python mock_demo.py --test
```

自动启动本地 mock 上游，通过真实 `server.py` 和 MCP stdio 调用全部 10 个工具，验证获取 Token → `/access_token` 提取 → `${token}` 注入 Header → 业务接口校验 Token 的链路；同时验证错误凭据阻断业务调用、业务接口拒绝无效 Token。完成后退出并关闭服务。

要在自己的 MCP 客户端里交互测试，执行并保持运行：

```bash
.venv/bin/python mock_demo.py
```

这会启动 mock 上游（`127.0.0.1:8765`）和真实 MCP HTTP 服务（`127.0.0.1:8766/mcp`）。将 `.mock/insurance-tools/client-configs/mcp.client.http.json` 内容加入客户端即可。端口占用时可使用 `--upstream-port`、`--mcp-port` 指定其他端口；Ctrl+C 停止服务。

脚本从 insurance-tools 正式配置和 OpenAPI 生成 `.mock/insurance-tools/` 下的测试副本，保留工具参数和注入规则，替换上游地址、鉴权凭据及接口标识。所有凭据均为 mock 值，无需填写真实 `.env`。业务响应会明确标记 `mock: true`，并返回收到的请求体供检查；这验证接线与鉴权机制，不代表真实 Ark 或业务接口已通过测试。`.mock/` 可删除，重新运行会生成；不要同时运行多个 demo 实例，因为它们使用同一输出目录。

## 验证

```bash
uv run --frozen python -m pytest -q
```

测试直接加载正式 `config.local.yaml`，在测试副本中将业务 URL 指向模拟上游，不维护第二份项目配置。独立测试样例存放在 `tests/fixtures/`。

覆盖 10 类 HTTP 请求逐字段对照（仅 policy_parse 显式注入必需的 trace_id）、业务 JSON 原样返回、默认值、身份覆盖拒绝、Ark 参数编码、每次刷新和并发 Token 隔离、鉴权失败阻断、错误脱敏、超时、任意 cwd 启动、`.env` 路径与优先级、缺失凭据报错、真实 stdio/HTTP MCP 协议连接，以及批量导入、生成配置关联、路径冲突、草稿鉴权阻断、Schema 推断和生成文件保护。集成测试使用本机临时 HTTP 服务，不访问原 dev 地址。

实现参考：[FastMCP 服务启动](https://gofastmcp.com/docs/deployment/running-server)、[python-dotenv](https://bbc2.github.io/python-dotenv/)。实际运行以 `uv.lock` 锁定版本为准。
