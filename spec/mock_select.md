❯ /btw 你应该构造一些live会跑失败的case，而不是你自己手动搞一些失败的case（不然怎么归因出问题）                                                     

  /btw 你应该构造一些live会跑失败的case，而不是你自己手动搞一些失败的case（不然怎么归因出问题）

    你说得对。我之前想"手工构造 output 来体现失败特征"——这跟 mock 数据本来的问题是同一个毛病：失败是人为预设的，不是 live
    链路真跑出来的，所以归因拿到的是"被塞进去的结论"而不是"从真实执行中复现出的分歧"。

    正确的做法是让 case 在 live 链路上真跑失败，而不是手工编一个失败的 output：

    - 构造能触发 live 失败的输入 query，让 case 走真实 live 调用（或 provided_output 模式下用业务系统真实跑出来的 raw
    response）。失败必须是业务系统在 live 执行中自然产生的，比如：
      - mpi：query 选规则层和 LLM 容易分歧的边界表达，让规则层命中 team_portrait 但 LLM 真实输出 other
      - mp：query 写"NBEV 目标值 120 亿"，让业务系统 extract_target_value_from_text 真的只提取数字不转单位（×10000 缺失），live 产出 targetNbev=120
    而非 1200000
      - cs：query 用业务系统 L1/L2 规则覆盖不到的表达，让 parser 真的产出空条件（empty_query）
      - QA：用真实会让回答模型翻车的 contexts/golden_answer 组合（含否定词、含未提及信息）
    - trace 的 live 节点记录的是真实执行——evidence 里的 input schema 是 live 真实传参，actual 是 live 真实输出。trace 模拟时用同样的 input
    重放业务系统函数，对照 actual 定位分歧。因为失败是 live 真跑出来的，分歧点真实存在，归因才有依据。
    - 如果 live 服务起不来，就用 provided_output 模式但 raw_response 必须来自业务系统真实跑过的输出（比如离线跑一次业务系统、把 raw response
    存下来作为 mock 的 output 字段），不能手工编 raw_response。

    这样 trace 模拟的"复现局部链路"才有意义——业务系统函数在同样输入下重放，要么复现同样的失败（确认根因），要么不复现（说明失败是上下游传递问题），
    两种结果都能产出真实归因。手工编的 output 没有这个对照能力，归因变成"对假数据做假分析"。

    核心原则：失败要 live 自己跑出来，不能人为塞。trace 模拟的价值就在于它能重放 live 真实调用、对照真实失败点。
