# 配置权威链收敛设计

## 目标

在不修改 `spec/adapter/config.md`、不改变项目评价算法和业务边界的前提下，完成现有配置实现的最后一轮权威链收敛：项目可调行为只由 `ProjectSpec` 提供，公共可调行为只由 `RuntimeConfig` 提供，配置门禁能够阻断重新引入的代码常量、环境旁路和不完整验收。

## 范围

本次包含四类改造：

1. 消除 `live_schema.py` 中与项目 YAML 重复的 `READY`、`SCENARIO_ENUM`、`INTENT_LABELS` 和无效 endpoint 常量；
2. 消除 endpoint discovery 的 consumer fallback 和固定 HTTP timeout；
3. 补强未登记环境变量、秘密文件范围和配置常量旁路门禁；
4. 补齐模型能力与本地服务生命周期的可执行验收。

本次不建立新的通用字段注册中心，不重写 live schema 数据结构协议，不迁移 mock case seed、算法不变量或历史 Trace/report。

## 设计

### 1. ProjectSpec 成为项目行为目录

`runtime.ready` 是 ready contract 的唯一来源。所有 case 校验、mock 数据检查和 live schema 检查都必须从当前项目 `ProjectSpec` 获得 ready 值；`live_schema.py` 只声明请求和输出的 dataclass schema。

场景和意图标签按用途读取：

- mock 生成优先消费 `runtime.mock_cases.default_scenarios`；未声明时消费 `verifier.presentation.scenarios`；
- 全场景回归和展示消费 `verifier.presentation.scenarios`；
- 意图标签消费 `verifier.presentation.intent_labels`；
- 结构化请求必填字段继续由 dataclass schema 推导，不迁入配置。

`ProjectSpec` 提供小型类型化访问器，消费者不再直接读取项目 YAML，也不再反射 `live_schema` 中的配置常量。`MOCK_CASE_SEEDS` 属于 mock case 生成材料，可以保留在代码/fixture 中，但其 key 必须是配置场景集合的子集。

### 2. LiveSchemaCheck 只负责结构

`LiveSchemaCheck` 保留 request/output/reference 的结构校验职责。涉及 ready 的 case 校验改为显式接收调用时的 ready contract，禁止在模块 import 时捕获项目配置。

这样修改 `project.yaml` 后无需重载 Python 模块，当前 run 解析出的 `ProjectSpec` 会直接决定 case 合同；配置来源和 Trace 指纹仍由现有链记录。

### 3. Endpoint discovery 只消费规范配置

`ProjectConfigResolver` 将 endpoint discovery 解析为完整规范对象。启用 discovery 时，`framework`、`source_roots`、`scan_patterns`、`exclude_patterns` 和 `blacklist` 必须由项目 YAML 明确声明；`route_prefix` 可规范化为空字符串。

`EndpointDiscovery` 使用键访问完整对象，不保留 `or DEFAULT_*`。发现出的远程工具从 `runtime.services.primary` 获取 `base_url` 和 `timeout_seconds`，不得固定 `timeout=10.0`。缺少 primary service 时在加载工具阶段明确失败，不生成不可执行工具。

### 4. 门禁补强

配置检查新增以下阻断：

- 产品代码直接读取任何字面量环境变量都报告旁路；已登记变量提示应走 resolver，未登记变量提示必须先登记；
- 项目 `live_schema.py` 不得重新声明 `READY`、`SCENARIO_ENUM`、`INTENT_LABELS`、`API_ENDPOINT` 等已归属配置的符号；
- 扫描已跟踪的配置、Markdown、JSON、Python、Shell 和工具配置中的秘密型字面值，同时排除明确的历史证据与测试占位规则；
- endpoint discovery 中的部署字段和 timeout 不得出现 consumer fallback 或数值硬编码。

门禁必须给出文件和行号，不自动修改配置。

### 5. 模型与本地服务验收

模型探测继续保留 JSON mode 和自动 tool calling，并增加与已配置 reasoning 策略兼容的请求探针。上下文能力采用显式声明的上下文上限和边界校验，不在 CI 中发送高成本满窗口请求。模型切换合同测试覆盖公共继承角色和显式 role policy 例外。

本地服务测试使用受控 fake process/clock 验证：已健康不启动、未健康只启动一次、非零提前退出、零退出后继续等健康、启动超时、日志脱敏和并发锁串行化。测试不得启动真实业务服务。

## 错误处理

- 配置缺失或重复来源在 resolver/config-check 阶段失败，不回退到代码值；
- endpoint discovery 工具缺少服务连接时失败关闭；
- 模型能力探测只输出能力名、HTTP 状态和脱敏后的有限诊断；
- 本地服务错误只输出项目、退出码和脱敏日志路径，不输出环境值。

## 验收

完成时必须满足：

1. 修改项目 YAML 的 ready、scenarios、intent labels 或 service timeout，无需修改项目 Python，所有目标消费者同步变化；
2. 仓库内不再存在上述 `live_schema` 配置常量和 endpoint discovery consumer fallback；
3. 新增未登记 `os.getenv("NEW_VAR")`、固定 discovery timeout 或秘密型 JSON/Markdown fixture 时，config-check 能够阻断；
4. 公共模型切换测试覆盖继承角色、显式例外、JSON、tool calling 和 reasoning 兼容性；
5. 本地服务生命周期边界测试全部通过；
6. `bash run.sh config-check --require-runtime-secrets --full --json`、完整 pytest、compileall 和 `git diff --check` 通过；
7. `spec/adapter/config.md` 保持不变。
