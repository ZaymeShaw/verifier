# Project 配置模板

`project.yaml` 只配置项目之间不固定、需要项目自己声明的内容。固定约定不放进模板：

- adapter 固定为 `impl/projects/<project_id>/adapter.py`
- 常用项目文档默认按固定文件名读取，例如 `application.md`、`evaluation.md`、`judge_boundary.md`、`attribution.md`、`checklist.md`、`mock.md`

新增项目优先参考：

```text
impl/projects/project.template.yaml
```

最小结构：

```yaml
project_id: example
name: 示例项目
description: 简短说明这个项目测什么

common:
  source:
    repo:

  api:
    base_url:
    endpoint:
    method: POST
    timeout: 60

  start:
    command:

extra: {}
```

## 公共层 common

`common` 只放相对通用、但每个项目取值不同的配置：

- `common.source.repo`：原项目代码位置。没有原项目代码时留空。
- `common.api`：项目主调用接口。
- `common.start.command`：项目启动脚本或命令。不由 verifier 启动时留空。

## 额外层 extra

`extra` 放项目特有配置，不强制结构，例如：

```yaml
extra:
  protocol: sse
  scenarios: []
  source_docs: {}
  downstream_search: {}
  semantic_equivalence_rules: {}
  frontend_extensions: {}
```

## 兼容旧配置

现有项目里的旧字段暂时仍兼容：

- 顶层 `api` 会作为 `common.api` 的 fallback。
- `application.external_repo` 会作为 `common.source.repo` 的 fallback。
- `documents` 仍可覆盖默认文档路径。
- `frontend_extensions` 暂时保留，后续项目特有配置可以逐步迁到 `extra`。


# 特定字段说明
> common.ready:一个列表，枚举值包括[output,reference],表示此场景可以直接通过输入获取的信息
- ready：已经获取的信息，通常通过mock agent提前产出，由mock agent的意图模块产生，不通过测评系统后续的live/judge/attr等trace生成。
- 非ready：未获取的信息，需经过测评系统trace生成（live、judge等环节）
  + output：mock agent与live系统交互过程中，由live产出
  + reference：代表参考答案，由judge agent负责产出