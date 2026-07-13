# 项目接入验收清单

接入一个新项目完成后，逐项跑过以下命令。**全部通过才算接入完成**——这是硬门禁，不是描述性检查。

## 1. 项目识别

```bash
bash run.sh cli projects
```
- 验收：新项目出现在列表中

## 2. adapter 静态合规

```bash
bash run.sh python scripts/check_adapter_compliance.py --project <id>
```
- 验收：✅ 通过，adapter 只含 `_load_*` 方法，无业务方法

## 3. 协议符合性探针

```bash
bash run.sh python scripts/verify_protocol_compliance.py --project <id>
```
- 验收：✅ 通过
- 检查内容：角色文件齐全、adapter `_load_*` 齐全、各角色类可实例化（`@abstractmethod` 全实现）
- 协议演进时此项自动卡住未跟进的项目

## 4. live_schema 不变量

```bash
bash run.sh python -c "from impl.projects.<id>.live_schema import REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, SCENARIO_ENUM, check; print('OK', len(SCENARIO_ENUM))"
```
- 验收：按命名规范导出齐全，`check` 可用，SCENARIO_ENUM 非空

## 5. mock 数据 schema 校验

```bash
bash run.sh cli mock-check --project <id>
```
- 验收：所有 case 的 schema 校验通过

## 6. 单链跑通

```bash
bash run.sh cli run-chain --project <id> --input '<REQUEST_SCHEMA 形状的 JSON>'
```
- 验收：live → judge → attribute → check 全链路返回，不报错
- 注：纯新协议 `ProjectAdapter` 项目在 core 迁移完成前可能因 `to_run_trace` 缺口失败，过渡期可暂用 `LegacyProjectAdapter`（见 SKILL.md Step 9 说明）

## 7. mock 数据固化

```bash
ls impl/data/<id>/mock_cases.json
```
- 验收：文件存在，且 `mock-check` 通过

## 8. 纳入回归

```bash
grep -q "<id>" impl/checklist/check1.py && echo "已纳入" || echo "未纳入"
```
- 验收：check1.py 的 CONFIG 含新项目

## 现有项目不回归（接入时副作用检查）

```bash
bash run.sh python scripts/check_adapter_compliance.py
bash run.sh python scripts/verify_protocol_compliance.py
```
- 验收：现有 4 个项目仍全部通过，未因接入改动产生回归
