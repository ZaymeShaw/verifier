# 独立门实现验证记录

实现位于 `hooks/verifier-ready/`。按本次用户要求，保留独立入口，未加入根 run.sh 的 gate 分支、AGENTS 完工条款或 pi settle hook。

已实现：专用实例 live 采集；显式存档 execution 采集；完整 envelope 校验；UTF-8 无损分块与实际工具返回核对；逐 case 调用账本及证据解引用；七类一致性关系检查、共同规则差异聚合、上轮关键发现闭环；全局审阅范围快照、指纹及失效判定；硬性指标与参考体量；实施者回应、人工裁决及显式基线提升。人工豁免保留真实不一致，并使用 PASS_WITH_EXCEPTION 披露。

验证命令：

```bash
bash run.sh python -m pytest hooks/verifier-ready/tests tests/test_process_prompt_contract.py -q
```

结果：91 passed in 4.47s。其中独立门 80 项，现有 prompt contract 11 项。

本地真实子进程模拟四个并行审阅分片，串通分块、账本、指标、审阅、快照及 verdict；检查根 run.sh、AGENTS 和方案文件在运行前后字节相同。只读 status 检测原文修改后的 stale；缺块、截断、非法引用、未知共同规则、失败重审、旧发现未闭环、模型身份错配和范围修改均有失败检查。

历史元数据 fixture 复算 111 次请求（110 succeeded / 1 failed）、24 次同名非 ToolLoop 额外调用，正确处理零调用 execution。batch fixture 为指标字段投影，来源哈希随文件保存，不能用来证明语义审阅。部分 execution 采集的指标和解引用账本只取选定范围，原 batch 存档不改写。

12 个构造样本及 gold 已复制并核对 13 份原文件 SHA256。它们仍需后续用实际审阅模型校准。

本机 pi 在临时私有配置中识别 DashScope/qwen3.8-flash；配置文件权限 0600 并在退出时清理。只运行模型注册检查，没有发送业务材料。

尚未执行：新门真实业务 live、全量 Qwen 审阅、语义校准、修复后真实 live 闭环与生产基线提升。模拟 PASS 只证明实现机制；不能作为真实上下文一致性或业务准确率已通过的结论。主流程和自动 hook 接入按用户要求留待独立验证后处理。

## hook 独立实现与验证补充

用户进一步要求 hook 也能独立验证后，新增 `adapters/pi_before_settle.ts` 及只读 `--hook-status`。仍未创建 `.pi/extensions` 注册文件，未加入主流程。

hook 专项 10 项 pytest 通过，其中包含 Node 的 21 个测试场景；完整独立门加现有 prompt contract 共 101 项通过。实际安装的 pi 0.87.1 loader 成功加载 TypeScript，并通过真实只读 Python 桥取得代码指纹。随后在隔离的状态输入下，使用 pi ExtensionRunner、SessionManager 消息投影及 AgentSession 完整 before-settle 边界，验证消息落入 transcript 后可以继续；没有调用 provider。

验证中特别覆盖最终 assistant 消息下初始 canContinue=false 的情况：hook 必须先追加 custom_message，再由 pi 判断可继续，不能提前跳过。其他场景涵盖全部失败状态、正常/人工例外放行、文档和排除文件不激活、bash/custom tool 内容变化、损坏输出、取消/错误结束、6 次上限、reload/resume 计数保留及其他扩展的 continuation 不被覆盖。

本次 hook 验证证明适配器和事件契约；尚未在实际模型驱动的 pi 会话中安装运行。全文审阅质量仍待真实 Qwen 验证。
