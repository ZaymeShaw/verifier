# Verifier JEV 分类工作流

基础输入文件 → 转化脚本 → 加工后输入（含 state）→ 与 JEV 模板组合 → JEV 请求体文件 → curl 调用 JEV → 分类结果。

本目录是 Verifier 专用分类工作流，不依赖 verifier 服务。`pipeline.py` 加工材料、生成请求体并通过原生 curl 请求 JEV，通用组装器位于上一级 `scripts/jev_build_requests.py`。发送逻辑在 pipeline 内，不需要单独的发送脚本。

## 安装与运行

输入文件和字段字典直接放在工作流根目录：

```text
verifier-jevcls/
├── evaluations.xlsx       # INPUT_PATH：评测 Excel
├── materials.json         # MATERIALS_PATH：原始材料
├── materials-map.json     # MATERIALS_MAP_PATH：字段字典
├── .env
├── pipeline.py
├── templates/
└── output/                # 加工、请求体和分类结果
```

当前本机文件是已验证过的两条真实样本，材料字段字典只是本次样本的取值配置；正式使用时替换为自己的材料及字典。
这两个本机数据文件已加入 Git 忽略。输入也可以使用其他名称、格式或目录，修改 `.env` 对应路径即可。

需要 Python 3.11+ 和 PATH 中可用的 curl。在本目录执行：

```sh
python -m pip install -r requirements.txt

# 首次使用：本目录没有 .env 时复制，然后配置输入、材料、字段字典、模板和输出路径
cp -n .env.example .env

# 使用自带的合成加工样例检查模板组装
python ../jev_build_requests.py --input example-processed.jsonl \
  --template templates/answer-classification.json --output-dir output/example

# 配好 .env（含连接地址、key 和模型）后，一次完成加工、组装、发送和结果保存
python pipeline.py
```

pipeline 只读取本工作流目录的 `.env`，所有相对路径均以该目录为基准，也支持绝对路径和 `~/`。
不读取父目录 `.env` 或进程环境变量，不进行变量插值；缺少必填配置或文件不存在时报错。
工作流入口不接收路径 CLI 参数。底层转化器和通用组装器仍可独立通过 CLI 使用。
pipeline 用当前 Python 解释器调用上一级组装器，可从任意目录用脚本绝对路径启动。
`OUTPUT_DIR=output` 使用固定输出目录。每次先在临时目录完成加工和校验，成功后整体替换旧输出，并删除旧批次残留文件；加工或校验失败时保留上一批结果。输出目录不能包含输入文件、模板、字段字典或工作流代码。
连接配置在加工前检查。请求体生成成功后覆盖旧输出，再开始逐条发送；发送失败时保留本次请求体、原始响应和已完成结果，返回非零退出码。不会恢复旧批次、自动重试或继续发送后续条目。重新运行会覆盖输出并重新发送整批。
仅离线加工时使用下文的两个底层脚本，无需密钥。

## 文件职责

### 工作流配置

本目录 `.env` 保存全部文件路径、模板选择和本机连接配置，已加入 Git 忽略；`.env.example` 是可提交的无密钥样例。
复制工作流后可执行 `cp .env.example .env`，设置下列文件路径及连接配置；运行 pipeline 必须填写 `JEV_API_KEY`。

| 配置 | 含义 |
|---|---|
| `INPUT_PATH` | 可选，Verifier 评测 Excel；留空或不配置时不关联评测结果 |
| `OUTPUT_DIR` | 必填，固定输出目录；推荐 `output`，每次成功后整体覆盖 |
| `MATERIALS_PATH` | 原始材料文件，与字段字典同时填写；没有评测 Excel 时必填 |
| `MATERIALS_MAP_PATH` | 材料字段字典 JSON，与材料同时填写；没有评测 Excel 时必填 |
| `JEV_MODEL` | 必填，最终使用的 JEV 模型名，覆盖模板中的 model；例如 `jev-latest` |
| `JEV_TEMPLATE_PATH` | 必填，标准 JEV 模板路径；相对路径以本工作流目录为基准 |
| `EVAL_AXES_SCOPE` | `main`：仅主要展示；`all`：全部展示分组。默认 `main` |
| `EVAL_TAGS_SCOPE` | `bad`：仅问题 tag；`all`：全部成功轴结论。默认 `bad` |
| `JEV_API_URL` | 必填，完整请求地址；当前网关为 `https://emrank.tech/v1/decisions`，直接使用，不拼接路径 |
| `JEV_API_KEY` | 必填，所用服务的 API Key，发送时放在 `Authorization: Bearer <key>` 请求头 |
| `JEV_TIMEOUT_SECONDS` | 必填，单次 HTTP 请求超时秒数，有限正数；示例为 120 |

协议与 Bearer 认证依据 [System One 官方文档](https://docs.typesafe.ai/api/system-one.md)。官方地址是 `https://api.typesafe.ai/v1/systemone`；当前网关使用 `/v1/decisions`，地址和模型均以 `.env` 配置为准。
工作流模型名由 `.env` 的 `JEV_MODEL` 决定，覆盖所选模板的 `model`。缺失或空白时报错；不会退回模板中的模型。分类标准仍放在模板 `questions` 中。原模板文件不改写。
输入、补充材料、字段字典、模板和输出路径均在本目录 `.env` 中指定。连接配置和密钥不进入模板、state 或请求体。

`pipeline.py` 读取本目录 `.env` 的文件路径、模型、筛选及连接配置。发送时只按 manifest 顺序读取请求并核对哈希；不发送模板快照。curl 使用原生客户端，不伪装 User-Agent，不跟随重定向，不自动重试；密钥通过标准输入传递，不写入命令参数、模板或请求体文件。

### 脚本与模板

| 文件 | 作用 |
|---|---|
| `verifier_excel_to_jev_state.py` | 读取评测轴结论及理由，按 trace ID 合并字段字典提取的材料 |
| `../jev_build_requests.py` | 通用组装入口，含协议校验：加工后 JSONL + 模板 → 单条标准请求文件 |
| `pipeline.py` | 串起加工、组装、curl 发送和分类结果保存 |
| `templates/answer-classification.json` | 完整 T/F1–F8 分类标签及独立的是否需要复核判断 |
| `example-processed.jsonl` | 跨业务、结构化 state 的最小合成示例 |

也可以分步运行，检查并确认加工材料后再组装。下方底层脚本独立使用时要求目标文件/目录尚不存在；日常覆盖运行使用 `python pipeline.py`：

```sh
python verifier_excel_to_jev_state.py --input cases.xlsx --output output/processed.jsonl
python ../jev_build_requests.py --input output/processed.jsonl \
  --template templates/answer-classification.json --output-dir output/requests
```

## 加工后输入约定

UTF-8 JSONL（读取允许 BOM），每行至少包含唯一非空字符串 `id` 和非空 `state`：

```json
{"id":"748b268f3f724c199471f60bdef19eb3","state":{"问题":"…","回答":"…","依据":["…"]},"source":{"file":"原始材料路径"}}
```

`state` 可以是字符串、对象或数组，其内部结构由转化脚本决定。额外元数据可放在记录顶层，组装时只有 `state` 进入请求。不做字符串占位符替换，不修改 questions，不把 ID 或 source 混入协议顶层。空 state、重复 ID、重复 JSON 键、NaN、无效模板均报错，不自动修复。

换项目时编写自己的转化脚本（本目录的 Excel 转化脚本只适配 Verifier），输出同样的 `id + state` JSONL，然后复用上一级 `jev_build_requests.py`。不需要修改通用组装器或添加项目配置层。换判断标准时修改 `.env` 的 `JEV_TEMPLATE_PATH`；独立使用通用组装器时通过 `--template` 指定。同一份加工材料可以复用。

### 不关联评测结果

在 `.env` 留空或删除 `INPUT_PATH`：

```dotenv
INPUT_PATH=
MATERIALS_PATH=materials.json
MATERIALS_MAP_PATH=materials-map.json
```

其余连接、模型、模板和输出配置不变，仍运行 `python pipeline.py`。材料及字段字典此时必填：只看问答就在字典中选择问题、回答；需要 trace 明细时再选择对应字段。`case_id_path` 指向材料里的 Langfuse trace ID，仍须非空且唯一。
不打开评测 Excel，不生成 `state.evaluations`，不使用评测筛选配置；state 只包含所选材料及材料说明。缺少评测不被加工成“回答正确”或“回答有问题”的证据。分类和复核状态仍由模型根据实际材料判断。
`INPUT_PATH` 填了非空路径就必须存在且符合评测格式，出错不会自动跳过评测。底层转换器也支持省略 `--input`，并传入 `--materials` 与 `--materials-map`。

### 当前 Excel 转化

本工作流的 case ID（加工文件中的 `id`）直接使用 Langfuse trace ID，不另设 `langfuse_trace_id` 或评测记录 ID。提供评测 Excel 时取值来自 Input / Live Request 的 `from_trace.trace_id`；不提供时按材料字典的 `case_id_path` 提取 trace ID，材料记录决定本批 case 及顺序。Excel 原 ID 仅用于表内关联，外部补充材料、加工文件、请求清单统一使用 Langfuse trace ID。缺失或重复立即报错，不用回答里的业务请求 ID、Judge 内部 trace ID 或用例名替代。

使用评测 Excel 时，转化入口要求每条记录都有明确的 `from_trace.trace_id`。只有 live 请求占位符的导出不能直接转换，需要先取得对应 Langfuse trace 并准备带该来源的输入。先前生成的以用例名为 ID 的 output 不符合当前约定，应重新生成。

Excel 只向 state 提供「评测轴汇总」的轴级结论及其 reason（「轴级说明」）。
「用例池候选区」只读取 `ID` 和 `Input / Live Request`，用于从旧 ID 映射到 Langfuse trace ID；这两个字段不会进入 state。
主表中的回答、Judge、归因、Reference、Trace 摘要以及整张「扩展轴明细」均不读取为评测材料。原始输入、输出、上下文由原始材料文件和字段字典提供。

`.env` 中两个独立筛选项取交集：

```dotenv
EVAL_AXES_SCOPE=main
EVAL_TAGS_SCOPE=bad
```

- `EVAL_AXES_SCOPE=main`：只选「展示分组」为「主要展示」的轴；`all` 包含「其余分析」。
- `EVAL_TAGS_SCOPE=bad`：只选「是否问题 tag」为「是」的轴；`all` 不按问题标记筛选。
- 仅选择运行状态 `succeeded` 的轴；每条保留 `axis_id`、`tag`、`verdict` 和 `reason`。`reason` 来自「轴级说明」，原文保留，不读取扩展明细。空说明保留为 null 或空字符串，不生成理由；同标签的不同理由不会被去重丢弃。
- `bad` 依据导出时已有的问题 tag 标记，不根据 case 整体成功/失败或判定文字猜测。
- 缺工作表、必需列或无效筛选值会报错，不退回读取主表的 tags。
- 每条 case 都保留：筛选后没有 tag 则输出空数组，不能据此判为 T。

输出形式：

```json
{"evaluations":{"description":"已有评测轴结论及理由，供参考，不作为原始事实或最终分类","filters":{"axes_scope":"main","tags_scope":"bad","run_status":"succeeded"},"value":[{"axis_id":"truthfulness","tag":"[truthfulness:refuted]","verdict":"refuted","reason":"回答中的数值与提供的依据不一致"}]}}
```

### 原始材料与字段字典

用户提供原始材料，脚本按字段字典提取；旧的 `{id, materials}` 专用输入约定已移除。
支持 JSON（单个对象或对象数组）、JSONL（每行对象）、UTF-8 CSV、XLSX。
同时提供材料和评测 Excel 时，两者的 Langfuse trace ID 集合必须完全一致：缺少、多出、重复或空白 ID 都报错，不按行号关联。
不提供材料时可以只加工 Excel，`state.materials` 为 null。

字典见 `examples/materials-map.json`，原始材料见 `examples/materials.jsonl`：

```json
{
  "case_id_path": "/trace_id",
  "fields": {
    "user_input": {"path": "/request/question", "description": "本轮用户问题"},
    "answer": {"path": "/response/answer", "description": "最终展示给用户的回答"},
    "history": {"path": "/request/history", "description": "历史对话", "required": false}
  }
}
```

路径使用 [JSON Pointer（RFC 6901）](https://www.rfc-editor.org/rfc/rfc6901)，由 `jsonpointer` 库解析。
`/messages/0/content` 读取数组第一条消息；字段名中的 `/` 转义为 `~1`，`~` 转义为 `~0`。
CSV/XLSX 按列名取值，如 `/用户问题`。CSV 值保留字符串；XLSX 保留 JSON 可表示的标量，拒绝公式、错误单元格及所选字段中的日期等非 JSON 类型，需先明确转换。
表格单元格中的 JSON 文本不会自动解析，嵌套材料建议用 JSON/JSONL。
多工作表 XLSX 必须在字典顶层指定 `"sheet": "材料表"`，单工作表可省略。

字段默认 `required: true`，路径缺失报错。可选字段缺失输出 `present: false, value: null`；存在但值为 null 输出 `present: true, value: null`。
对象、数组、数字、布尔值、空字符串原样保留。`state.materials` 的字段形式为：

```json
{"user_input":{"description":"本轮用户问题","present":true,"value":"缴费日期是什么时候？"}}
```

筛选后的轴级结论和理由放入 `state.evaluations.value`，同层保存筛选条件与描述。
实际输入、输出和上下文放入 `state.materials`；加工阶段不消除冲突或生成分类。

在 `.env` 中配置：

```dotenv
INPUT_PATH=evaluations.xlsx
MATERIALS_PATH=materials.json
MATERIALS_MAP_PATH=materials-map.json
JEV_TEMPLATE_PATH=templates/answer-classification.json
JEV_MODEL=jev-latest
OUTPUT_DIR=output
```

然后执行 `python pipeline.py`。提供评测 Excel 且不使用补充材料时，可将两个 `MATERIALS_*` 配置同时留空。
独立使用底层 `verifier_excel_to_jev_state.py` 时仍可传入 `--materials` 和 `--materials-map`；底层脚本 CLI 相对路径以当前工作目录为准。
输出另存 `materials-mapping.json` 字典快照；`processed.jsonl` 保存本次实际提取的描述和值。

## 输出

```text
output/
├── processed.jsonl
├── materials-mapping.json   # 配置了字段字典时生成
├── classification-results.json
├── classification-results.xlsx  # 最终三列表格：traceid、标签、待复核分数
├── responses/              # 每条 HTTP 原始响应；错误响应也保留
│   ├── 000001.json
│   └── 000002.json
└── requests/
    ├── 000001.json
    ├── 000002.json
    ├── ...
    ├── template.json
    └── manifest.json
```

requests 下每个数字命名文件都是直接 POST 到 `JEV_API_URL` 的 JSON body。`manifest.json` 记录 ID → 请求文件及内容哈希，消费程序必须按该清单读取，不能将整个目录的 JSON 都发送。`template.json` 是应用模型配置后的有效模板快照，空 state 不可直接发送。manifest 记录加工输入和原模板文件的 SHA-256，以及实际请求的 model，便于核对来源。独立使用通用组装器时可用 `--model` 覆盖模板模型；不传则使用模板值。

整批请求成功后，最终输出 `classification-results.xlsx`，包含 `traceid`、`标签`、`待复核分数` 三列。traceid 为原始 Langfuse trace ID，以文本保存；标签是模板返回的完整文字（例如 `T:回答正确`、`F4:知识缺失`）。复核列直接保存独立的 `needs_review.noul` 原始分数（0–1 数值），显示两位小数，不按阈值转成“是/否”。分数不是经人工校准的准确率。调用失败时仅保留 JSON 和原始响应，不生成不完整的最终表格。重跑会覆盖固定输出目录中的表格。

## 协议与分类边界

字段类型依据 [TypeSafe System One 官方 OpenAPI](https://docs.typesafe.ai/api/system-one.md)，核对日期 2026-11-11。当前工具支持标准文本请求的 `model/state/questions`，问题类型 Choice、Noul、Score，支持结构化 instructions/criteria。图片 assets、Box 和 multipart 不在本工具范围，明确拒绝。未知协议字段（如 decode、builder）也拒绝。`state` 内部和加工记录顶层的业务字段不受此限制。

这是一份标准协议子集的本地结构校验，不替代服务端的模型可用性、token 预算或实际准确率验证。文件生成不检查服务端模型别名是否存在。示例 `JEV_MODEL=jev-latest` 使用服务端模型别名；固定模型实验时请修改 `.env` 的 `JEV_MODEL` 并保存实际响应 model。模型名必须由你配置的服务支持。

分类模板包含两个独立问题：

- `classification`（Choice）：从 `T:回答正确`、`F1:大模型无法回答`、`F2:答非所问`、`F3:回答内容错误`、`F4:知识缺失`、`F5:回答内容不合规`、`F6:错别字原因`、`F7:可能是上下文问题`、`F8:其他bad原因` 中选择一个完整标签，保存原始 probabilities/confidence。
- `needs_review`（Noul）：是否存在需要人工或更多 trace/原始依据确认的关键不确定性。true 对应需要复核，false 对应现有材料足够；缺少评测文件本身不是复核理由。复核判断不是 badcase 分类，已确认的错误也可能无需进一步复核。它取代原来的可判定性问题，不重复设置两个复核项。需复核时分类仍是候选，不能视为确定标签。

JEV 的问题彼此独立，不能把另一个问题的答案作为本问题输入。最终是否采纳候选由后续消费者处理。工作流已接入模型网络调用和结果整理，不回填 Excel。

`classification-results.json` 是按发送顺序保存的结果数组，`id` 仍为 Langfuse trace ID。每条包含 `success`、HTTP 状态、请求哈希、响应文件路径和耗时。成功项另含 `classification`、`needs_review_score`（原始分数）、实际 `model`、完整 `answers`（保留 confidence/probabilities）及 `usage`。`success=true` 表示调用成功且分类选项有效，不代表分类已确认；复核倾向看 `needs_review_score`，不自动二值化。失败项仅记录错误，不填分类值；数组后未出现的 case 尚未发送。HTTP 200 但缺少合法分类答案或 0–1 范围内的复核分数也算失败。当前分类工作流要求模板含 `classification`（Choice）和 `needs_review`（Noul）；其他场景的模板组装使用通用组装器。

复制本工作流到其他位置时，需要保留 `../jev_build_requests.py` 的相对关系。通用组装器只依赖 Pydantic，可单独复制使用；Excel 转化脚本只依赖标准库和 openpyxl，不导入组装器。

当前分类定义是待业务验证的初稿：F4/F6/F7 要求具体原因证据，F8 不代表未知，多问题按核心任务影响选择主类。F5 没有无条件优先规则。评测未兑现不自动等同于回答错误，正确拒答或对象不存在可能是 T。

## 验证

在仓库根目录执行 `python -m pytest tests/test_verifier_jevcls_pipeline.py -q`（开发环境需 pytest）。覆盖请求隔离、非法输入拒绝、跨业务 state、Excel 关联与失败时不发布输出。另覆盖 curl 调用边界、逐条结果保存、失败停止、超时与无效响应拒绝。自动测试模拟网络，不代表真实服务可用性或分类质量已验证。
