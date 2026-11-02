# 更正 2（派发方，2026-10-09）：输出上限与 reasoning_effort 也要与生产一致

修好结构注入后的冒烟里，上下文、模型两个轴各 6 次尝试全部失败（`llm_request_failed`）。原始回复约 66KB，**都停在推理中途、没写到 JSON**——是被 `MAX_TOKENS = 16000` 截断了，不是方案或模型的判断问题。

证据（网关记录的 183 次真实六轴请求，job fb5fda…）：
- 生产请求**不设** `max_tokens` / `max_completion_tokens`，用模型默认上限；
- 生产六轴单次最多用到约 52,000 token（输出 + 推理）；
- 生产请求带 `reasoning_effort`（六轴代码传入的值），请求体字段为 messages、model、reasoning_effort、stream、stream_options、temperature。

请：
1. 去掉 `max_tokens`（与生产一致，用模型默认上限）。若中转要求必须带，设为不低于 64000，并在 RESULT.md 写明。
2. 把六轴代码传入的 `reasoning_effort` 原样转发到请求里，新方案臂也用同样的设置。
3. 这两组截断的失败记录保留，标为「无效：输出上限低于生产」，不计入指标；修好后重跑冒烟。
4. 写进 RESULT.md 的「偏离与更正」。
