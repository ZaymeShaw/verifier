live 和 trace 的串联逻辑

一、两者定位

- live：内层模块，做 REQUEST_SHAPE → EXTRACT_OUTPUT_SHAPE 的契约转换。只关心"业务系统接受什么形状的输入、返回什么形状的输出"。
- trace：外层模块，承载一次运行的完整事实记录。负责把 live 产出的 extracted_output + 调用过程中收集到的事实（project_id / case_id /
session_id / raw_response / execution_trace / fallbacks / multi_turn_state / ready 等）组装成一条可观测、可判定的 trace。

二、串联方向

单向依赖：trace 依赖 live，live 不依赖 trace。

pipeline
    ↓ 调
live.execute_live(normalized_request) → extracted_output
    ↓ 返回
trace 层组装：spec + case + extracted_output + 过程事实 → RunTrace
    ↓ 输出
judge / attribute / check 等下游消费 trace

live 不知道 trace 的存在，trace 知道 live 是它的输入来源之一。

三、数据流

1. case 进来 → trace 层从 case 提取 normalized_request（符合 REQUEST_SHAPE）
2. trace 层调 live.execute_live(normalized_request) → 拿到 extracted_output（符合 EXTRACT_OUTPUT_SHAPE）
3. trace 层自己组装：
    - project_id ← spec
    - case_id / session_id ← case / 交互契约
    - extracted_output ← live 返回值
    - raw_response / execution_trace / fallbacks / multi_turn_state ← trace 层在调用过程中收集（或 live 层通过访问器暴露）
    - ready ← spec 配置
4. trace 落形 → 一条完整的 RunTrace 出去，供 judge/attribute 消费

四、关联关系

- live 的输出是 trace 的核心输入之一：extracted_output 是 trace 里"业务系统真实产出"的具现，judge 对照 reference 和 actual 时用。
- trace 是 live 结果的承载者：live 不持久化、不观测、不判定，只产出 extracted_output；trace 把这个产出包装成可判定的事实原件。
- 过程信息归属 trace：raw_response、execution_trace、fallbacks、multi_turn_state 这些"调用过程的事实"由 trace 层维护，live
层不承担这些职责。
- 契约归属 live：REQUEST_SHAPE 和 EXTRACT_OUTPUT_SHAPE 由 live_schema 定义，是 live 的契约，trace 层只消费不定义。

五、不变量

1. live.execute_live 的签名纯粹：REQUEST_SHAPE → EXTRACT_OUTPUT_SHAPE，不掺杂 trace 字段
2. trace 的组装由 trace 层自己完成，不依赖 live 内部结构（不反向扒 LiveExecutionResult）
3. live 不感知下游（judge/attribute），trace 才是下游的输入
4. 单轮和多轮在 live 内部统一，trace 层零感知

六、一句话

live 是契约转换器，trace 是事实承载者。live 把 REQUEST_SHAPE 转成 EXTRACT_OUTPUT_SHAPE，trace 把这个产出 + 
调用过程中收集的事实组装成一条可判定的 trace 给下游。live 不依赖 trace，trace 依赖 live。