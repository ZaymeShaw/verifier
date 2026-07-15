# Issue Manager 操作指南

## 安全机制

⚠️ **核心原则：所有 push 操作必须通过 `publish` 命令，严禁直接 git push**

### 双重保护

1. **代码硬编码保护**（manage.py）：
   - `PR_TARGET_BRANCH = f"issue-{N}-{slug}-pr"` 硬编码目标分支
   - 禁止任何包含 main/master/trunk/develop/dev 的分支名
   - 必须以 `-pr` 结尾

2. **入口脚本保护**（issue-manager.sh）：
   - 禁止任何形式的 `git push <...>` 直接调用
   - 必须使用 `issue-manager publish <id>` 通过 wrapper 脚本

### 使用示例

```bash
# ✅ 正确：通过 issue-manager shell 脚本
python3 .claude/skills/issue-manager/manage.py pull 123
python3 .claude/skills/issue-manager/manage.py checkout 123
python3 .claude/skills/issue-manager/manage.py publish 123

# ✅ 正确：从项目根目录直接调用（推荐）
./.claude/skills/issue-manager/issue-manager.sh pull 123
./.claude/skills/issue-manager/issue-manager.sh publish 123

# ❌ 错误：直接 git push（会被 wrapper 拦截 + PreCommand hook 级别阻止）
git push origin issue-123-xxx
git push origin main
```

## 命令流程

```
pull 123
  ↓ 创建 issue-123-{slug} 分支，生成印记 issue-123-{slug}.yaml
开发，提交代码
  ↓
checkout 123
  ↓ 切换到 issue-123-{slug} 分支（从印记读取 slug）
开发，提交代码
  ↓
publish 123
  ↓ 推送到 issue-123-{slug}-pr，创建 PR
```

## 关键约定

1. **slug 来自印记文件**：publish/checkou 都从印记文件读取 slug，确保分支一致性
2. **并行 blocking**：同一 issue_id 的印记文件只能有一个，后续 pull 会覆盖旧的
3. **未提交改动保护**：任何 checkout/pull/fetch 前检查未提交改动
