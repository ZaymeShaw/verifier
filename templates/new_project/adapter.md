# 项目接入模板

本项目目录包含 verifier 新项目的标准模板。

## 使用方式

新项目通过 `scripts/scaffold_project.py` 动态生成骨架，不再手动复制模板文件。

```bash
bash run.sh python scripts/scaffold_project.py --project <project_id>
```

脚手架会：
1. 扫描协议基类（`impl/core/*_protocol.py`）
2. 根据 `@abstractmethod` 生成项目层 stub
3. 输出到 `impl/projects/<project_id>/`

## 生成内容

脚手架生成以下文件（全部为 stub，需项目层填充业务逻辑）：

- `project.yaml` — 项目配置
- `adapter.py` — 继承 `ProjectAdapter`，实现 `_load_*` 加载各角色
- `live.py` — 继承 `ProjectLive`，实现被测系统调用
- `mock.py` — 继承 `ProjectMock`，实现测试数据生成
- `judge.py` — 继承 `ProjectJudge`，实现输出评估
- `attribute.py` — 继承 `ProjectAttribute`，实现问题归因
- `tools.py` — 继承 `ProjectTools`，实现工具能力

## 后续步骤

1. 冻结 `live_schema`（不变量）
2. 填充各角色 stub 的业务逻辑
3. 运行合规检查：`bash run.sh python scripts/check_adapter_compliance.py --project <project_id>`
4. 运行协议符合性检查：`bash run.sh python scripts/verify_protocol_compliance.py --project <project_id>`
5. 执行端到端验证（mock-check + run-chain）

## 设计原则

- **动态发现**：脚手架根据协议基类的 `@abstractmethod` 生成，协议演进时自动覆盖
- **不写死方法名**：通过命名规范 + 协议基类反射，适配未来变化
- **工程口径统一**：脚本和校验工具放在工程 `scripts/`，skill 只引用不重复实现
