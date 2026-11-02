# 过程评测案卷化改造：冻结样本复评（E）

对应方案：`spec/adapter/judge-process-eval-plan-20260920.md`；接入标准：`spec/adapter/business-trace-v1.md`。

## 这批样本

| 来源 | 数量 | 说明 |
| --- | --- | --- |
| `report/business-trace-agno-20260913/snapshots/snap-*.json` | 5 | 旧冻结快照（and-procedure / cash-value / multi-turn / policy-with-data / unknown-policy） |
| `report/process-dossier-20260920/clean-traces/*.json` | 25 会话 | A 做完后干净重跑：29 个请求合并成 25 个会话，其中 4 个会话各两轮 |

冻结 trace，重评不再打业务后端；结果按样本落在 `results/<来源>--<样本>.json`（含逐轴 checks 与主轴裁决）。

复评命令（可重复、可续跑）：

```bash
PYTHONPATH=. python scripts/_replay_process_dossier_tmp.py --kind all --workers 3
# 单个样本 / 强制重跑：--only ctx-ellipsis --force
```

写标准答案前的原始事实（确定性提取，不经 LLM）：`sample-facts.md` / `sample-facts.json`
（生成：`PYTHONPATH=. python scripts/_summarize_process_samples_tmp.py`）。

## 这一轮改了什么

1. **分析轴真的做问题分析并选段**：`trace_analysis` 分两步——程序把完整案卷（无损、编号唯一）装好；
   分析轴产出行动路线 + **每个下游轴需要哪些案卷编号**（只写编号与用途，不写证据正文）。
   程序合并各段，下游拿到的是选段视图。
   > B3 之后（见 `evidence-index/README.md`）：分析轴不再逐段读完全部原文，改为「清单 + 只读取证工具」
   > （`business_trace/tools.py`，本文件下面第 6 条说的「已删」是当时的状态，B3 又建了回来并改为工具形态）；
   > 引用必须（a）在清单里、（b）有正文读取回执。
2. **六轴不再吃全文**：每轴 prompt = 自己的问题 + 本轴选段原文（超 `VIEW_BUDGET_CHARS` 按整理员给的
   优先级截断并记入 `excluded`）。引用只校验「编号在本轴视图内」；同一源路径的两种表示（如
   `messages/5` 与 `messages/5#reasoning`）互相可引用。
3. **主轴也不再吃全文**：主轴拿到 structure + 六轴 checks + 它们引用过的编号所对应的原文。
4. **编号唯一化修复**：同一条持久化路径被两种类别登记时编号带 `#<kind>`，避免选段静默丢材料；
   同一源路径的两种表示互相可引用。
5. **输出不合规不再杀轴**：轴的一次重试后仍不合规时，程序就地把缺字段/多字段/视图外引用修好——
   无有效引用的 pass/fail 降为缺证并留痕（`view.dropped_refs` / `view.repaired`）；分析轴某个片段
   整段不可解析时，案卷仍完整，该片段记入 `structure.repaired_chunks` 与 coverage_note，下游按缺证处理。
6. **删掉已无消费者的读取工具层**（`business_trace/tools.py`；B3 重新以「只读取证 + 回执」形态建回，见第 1 条注）、
   `consistency` 伪轴，与前端事后审计残留
   （`shared_evidence_warning` / 事实层叙事 / precheck 标签 / critical 标签）；前端在 trace 模式下
   标明「过程证据（支撑主裁决）」，主状态只以主裁决为准。
7. insurance 预设不再并列启用 `fulfillment` 扩展轴（主轴已产 `fulfillment_assessments`）。
8. 过时的 `spec/adapter/process-eval-v4.md`（探测/findings/observations 设计）删除，
   `business-trace-v1.md` 改成案卷 + 选段口径。

## 效果（改前 → 改后）

| 指标 | 改前 | 改后 |
| --- | --- | --- |
| 单轴 prompt | 全量案卷，最大样本 575k 字符 / 213k tokens，4/25 样本超 131k 窗口 | 选段视图，最坏情况（把全部记录都选给一轴）≤ 104k tokens；本轮实测各轴 6–20k 字符 |
| 分析轴单次调用 | 全量案卷一次塞入（超窗口） | 分片读完为止，单次最大 109k tokens（`CHUNK_CHARS=100k`） |
| 引用校验 | 事后查翻没翻过（covers/seen_refs/unread_refs…） | 只校验格式与编号是否在本轴视图内 |
| 主轴 | 全量案卷 + 六轴 | structure + 六轴 checks + 被引用编号的原文 |

## 结果与人工对照

```bash
PYTHONPATH=. python scripts/_process_oracle_review_tmp.py   # 生成/刷新对照表
```

见 `oracle-review.md`：每条样本列出「按冻结 trace 能确定的事实」「Judge 实际结论」「差异」；
对照表只自动标机器可核的异常（轴 failed/blocked、主轴 not_evaluable、引用被剔除、材料被排除），
语义上的该报/误报不做自动判定，留人工抽查。不以通过率为目标。
