# Original-rule fixes — independent review R2 remaining / R3

日期：2026-10-07。仅处理用户指定的 R2 剩余完整性、R3 配对 span 漏块，以及既有实现指纹依赖表。未修改 transcript provider、common/output/projection、其他测试或规格文档。

## 修改

- `impl/projects/llm_probe/business_trace/design_rules.py`
  - `declarations()` 直接登记完整工具原对象，不再只保留 name/description/parameters/returns。支持完整 function wrapper，保留外层及内层 strict、独立 x-condition 和其他扩展字段。
  - 保留已经完成的工具定义 `/fields` wrappers 路径修复，没有重新 flatten。
  - 工具端点沿 provider 已建立的 `span_ref` 获取同次工具调用说明，不搜索相邻 span 或按同名猜测。说明使用 span 自己的 ref、`/fields/tool_description/value`、工具名及当前 link ownership；scope=current 登记 execution，采集版仍为参考。模型轴不从此路径获取规则。
  - pre-run 读取边界未扩大：只读 definitions 和首个调用的 typed declarations，不读取运行工具结果、模型输出或插值消息。
- `impl/projects/llm_probe/process_loop/llmtracing_report.py`
  - 仅修改 FILES：加入 design_rules、dossier、materials、evaluation、process_output、process_contract，使这些原文/校验依赖的变化影响现有实现指纹。不另建版本机制。
- `tests/test_design_rule_blocks.py`
  - 完整 raw/tool wrapper 保留及反向源路径测试：引号、换行、独立条件、if/then、strict、扩展字段。
  - `/fields/.../value` 引文对原 record 的反向解析，拒绝旧 flatten 路径。
  - 合成配对样本：保持来源、scope、工具名、link ownership；相邻同名但无配对 span 不进入；模型轴不升级为 actual_input。
  - 冻结样本：读取 `report/expectations-20261006/unit-format-full-live-20261007/result.json`，通过真实 `_axis_links()` 枚举工具轴块，确认 persisted policy_detail 调用的配对 span **389 字**原始说明完整登记为 execution。
  - 指纹依赖测试通过内存 monkeypatch 模拟逐个依赖变化，确认指纹改变，不修改依赖文件。

## 验证

Python：`/Users/xiaozijian/miniconda3/envs/agno/bin/python`。

使用 `PYTHONDONTWRITEBYTECODE=1`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`-B`、pytest `-p no:cacheprovider`；audit hook 拒绝 socket connect/bind/sendto/getaddrinfo、subprocess 和 os.system。

运行文件：

- `tests/test_design_rule_blocks.py`
- `tests/test_axis_materials.py`
- `tests/test_process_v2_rules.py`
- `tests/test_process_v2_entrypoints.py`

结果：**211 passed in 0.51s**。本次定向测试没有遇到并发 required E hash enforcement 失败，也未放松任何 E 校验。未跑全仓；通过结果只对应此时工作区及上述测试。

## 边界

没有真实模型或业务调用，没有启动第二轮 live，没有重判冻结业务结果。冻结样本仅验证候选原文块的机械完整性与来源，不证明规则语义已经全部核实。用户已告知 Live1 因 projection references 失败；本任务不把该失败改写为通过，也不宣称第二轮 live 已成功。其他独立评审项由其他代理负责。
