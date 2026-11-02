# need-side / main-judge 并行任务状态

## 已实现

1. `impl/projects/llm_probe/business_trace/expectation_material.py`
   - 删除 system / tools / format / definition / instruction template 的投影及缺料原因。
   - 保持第一请求的用户原话与历史出处 ID / trace_refs；不读取后续调用与本轮产出。
   - `description` 为 `background/description`，`criterion` 为 `want/criterion`。
   - 任意非空（含空白字符串）`capability` 不进入材料，固定缺料原因 **`capability 未拆分`**，即使已有用户原话也一样。
   - 不读取 `downstream`，也不因此改变 verdict 或 hash。没有修改共享场景形状校验。
   - history_runs 无当前 run 身份或历史记录无身份时不把内容当已证实历史。
2. `impl/projects/llm_probe/eval_axes/adapters/expectations.py`
   - prompt 仅提取结果需求，禁止设计声明、能力声明、执行路径与通用底线。
   - 来源严格限于 want/user、want/criterion、history/history、background/description。
   - 每条必须至少引用一个 want；背景／历史单独或合用均不能独立产需求。保留来源成员、非空、唯一 ID、歧义组校验。
3. `impl/projects/llm_probe/need_judge.py`（新增）及 `impl/projects/llm_probe/judge.py`
   - **业务 Trace 主判**读取 report 中成功的冻结 E；没有成功 E 时阻断，绝不另推需求。
   - 校验 E 内容 hash；两阶段模型 schema 均严格要求 E 的原 ID 全覆盖、无增删重复、hash 相同。
   - 第一阶段仅见 E，逐条投影 blocking；第二阶段才见最终交付与六轴／案卷证据。保持公共 `BusinessExpectation.blocking` 的“比较 actual 前确定”语义。
   - 两阶段均没有模型可写的 `business_expectations` 字段。公共 `JudgeResult.business_expectations` **仍存在**：这是程序从冻结 E 原样生成的公共封装，不是模型自推的第二份需求。陈述、条件、歧义组、出处、E hash 均保留；公共总体 verdict 仍由现有 finalize 推导，没有修改共享 core。
   - 一次正常主判是两次调用（blocking + delivery），每阶段最多一次结构纠错；未启用 response_format，未加 fallback。
4. 测试：新增 `tests/test_expectations_v2_need_judge.py`；更新 `tests/test_process_main_judge.py` 的成功 fixture 提供冻结 E、mock 新本地执行点，保留其失败门禁和报告消费断言。

## 备份与边界

原文件在 `before/need-judge/`，保留完整仓库相对路径。`fulfillment.py` 也已备份但**没有修改**。

没有修改 demand/、spec/alg/、共享 core、`tests/test_expectations.py`、`tests/support/expectations.py` 或实施文档；没有提交 git。没有触碰其他 agent 的六轴投影／输出／design_rules 所有权文件。

## 离线验证证据

解释器：`/Users/xiaozijian/miniconda3/envs/agno/bin/python`。

使用本目录 `offline_tests.py`：拒绝外网及业务／付费本地端口；新增测试还将 socket.connect/connect_ex 全部禁用。未调用真实模型。

定向命令：

```text
python offline_tests.py -q tests/test_expectations_v2_need_judge.py tests/test_process_main_judge.py tests/test_llm_probe_eval_axes.py tests/test_process_session_isolation.py tests/test_project_layer_dispatch.py tests/test_policy_search_judge.py
```

结果：**119 passed in 7.31s**，日志 `need-judge-tests.log`。覆盖需求材料负例、background/history 非独立来源、capability partial、来源/hash、blocking 前置隔离、主判 E 全覆盖及拒绝自推字段、公共结果 finalize、缺 E 阻断、现有主判过程失败门禁、其他项目分发与 policy_search 回归。

全仓也已尝试：`python offline_tests.py -q tests`，但 **collection 阶段 4 errors**，没有进入全仓执行。日志 `need-judge-full-tests.log`：并行改造时 `process_common.ProcessAssessment` 已删除，`process_loop/llmtracing.py` 尚在导入它，导致 test_expectations / test_llmtracing_tool_loop / test_process_prompt_contract / test_transcript_evidence_boundary 收集失败。这是当前并行集成的可见状态，不是全仓通过，也不能据此判断其余既有 14 项失败是否变化。未越权修复。

## 剩余问题／范围限制

- **未启用业务 Trace 的旧 llm_probe 主判／独立 fulfillment 能力兑现轴未切换**，仍走原单次公共判定。该路径没有上游冻结 E 的依赖图，独立 fulfillment 还是能力描述契约；本次只完成已有 E 生产链路的主判消费，不能声称所有 llm_probe 场景已不再自推需求。若要求同时改造该路径，需要明确其 E 生产／依赖登记并接入（不能仅 prompt 宣称“使用 E”）。其他项目和公共 JudgeResult 行为未变。
- 本次证明无需改变共享 JudgeResult 语义即可让业务 Trace 主判用 E；保留公共字段为程序投影，是为了避免公共 finalize 把所有结果变为 not_evaluable。若“主判输出不能包含 business_expectations”被解释为连公共封装字段也必须删除，则与“公共 JudgeResult 不变”冲突，需协调确认；当前满足“不含自推需求”。
- 不做真实模型或付费网络验收；没有稳定性、质量、耗时收益的真实测量。两阶段主判新增的 blocking 调用应计入后续完整实测。
- 全仓需等其他 agent 完成六轴／ToolLoop 迁移后重跑；本报告不替其代码作通过声明。
