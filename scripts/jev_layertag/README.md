# JEV 问题业务标签分类

为原始问题选择业务标签，输出完整的场景、子场景和三级领域路径。不依赖评测 Excel，不读取当前回答或 T/F 分类结果。问题 ID 原样保留；来源是 Langfuse 时可直接使用 trace ID，与其他工作流按 ID 关联。

## 工作流及文件关系

```text
问题材料 + 字段字典
  → questions_to_state.py
  → output/processed.jsonl（id + state + source）
  + templates/layer-tagging.json（标准 JEV 模板）
  → ../jev_build_requests.py
  → output/requests/（请求体、有效模板、manifest）
  → pipeline.py 中的 curl 发送与响应校验
  → output/classification-results.json

标签 Excel → taxonomy_to_template.py → templates/layer-tagging.json
```

`pipeline.py` 是完整入口，默认实际发送请求。`--prepare-only` 明确只加工和生成请求，不发送。标签 Excel 转模板是独立维护步骤，不在每次分类时重新生成或覆盖模板。

与 `../verifier-jevcls` 采用相同的文件分层、本目录 `.env`、固定输出目录及 manifest 发送方式。唯一上级代码依赖是通用组装器 `../jev_build_requests.py`；不导入 Verifier 的业务转换脚本，不依赖 verifier 服务，也不改变原工作流。

```text
jev_layertag/
├── .env.example
├── .env                         # 本机配置，不提交
├── requirements.txt
├── pipeline.py
├── questions_to_state.py
├── taxonomy_to_template.py
├── templates/layer-tagging.json
├── examples/
│   ├── questions.jsonl           # 四条明确标识的合成问题
│   └── questions-map.json
└── output/                      # 运行产物，不提交
```

复制目录时需要保留上级 `jev_build_requests.py` 的相对位置。依赖版本沿用现有工作流，没有增加第三方包。

## 安装和运行

需要 Python 3.11+ 和 PATH 中的 curl。在本目录执行：

```sh
python -m pip install -r requirements.txt
cp -n .env.example .env
# 编辑 .env，设置输入、字段字典、模型及服务连接信息

python pipeline.py --prepare-only
python pipeline.py
```

也可以从任意目录使用 `pipeline.py` 的绝对路径运行。仅加载本目录 `.env`，不读取父目录 `.env` 或进程环境变量，不插值配置值。所有相对路径以本目录为基准，支持绝对路径和 `~/`。

| 配置 | 用途 |
|---|---|
| `INPUT_PATH` | 问题输入：JSON、JSONL、CSV 或 XLSX |
| `INPUT_MAP_PATH` | JSON Pointer 字段字典 |
| `JEV_TEMPLATE_PATH` | 完整标准 JEV 模板 |
| `OUTPUT_DIR` | 固定输出目录，成功加工后整体替换旧批次 |
| `JEV_MODEL` | 必填，覆盖模板 model；不回退到模板值 |
| `JEV_API_URL` | 完整 POST 地址，直接使用，不拼接路径 |
| `JEV_API_KEY` | Bearer 密钥，仅发送时使用 |
| `JEV_TIMEOUT_SECONDS` | 请求超时秒数，必须为有限正数；样例为 300 |

默认样例使用现有工作流的网关地址和模型名，服务可用性以实际响应为准。正式运行会把选中的问题、历史和完整标签定义发送到 `.env` 指定的服务；先确认该服务获准处理这些材料。本地 `.env` 和 output 都被忽略。其他自有输入文件应自行放到受控且不会提交的位置。

加工失败时保留上一批输出。加工完成后发布本批请求，再逐条发送；网络、HTTP 或响应校验失败时记录错误并停止，保留原始响应和已完成结果。没有自动重试、断点续跑或备用服务。再次运行（包括 `--prepare-only`）会覆盖本目录本批输出；需要保留的批次应先另存。

## 输入与字段字典

示例原始记录：

```json
{"id":"case-001","question":"这款产品的佣金怎么算？","history":[]}
```

字段字典沿用现有工作流的 `case_id_path + fields` 形式：

```json
{
  "case_id_path": "/id",
  "fields": {
    "user_input": {"path": "/question", "description": "本轮用户问题"},
    "history": {"path": "/history", "description": "消解本轮指代所需的历史对话", "required": false}
  }
}
```

`user_input` 必须为非空文本，`history` 可为文本、消息数组或 null，也可不配置。字段白名单只有这两项；未选中的回答、评测字段和其他元数据不会进入 state。调用者应把 history 限定为本轮之前的相关历史，避免把当前回答或评测意见混入历史。

字段默认必需，可选字段缺失时保留 `present: false, value: null`，显式 null 为 `present: true`。ID 必须是非空、无首尾空白且批内唯一的字符串，不用行号代替。字段描述来自字典，本轮内容来自材料。

JSON Pointer 使用现有 `jsonpointer` 库：例如 `/request/question`、`/messages/0/content`，字段名中的 `/` 写作 `~1`，`~` 写作 `~0`。CSV/XLSX 可直接用 `/用户问题` 等列名；多工作表 XLSX 必须在字典顶层指定 `"sheet": "问题表"`。

JSON 文本单元格不自动解析，结构化历史建议使用 JSON/JSONL。XLSX 的公式或错误单元格被拒绝；所选日期等非 JSON 类型需要先明确转换。重复 JSON 键、NaN、重复 ID、空问题等均报错，不静默跳过。

加工记录的 `source` 保存输入文件、来源行号和内容哈希，保留在本地。只有 `state` 会进入标准请求体；ID 通过 manifest 与响应关联，不混入 JEV 协议顶层。

## 标签字典和模板

初始模板来自本聊天复原的《万能营销意图聚类及标准》工作表，记录源文件名、工作表和 SHA-256。61 行明细按完整五级路径合并成 **48 个业务标签**。每个标签的 `scope` 是其全部明细条目的集合，不把每条明细再当作一个新标签。

模板 `questions.classification.criteria` 是运行时唯一的标签定义来源。每个业务选项保存：

- `path`：场景、子场景、一级领域、二级领域、三级领域。
- `scope`：覆盖范围。
- `source_rows`：来源行号。
- `review_required`：标签定义是否仍有待核对内容。

ID 为完整路径的 SHA-256 前 16 位加 `tag_` 前缀；行重排或明细修订不改变 ID，路径改名会改变 ID。Excel 导入器只展开实际的纵向合并单元格，不把普通空白擅自向下填充；不完整路径、公式、横向合并会报错。照片复原文件使用 `FFF2CC` 填色表示文字待核，该标签的 `review_required` 会设为 true。普通 Excel 导入后仍需要业务确认标签定义，颜色不是自动完成业务审查的证明。

重新导入已确认的标签 Excel：

```sh
python taxonomy_to_template.py \
  --input taxonomy.xlsx --sheet '问答陪练-意图（复原）' \
  --output templates/layer-tagging-reviewed.json \
  --model 'typesafe/jev-1.13.0[slow]'
```

检查新模板后，将 `.env` 的 `JEV_TEMPLATE_PATH` 指向它。生成器不覆盖已有文件。也可以直接维护完整模板，保持 path、scope 和 review_required 一致；确认定义后明确将该标签的 review_required 改为 false。生成后的模板是实际运行依据，修改 Excel 不会悄悄改变既有模板。

本工作流仍使用标准 `model/state/questions` 请求，没有自定义协议顶层字段。使用一个 Choice 选择完整末级标签，不单独让模型预测各层。Choice 的 criteria 支持结构化定义及最多 255 项，见 [TypeSafe System One 文档](https://docs.typesafe.ai/api/system-one.md)；当前 48 个标签加 3 个处理状态共 51 项，由上级组装器执行协议结构校验。

额外三个选项是处理状态，不是业务标签：

| 模型选项 | 结果状态 | 含义 |
|---|---|---|
| `__review__` | `review` | 指代不明、缺必要上下文或分类边界无法区分 |
| `__out_of_scope__` | `out_of_scope` | 诉求明确但现有体系未覆盖 |
| `__multi_intent__` | `multi_intent` | 多个独立诉求，没有已有复合标签可以完整覆盖 |

单个 Choice 同时容纳标签和这些状态，避免两个独立模型问题给出互相矛盾的标签/状态。已有复合业务标签仍按其定义使用。`非行业基本知识` 已覆盖非保险知识咨询，不能仅因问题不涉及保险就判未覆盖。

## 输出和关联

```text
output/
├── processed.jsonl
├── input-mapping.json
├── label-catalog.json            # 从有效模板提取的标签快照
├── run.json                      # 来源哈希、模型、问题数、标签数
├── classification-results.json
├── responses/000001.json ...     # 原始 HTTP 响应（若服务有返回）
└── requests/
    ├── 000001.json ...
    ├── template.json             # 应用 JEV_MODEL 后的有效模板
    └── manifest.json             # id、请求文件、内容哈希
```

发送只读取 manifest 中的请求文件，并在发送前校验整批哈希，不会把模板快照作为请求发送。curl 不跟随重定向、不自动重试；密钥经标准输入传递，不进入进程命令参数或请求文件。

每条成功记录包含：原始 `id`、`classification`、`classification_status`、`candidate_label_id`、`candidate_path`、`label_id`、`path`、`review_reason`、实际模型、完整 answers（含 confidence/probabilities）、usage、HTTP 状态、请求哈希、原始响应路径及耗时。

- 选到已确认定义的业务标签：状态 `ready`，从模板还原 `label_id/path`。
- 选到仍待核对定义的业务标签：状态 `review`，原因 `taxonomy_definition_unverified`；保留候选，`label_id/path` 为 null。
- 选到三个处理状态：候选和业务标签均为 null，不伪造业务类。
- 发送失败或响应无效：`success: false`，只有错误及调用记录，不填分类。数组中尚未出现的输入没有发送。

`success: true` 表示调用和结构校验成功，`ready` 是规则上可用的模型候选，两者均不代表人工确认或准确率已验证。未配置未经校准的概率阈值；原始概率保留供后续人工验证。当前版本不生成多标签，不把多意图中的其他诉求静默丢掉，也不回填原 Excel。

## 验证

在仓库根目录执行：

```sh
python -m pytest tests/test_jev_layertag_pipeline.py tests/test_verifier_jevcls_pipeline.py -q
```

测试覆盖真实标签来源行的完整归并、输入字段隔离、合并单元格和缺失输入、模板协议、模型覆盖、结果路径、待复核处理、失败停止与已完成结果保存。网络响应在自动测试中模拟；模拟结果不用于宣称真实模型分类效果。

本机首轮检查：86 项测试通过，四条合成问题的真实请求体已生成。首次发送因沙箱无法解析服务域名而失败，后续外网执行申请被自动审批拒绝，尚未取得真实 JEV 分类结果。获准向配置服务发送标签定义和合成问题后，可直接运行完整 pipeline。
