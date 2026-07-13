---
name: draft
description: 围绕 objective 探索和优化项目角色实现，在固定数据集上比较 current/draft，并按 review 判断目标是否真正改善。不自动 promotion。
---

# Draft Skill

按 `verifier/spec/draft/draft.md` 工作。核心不是生成更多字段或完成一套表格，而是探索怎样实现 `objective`，并用真实实验和固定数据证明是否满足 `review`。

## Config

用户提供 YAML 内容或临时文件。字段、项目路径和灰度配置的关联方式见 `reference/draft_config_template.yaml`。

真正驱动工作的是：

- `objective`：要改善什么。
- `material`：从哪里理解项目和寻找优化路径。
- `mock_source`：项目已有的固定 mock 数据集。
- `review`：怎样判断目标是否真正改善。

## 工作循环

```text
生成/读取 config → 冻结 mock 数据 → 探索并生成 draft → 对比 current/draft
→ 用户可补充需求 → 修 draft/tool → 再验证
→ draft 真正优于 current，或达到上限后记录 blocker
```

1. 读取 config，理解 `objective`、`review` 和项目材料。
2. 从 `mock_source` 加载项目已有 mock 数据集并固定，整个 loop 不修改。
3. 运行 current，确认目标差距；探索源码、配置、业务链路和已有检查能力，通过实验验证优化方向。
4. 将有效探索写入 `draft/<role>.py`；结构与 production 一致，并实现协议自省得到的 `abstract_methods`。
5. 在同一数据集运行 current/draft，按真实实验逐条回答 `review`。
6. 用户可根据结果补充需求；修 draft/tool 后继续用同一数据验证。
7. objective 真正改善且无退化时才建议 promotion；否则记录验证过的方向和 blocker。

每轮只需说明：目标、实际探索/改动、关键实验与观察、current/draft 的目标差异、review 结论和遗留问题。

## 实际使用的工具

### 协议自省

```bash
$(读取 impl/config.yaml 的 python.executable) .claude/skills/draft/scripts/introspect_protocol.py impl/core/<role>_protocol.py
```

按输出实现 `abstract_methods`。

### Draft 校验

```bash
$(读取 impl/config.yaml 的 python.executable) .claude/skills/draft/scripts/check_draft.py --project <project> --role <role>
```

校验 draft 可编译、可加载、只有一个对应协议实现、abstract methods 完整，并能通过项目灰度配置实例化。

### Current / Draft 运行

- Attribute：`attribute/scripts/compare_attribute.py`
- Judge：`judge/scripts/compare_judge.py`

脚本只负责在同一批 case 上运行两边并保留原始结果；目标是否改善必须结合 `objective`、真实实验和 `review` 判断，不能由通用字段匹配代替。

## 硬原则

- mock 数据集在 loop 中固定；要换数据必须由用户明确更新 config。
- draft 遵守当前协议，位于项目 `draft/`，production 默认不加载。
- 证据来自当前运行、真实代码链路、业务接口或项目已有检查标准。
- 不写死 case，不把异常包装成成功，不用输出丰富度冒充效果。
- Judge 保持业务外部视角；Attribute 可以探索内部代码链路。角色原则见对应 `ROLE.md`。
- promotion 必须由用户确认；确认后覆盖 production 文件，并关闭 `<role>_draft.enabled`。

## 文件

```text
.claude/skills/draft/
├── SKILL.md
├── reference/
│   ├── draft_config_template.yaml
│   ├── project_yaml_draft_switch_template.yaml
│   └── draft_report_template.md
├── scripts/
│   ├── introspect_protocol.py
│   └── check_draft.py
├── attribute/
│   ├── ROLE.md
│   └── scripts/compare_attribute.py
└── judge/
    ├── ROLE.md
    └── scripts/compare_judge.py
```
