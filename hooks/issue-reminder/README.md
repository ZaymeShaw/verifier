# Issue-Reminder Hook

会话启动时扫描印记目录，提醒正在处理的 issue 或提示开始新 issue。

## 行为

1. 读取 `.claude/skills/issue-manager/config.yaml` 获取印记目录路径
2. 扫描印记目录下的 `issue-*.yaml` 文件
3. 过滤 `status: in_progress` 的 issue
4. 按配置的 `max_display` 限制显示数量
5. 输出每个活跃 issue 的信息

## 配置

配置项在 `issue-manager/config.yaml` 中：

```yaml
reminder:
  max_display: 5
```

## 输出示例

```
📌 当前正在处理 2 个 issue:
------------------------------------------------------------

1. Issue 123: fix-login-bug
   分支: issue-123-fix-login-bug
   印记: .claude/skills/issue-manager/active/issue-123-fix-login-bug.yaml

2. Issue 456: add-user-profile
   分支: issue-456-add-user-profile
   印记: .claude/skills/issue-manager/active/issue-456-add-user-profile.yaml

💡 提示: 使用 'issue-manager' skill 管理 issue
```

## 关联组件

- **issue-manager skill**: 管理印记文件
- **印记目录**: `.claude/skills/issue-manager/active/`
