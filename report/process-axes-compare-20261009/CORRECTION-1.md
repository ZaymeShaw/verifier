# 更正 1（派发方，2026-10-09）：现行臂与生产调用不等价，先修再跑

冒烟测试（`runs/current/pass1/smoke-policy-detail-renyanlin/`）暴露了两个管道问题，会让对比失效。请先修复，再继续。

## 1. 现行臂的模型调用必须与生产 `LlmClient.complete_json` 等价

现在 `llm_transport.Transport.complete_json` 忽略了 `output_spec`，模型看不到输出结构。冒烟中 6 个轴全部因结构不合格失败（如 `units` 写成对象、缺 `reason`/`scope_note`），这是管道缺陷，不是现行方案的表现。

生产做了三件事（见 `impl/core/llm_client.py` 约 980–1060 行），现行臂必须照做：
1. 系统提示词末尾追加 `"\n\n" + render_output_constraint(output_spec)`（`impl/core/structured_output.py`）；
2. 解析用仓库的 `impl.core.llm_client.extract_json`（含未转义引号修复），不要用自写的解析；
3. 解析后执行 `enforce_output(parsed, output_spec, caller=stage)`，不合规就抛 `ValueError`，让六轴代码自己的纠错轮（`process_common` 里「上次输出未通过程序检查……」那一次重问）照常生效。不要在 transport 层吞掉或替换这个行为。

可以直接复用这些函数，只把「发请求」那一步换成你的 deepseek 直连；`finish_reason=length` 与限流的重试保留。

## 2. 重跑时的「发送前检查失败：材料批次与 pending 必须一一覆盖」

所有 `*.rerun1.json` 都报这个错，说明回放状态在两次运行之间被复用或被改动（批次、selection、required、projection 之类的可变对象）。每次运行（含整轴重跑）都要从冻结输入重新构造，不共享可变对象。

## 3. 记录与继续

- 现有 `runs/current/` 的冒烟记录**保留**，在 RESULT.md 里标为「无效：现行臂缺输出结构注入与校验」，不计入任何指标。
- 修好后重跑冒烟：所有轴都能产出合规结果，或者失败原因是模型的判断而不是管道问题，再跑全量。
- 新方案臂同样要把输出形状写进提示词（草稿第 4 节），两臂用同样严格的解析与校验。
- 这次更正写进 RESULT.md 的「偏离与更正」一节。
