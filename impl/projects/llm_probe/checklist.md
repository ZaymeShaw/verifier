# Checklist

- live_request 必须能解析出 url 或 capability_ref，以及 capability 或映射表里的能力描述。
- HTTP JSON 只发 body，信封字段不能出现在被测服务的请求体里。
- EXTRACT 只有 output_text 字符串。
- 流式响应必须失败，不能进入 judge。
- attribution.enabled 为 false。
- 轴2 走文本形态：capability 预设的 `boundary` 为 G。未填则每条未达成期望归位为「说不清（缺能力边界资料）」。
- 体裁分工：能力描述（轴1）= 系统定位三问——①用户拿它办什么事（用户视角，fulfilled.md §1 明令排除实现视角）②交付物被谁怎么消费执行（judge 须把输出放到消费方语义下推演，如把查询条件当查询跑）③什么算办成（等价即达成；互斥/放大/缩小/编造/丢失即未达成）。能力边界（轴2）写「能做/不能做」陈述句，不写解析规则。
- boundary 引用超预算资料自动转检索式消费：目录条目进 prompt，正文由 material_search / material_read 工具查；citations 带 material uri + Lx-Ly 行定位，placement 带 tool_trail。
- 轴1 judge 对可 parse 的 output_text 附 output_text_parsed；NE 仅限证据缺失，「支不支持」归轴2。
