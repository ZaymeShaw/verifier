# DeerFlow run_chain 输入边界修复设计

## 目标

修复 Summary 前端单链路运行 DeerFlow 裸请求时，顶层 `input/config` 被通用 MockCase 归一化误拆的问题，同时保持“加载 Mock 数据集 → 批量归因”现有行为不变。

## 问题边界

`/api/run_chain` 的 `input` 字段承载项目原生请求。DeerFlow 原生请求本身包含顶层 `input`，不能再次被解释为 `SingleTurnCase.input` 外壳。

批量入口承载的则是标准 `MockCase`。它通过 `MockCase.live_request → SingleTurnCase.input` 显式转换，目前工作正常，不属于本次故障范围。

## 方案比较

1. **在 `/api/run_chain` 服务入口显式包装（采用）**
   - 将 API 的裸项目请求构造成 `SingleTurnCase(id="", input=request)` 后传入 pipeline。
   - 优点：输入语义由入口决定，不依赖字段名猜测；改动小；恢复历史行为；不影响批量路径。
   - 代价：需要让 `pipeline.run_chain` 的类型声明明确接受 `SingleTurnCase`。

2. 在 `normalize_mock_case` 中根据字段猜测是否为 DeerFlow 裸请求
   - 优点：表面上只改一个函数。
   - 缺点：通用层需要理解项目协议；`input` 字段仍有歧义；可能破坏目前正常的批量转换。

3. 重构单链路和批量链路为两个新协议
   - 优点：长期边界最清楚。
   - 缺点：范围过大，不符合当前只修明确 Bug 的要求。

## 数据流

单链路：

`Summary 裸 live request → service.run_chain → SingleTurnCase(input=完整请求) → pipeline.run_chain → live_run`

批量：

`MockCase → parse_mock_case → mock_case_to_single_turn → 现有 batch pipeline`

两条路径不再依赖裸字典的 `input` 字段来猜测数据类型。

## 错误处理

本修复不改变 DeerFlow Live Schema 校验和异常策略。请求确实缺少 `input/config` 时仍应由现有 Schema 校验拒绝；只避免合法请求在校验前被错误改写。

## 验证

新增回归测试覆盖：

1. `/api/run_chain` 收到合法 DeerFlow 裸请求时，进入 pipeline 的对象是 `SingleTurnCase`，其 `input` 完整保留顶层 `input/config`。
2. `pipeline.run_chain` 接收该对象后，`live_run` 看到的仍是完整请求。
3. 标准 DeerFlow `MockCase.live_request` 经批量转换后仍完整保留请求，防止单链路修复造成批量退化。
4. 运行相关定向测试及现有 live/batch 协议测试。

## 非目标

- 不修改 Draft/Production Mock 生成策略。
- 不修改 DeerFlow 多轮 Mock Agent。
- 不修改 `normalize_mock_case` 的通用兼容逻辑。
- 不改变前端 Mock 数据集和批量归因协议。
