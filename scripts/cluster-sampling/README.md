# 聚类与采样工作流

`pipeline.py` 加载本目录 `.env`，通过当前 Python 解释器依次调用 `../embed_cluster.py` 和 `../cluster_sample.py`。算法与数据读写均保留在原脚本中。没有清洗、hard 标注、场景分类或可测性判断。

## 配置与运行

使用 Python 3.11 或更高版本。首次使用，在本目录执行：

```sh
python -m pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 填好密钥（使用其他服务时同时调整地址和模型），按原大工作流的默认参数运行：

```sh
python pipeline.py
```

也可以从任意工作目录用 `pipeline.py` 的绝对路径启动，原脚本、配置文件、输入输出相对路径都不会随当前工作目录变化。

| 配置 | 环境变量 | 默认值 | 命令行覆盖 |
|---|---|---|---|
| 输入文件 | `INPUT_PATH` | `./example-input.jsonl` | `--input` |
| 输出根目录 | `OUTPUT_DIR` | `./output` | `--output-dir` |
| ID 列 | `INPUT_ID_COLUMN` | `id` | `--id-column` |
| 文本列 | `INPUT_TEXT_COLUMN` | `text`（样例）；旧题库设为 `turns` | `--text-column` |
| API 根地址 | `EMBEDDING_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `--base-url` |
| 向量模型 | `EMBEDDING_MODEL` | `qwen3.7-text-embedding` | `--model` |
| 密钥 | `EMBEDDING_API_KEY` | 无，必须配置 | 不在命令行传密钥 |
| 密钥变量名 | `EMBEDDING_API_KEY_ENV` | `EMBEDDING_API_KEY` | `--api-key-env` |
| 向量维度 | `EMBEDDING_DIMENSION` | `1024` | `--dimension` |
| 请求批量 | `EMBEDDING_BATCH_SIZE` | `20` | `--batch-size` |
| 请求超时（秒） | `EMBEDDING_TIMEOUT` | `60` | `--timeout` |
| 服务专用参数 | `EMBEDDING_EXTRA_BODY` | `{}`，不加指令 | `--extra-body` |
| 粗簇阈值 | `CLUSTER_THRESHOLD` | `0.7` | `--threshold` |
| 细簇阈值 | `CLUSTER_FINE_THRESHOLD` | `0.85` | `--fine-threshold` |
| 聚类方式 | `CLUSTER_LINKAGE` | `complete` | `--linkage` |
| 目标采样数 | `SAMPLE_TOTAL` | `1087` | `--total` |
| 采样权重指数 | `SAMPLE_ALPHA` | `0.6` | `--alpha` |
| 合并桶分档 | `SAMPLE_TAIL_BINS` | `1,3` | `--tail-bins` |
| 长尾样本占比上限 | `SAMPLE_TAIL_MAX_RATIO` | 留空，不限制 | `--tail-max-ratio` |
| 小簇大小上限 | `SAMPLE_SINGLE_MAX_SIZE` | `20` | `--single-max-size` |
| 单簇抽取上限 | `SAMPLE_CLUSTER_CAP` | 留空，不限制 | `--cluster-cap` |
| 配额取整方式 | `SAMPLE_ROUNDING` | `pps` | `--rounding` |
| 随机种子 | `SAMPLE_SEED` | `42` | `--seed` |

配置优先级：命令行 > 当前进程环境变量 > 本目录 `.env` > 默认值。相对输入、输出路径始终相对于本目录；也接受绝对路径。不自动读取仓库根目录 `.env`，不做变量插值。`.env` 与默认输出目录已忽略，不提交密钥。

所有运行参数均可在 `.env` 配置，也可用命令行覆盖。模型、维度及聚类、采样策略默认对齐 `tmp/embed_cluster_10k/qwen3.7/pipeline-0.7/` 的原运行报告；批量 20、超时 60 沿用当时 embedding 脚本默认值，历史报告未记录这两个请求参数。接口沿用当前 OpenAI 兼容协议，历史报告来自百炼原生接口；参数对齐不代表已复现全部历史向量或分簇。

`EMBEDDING_DIMENSION` 留空时不发送维度参数；`CLUSTER_FINE_THRESHOLD` 留空时关闭细簇；`SAMPLE_TAIL_BINS` 留空时不合桶；`SAMPLE_CLUSTER_CAP` 留空时不设单簇上限。对应命令行传 `''` 同样有效，未设置变量则使用表中的默认值。保持原脚本的直连行为，不继承系统代理。

默认输入仍是 12 题样例。只演示抽 5 题时运行 `python pipeline.py --total 5`；不覆盖时目标仍为原流程的 1087，实际数量受输入及可抽容量限制。

## 长尾占比上限

在 `.env` 设置：

```dotenv
SAMPLE_TOTAL=1500
SAMPLE_TAIL_BINS=1,3
SAMPLE_TAIL_MAX_RATIO=0.30
```

**长尾只指原始粗簇大小为 1 的单例桶 `tail:1`**，其样本数最多占最终实际样本数的 30%。
`SAMPLE_TAIL_BINS=1,3` 将数据分成 `tail:1` 和 `pool:2-3` 两个合并桶；后者是非长尾。
非空分档必须从 1 开始，单例须独立成桶；可以增加分档，如 `1,3,5` 增加非长尾桶 `pool:4-5`。
大簇拆出的单条细簇也属于非长尾，不因细簇大小为 1 而成为长尾。

默认分段规则：

| 原始粗簇大小 | 采样规则 | 是否计入长尾占比 |
|---|---|---|
| 1 | 单例合桶，随机选一部分 | 是 |
| 2～3 | 合桶后等概率随机选原始簇，每个选中的簇内随机抽 1 条 | 否 |
| 4～20 | 每个粗簇随机抽 1 条 | 否 |
| >20 | 按细簇拆开，每个细簇随机抽 1 条 | 否 |

两个合并桶之间仍按原始行数的 `n^alpha` 分配剩余名额。每个桶的可抽容量是原始粗簇数量，
还受 `SAMPLE_CLUSTER_CAP` 限制；每个原始簇最多抽 1 条，不按行数反复抽同一个簇。
单例桶超过占比上限的名额转给可抽的非长尾（包括 `pool:2-3`），容量不足时少抽。
30% 是上限，不保证刚好抽到 30%；固定保底数超过 `SAMPLE_TOTAL` 时仍报错。

设非长尾可抽容量为 N，上限为 r，则最终总量还受 `floor(N / (1-r))` 限制。
N 包含非长尾合并桶容量、中簇固定名额和大簇细簇固定名额，不能只算后两者。
历史的 1087 是将大小 1～3 全部算作长尾时倒推的总量；当前采用用户确认的“只有单例是长尾”定义，
不再使用历史 326/1087 作为长尾比例，迁移后应重新设置 `SAMPLE_TOTAL`。

`SAMPLE_TAIL_MAX_RATIO` 留空不限制，0 排除单例桶，1 不限制；取值为 0～1 的有限数，不能写 `30%`。
`SAMPLE_TAIL_BINS` 留空时不合桶，也没有单例桶约束。
若输入全是单例且上限小于 1，只能输出 0 条（Excel 保留表头，报告比例为 `null`）。
若输入全由大小 2～3 的粗簇组成，则长尾数量为 0，仍可正常每簇抽 1 条。
报告 `summary` 记录实际数量、单例长尾数量、非长尾数量和单例长尾占比；空结果的比例不适用。

## 输入

样例 `example-input.jsonl` 有 12 道合成题，每行至少有 `id`、`text`；`source` 等其他字段原样保留。支持 JSONL、CSV 和 XLSX（首个工作表）。使用其他列名时传入 `--id-column`、`--text-column`。JSONL 的文本列也可为字符串列表，多轮文本按换行拼接。

`.env`、JSONL 和 CSV 输入须保存为 UTF-8（允许带 BOM）；缓存及 JSON/JSONL/CSV 输出统一写为 UTF-8，不依赖 Windows 的默认 GBK 编码。Excel 输入输出仍为 `.xlsx`。若现有 CSV 是 GBK 编码，请先另存为 UTF-8 CSV 或 XLSX。

## 输出

每次直接覆盖输出目录中的同名结果，只保留一份，不创建运行子目录：

```text
output/
├── sampled.xlsx                # 最终交付：被抽中的原题及聚类、采样信息
├── clustered.xlsx              # 中间结果：全部输入题及粗簇/可选细簇，供 Excel 查看
├── clustered.jsonl             # 全部输入题及粗簇/可选细簇
├── cluster-report.json         # 模型标识、阈值、各簇成员
├── sample-report.json          # 采样参数、分段、各簇配额与实际抽取数
└── .cache/embeddings.jsonl      # 跨运行复用的向量缓存
```

`sampled.xlsx` 是可直接打开的 Excel 表格，首行为字段名并冻结表头；每行一道抽中的题，保留原题字段，并带有：

| 字段 | 含义 |
|---|---|
| `cluster_id` | 语义粗簇，例如 `c0` |
| `fine_cluster_id` | 细簇，例如 `c0.0`；只有设置细阈值才有 |
| `new_cluster_id` | 采样分组，可能是原簇、细簇，或合并桶 |
| `segment` | 采样分段，例如 `tail:1`、`pool:2-3`、`small:4-5` |
| `cluster_size` | 采样前原始粗簇的题数，不是最终样本数 |

`new_cluster_id=pool:2-3` 只是把规模为 2–3 的多个小簇放进同一采样分组，不代表它们语义相同；语义关系看 `cluster_id` 和 `fine_cluster_id`。

`clustered.xlsx` 在聚类完成时自动生成，不需要额外配置，目录同样由 `OUTPUT_DIR` 指定。
它包含全部输入行，保留原字段，增加 `cluster_id` 和启用细簇时的 `fine_cluster_id`，不包含采样阶段才产生的三列。
Excel 和 `clustered.jsonl` 来自同一次聚类；列表、对象在 Excel 中保存为 JSON 文本，采样仍读取 JSONL 以保留原始类型。
即使随后采样参数错误或采样失败，成功生成的 `clustered.xlsx` 也会保留，便于查看中间结果。

只需接入结果的下游读取 `sampled.xlsx` 即可。实际样本数以表格数据行数及报告为准：受可抽容量或长尾占比上限约束时会少抽并提示；目标不足以覆盖保底簇时会报错，不自动调整策略。原始列表、对象字段在 Excel 单元格中保存为 JSON 文本。

启动聚类前先删除上述五个旧结果文件，保留缓存及目录中的其他文件。聚类失败不会进入采样，并移除未完成的聚类 Excel；任一步失败都移除最终采样 Excel 和采样报告，避免误读旧结果或未完成的结果。采样失败时保留成功生成的聚类中间产物。输入路径不能与这五个输出路径重合。

重新执行会复用成功缓存。缓存按服务地址、模型、维度和专用参数区分；模型部署在同一地址、同一 ID 下实际换版时应清除对应缓存或换输出目录。不要同时运行多个进程写同一输出目录。

聚类质量依赖模型和阈值，样例不预设应分成几个簇。接口调用失败不会切换模型。复制到其他项目时，保留本目录与上一级两个原脚本的相对位置。
