# Evidence Standards

## Evidence status

| Status | 条件 |
|---|---|
| `confirmed` | 有 browser action trace / screenshot / API response / code reference / run output 直接支撑 |
| `partially_supported` | 部分证据，但不足以完全确认 |
| `hypothesis` | 合理推测，无直接证据 |
| `unverified_reviewer_critique` | 来自独立 reviewer/critique agent，无独立证据验证 |

## Evidence sources

| Source | 适用范围 |
|---|---|
| `browser` | 前端页面、按钮、链路、UI 状态 |
| `code` | 实现逻辑、函数、配置 |
| `artifact` | 需求文档、协议、skill 文档 |
| `run` | 命令执行结果、API 响应、日志 |
| `reviewer` | 独立角色 critique，不可单独作为 confirmed 来源 |

## 关键规则

- 子进程（demanding user）的判断默认标 `unverified_reviewer_critique`
- 只有被 browser/code/artifact/run evidence 独立验证过的才能升为 `confirmed`
- browser surface 可见时，frontend 相关 finding 必须有 browser evidence
- 不可见面上的判断必须标注 confidence impact
