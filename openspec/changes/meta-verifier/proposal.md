## Why

`impl/demand/meta-verifier.md` 将需求从“构建 UAT 协议模块”升级为“构建挑剔的测试者 / meta verifier”。基础要求仍然包含页面基础功能和按钮 UAT，但进阶目标不是只验证固定 UAT case，而是让系统扮演需求方用户，通过真实浏览器使用本项目，并主动指出系统无法满足需求的地方。

历史 UAT-only 方案过于受限：它把重点放在通用 UAT 协议对象、固定浏览器动作和断言上，能覆盖按钮和主链路，但不能承担算法时代对系统能力、需求满足度、架构合理性、关键链路完整性的“挑剔验证者”职责。因此本变更需要废弃历史 UAT-only 方案及其实现，转向 meta-verifier。

## What Changes

- 新增 meta-verifier 能力：加载项目文档、项目 skill、协议和前端页面，识别关键链路、关键函数、关键前端组件和用户常见操作路径，并枚举形成 checklist。
- 新增单入口 skill 形态：用户只使用 `/meta-verifier [自然语言目标]`，不需要指定 explore/test/reproduce/critique 等模式；meta-verifier 根据用户输入自动路由到整体探索、定向验证、问题复现或需求方 critique。
- 新增需求方用户模拟：启动独立 Claude Code 子进程 / sub agent，扮演需求方用户，对本系统提出真实目标和验收视角。
- 新增真实浏览器使用验证：通过 Python Selenium 等工具打开 `http://127.0.0.1:8020/frontend/index.html`，从入口页进入系统并操作所有核心页面、按钮和主要路径。
- 新增 meta-verifier 发现报告：记录功能开发缺陷、算法能力问题、系统设计架构缺陷、用户目标无法满足点、证据和复现路径。
- 保留基础页面 UAT 作为 meta-verifier 的一个证据采集手段，但不再把“UAT 协议模块”作为最终目标。
- 废弃并清理历史 UAT-only 方案：移除以 `UATCase`、`BrowserSession`、`BrowserAction`、`BrowserAssertion` 等固定协议对象为中心的实现和测试，避免它误导后续工作边界。

## Capabilities

### New Capabilities
- `meta-verifier`: Defines a verifier-of-verifier capability that combines project understanding, demand-side persona simulation, real browser operation, checklist generation, and defect/architecture/capability critique.

### Modified Capabilities
- `demand`: Replaces the UAT-only demand with meta-verifier demand sourced from `impl/demand/meta-verifier.md`; basic page/button UAT remains required but is nested under the broader meta-verifier acceptance process.

### Deprecated Capabilities
- `uat-module`: The historical standalone UAT protocol module is superseded because it is too rigid for the advanced meta-verifier requirement.

## Impact

- Affected demand source: `impl/demand/meta-verifier.md` is now the source of truth for this change.
- Affected implementation: `.claude/skills/meta-verifier/` should contain the meta-verifier skill entrypoint, protocol docs, orchestration scripts, checklist generation, browser execution integration, issue/report models, and sub-agent/persona coordination boundaries. `impl/` is the first project under test and may expose reusable project mechanisms, but it is not the meta-verifier skill home.
- Affected frontend scope: `http://127.0.0.1:8020/frontend/index.html` and all linked project pages must be exercised from the real entrypoint.
- Affected tests: `tests/` should cover checklist generation, report structure, browser evidence capture, and real 8020 meta-verifier smoke paths.
- Removed/deprecated implementation: existing UAT-only protocol code, docs, and tests should be deleted or replaced by meta-verifier equivalents.
- Dependencies: Selenium remains useful as the first browser-operation mechanism; Claude Code sub-agent execution becomes part of the advanced meta-verifier design.
