# Judge Knowledge Baseline

一等产物，与 draft 同等。promotion 时一起成为新 baseline，下一轮 AI 站在这一层之上探索。

## 链路地图

记录业务输入 → 业务输出 → 判定的关键环节、分支和已知 gap。每个项目按 `impl/projects/<project>/` 实际结构补充。

- 业务输入边界：judge 能看到什么、不能看到什么。
- 判定分支：哪些条件触发 fulfilled / not_fulfilled / not_evaluable。
- 已知 gap：哪些业务场景下当前判定会失真。

## Gap 模式

沉淀"这类 gap 怎么识别和判定"，不是"这条 case 怎么修"。

- 模式名：简要描述。
- 触发条件：哪类 trace/业务输入会出现这个 gap。
- 判定路径：从哪些业务字段推断 gap。
- 关联标准：项目已有 semantic comparator/runtime check 怎么使用。

## Probe 库

被验证过有效的 judge probe 及适用场景（外部业务视角，不读取内部代码）。

- probe 名：来源文件路径。
- 输入：从 trace 取哪些业务字段。
- 输出：能稳定显示什么 gap。
- 边界：在哪类 case 上无效。

## 被否决的假设

试过什么、为什么不 work。

- 假设：改 X 能解决。
- 实验：怎么验证的。
- 结果：为什么不 work 或在什么边界失效。

## 泛化边界

这个优化在什么范围有效，超出什么边界可能失效。

- 适用范围：哪类 case 验证过。
- 不适用范围：哪类 case 没验证或已知可能失效。
- 风险条件：触发 not_evaluable 误判或强判 fulfilled 的条件。

## 维护

- 每轮 promotion 前更新本文件。
- 只记录被验证过的事实，不写猜测。
- 删除被新探索推翻的旧条目。
