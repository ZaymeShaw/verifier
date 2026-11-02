# 8021 实测发现的输出协议矛盾与修复

## 触发与现象

用户在 8021 启动最新 verifier，批次 `5db2d9d4128f46a38af796145f5094d5` 选择 32 条用例、并发 4。首批四条走 Agno 普通案卷路径。约 20 分钟时完成 0/32，但模型调用不断返回，任务没有停住。

四条上下文轴，以及随后部分意图轴的结果缺少 `results[*].matched_link_id`。原始上下文中的 `error` 明确为必填字段缺失，模型输出含 expectation_ids 与 expectation_checks，却省掉 matched_link_id。这是评测模型产出的协议失败，不是被测业务违约。

## 已确认的代码缺陷

普通运行单位按消费者协议应提供 `matched_link_id=""`；应发生单位若无法定位实际事件，也以空字符串明确表示无法匹配。字段必须存在，值可空。

实际发给模型的 JSON Schema 却是：

```json
{"matched_link_id":{"type":"string","minLength":1}}
```

根因是通用 dataclass 到 schema 的转换默认给所有字符串加 minLength=1。`ResultGroup.matched_link_id` 没有声明空值例外，普通案卷提示词也没有明确强调“普通单位保留此字段并填空字符串”。因此 schema 与合法协议值矛盾。需求轴的 ambiguity_group 无歧义时也应填写空字符串，存在同类 schema 矛盾。

本地 SchemaValidator 检查字段存在和字符串类型，并未按生成 schema 的 minLength 校验普通字符串。旧回归的脚本回复主动给了空字符串，因此通过本地校验，却没有发现真实请求携带的 schema 相互矛盾。这是我先前验证的覆盖缺口；不是“模型本来漏字段，所以随便补个默认值就好”。

这些事实能确认实现缺陷；不能单凭它们断言 minLength 是模型省略字段的唯一原因。

## 改了什么

- 通用 schema 转换支持字符串字段的 dataclass metadata：`allow_empty=True` 仅改变该字段 minLength，不改变 required；字段说明也由 metadata 随 schema 交付。
- `ResultGroup.matched_link_id` 声明可空与含义；`Expectation.ambiguity_group` 声明无互斥读法时可空。
- 消费者提示词明确所有结果必须携带 matched_link_id：普通单位空字符串，应发生单位填真实事件，无法定位仍空字符串；不得省略。
- 普通案卷、共享 dossier ToolLoop 和 transcript 仍从同一个 ResultGroup dataclass 生成 schema，不复制手写三套契约。
- 不在模型输出后偷偷补字段，不允许 null 或删掉 required，不改变真实判断、E 覆盖和匹配校验。

所有需求及方案文档保持原样，157 份保护文档哈希仍一致。用户运行的 8021 批次未停止或重启。

## 验证

新增测试同时检查合法空值是否被实际模型 schema 允许、缺字段是否仍被拒绝、三条路径是否一致、无歧义组空值是否合法，以及显式 required_nonempty 能否保持强约束。

针对相关功能、普通案卷、共享会话、真实本机 SDK 协议的集合：135 passed，2 failed。两项失败是已有的 Python 3.11 PEP 604 联合类型/Authority schema 退化问题，使用未修改 HEAD 的 structured_output.py 在隔离进程中复现，同样两项失败；不是这次 metadata 修复引入。原始日志完整保留，不隐藏失败。

更广回归：447 passed、1 skipped、2 deselected，95.39 秒，见 `broad-tests.log`。两项既有失败单独列为 deselected，未从测试代码删除；此前针对集合及未修改 HEAD 的失败日志均保留。

真实模型协议核验复用当前 B/Agno 客户资料用例某次被拒上下文轴的原始 user 输入，换成修复后的 schema 和提示词，使用已配置的评测端点。它不重新请求业务系统，不重跑整批，不把模型生成的判断视为语义验收通过。输入来源、原文哈希、schema 在 manifest.json，真实结果在 result.json，生成正文在 generated-output.json，实际发送的提示词在此目录模型上下文 JSON。

这次真实核验一次命中 primary / gemini-3.8-flash-medium，耗时 167.38 秒。生成 6 组结果，全部保留 matched_link_id，全部为合法空字符串；结构校验通过，未尝试补默认值。只核验这一批生成的输出协议，不宣称覆盖完整 κ 轴全部批次，更不宣称六轴或语义验收通过。

## 对当前批次的影响

8021 启动于修复前，Python 进程已经载入旧类及 schema 函数；修改磁盘文件不会让这批运行自动切换。此批结果应保留为排查材料，不能声称它已经验证修复。重启 8021 后才会加载新协议，建议先跑一条完整用例验证，再扩展到整批。
