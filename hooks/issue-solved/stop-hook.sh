#!/bin/bash
# Issue-Solved Stop Hook — 从 config.yaml 读取配置
#
# 职责：仅做轻量决策，不维护任何状态文件
# - 从 config.yaml 加载所有可配置项（依赖 python3 + yaml）
# - 检查 issue 是否 closed（frontmatter 的 status:，忽略大小写）
# - 读取 issue/audit/{issueid}.txt 获取审核 verdict
# - 决策：block（要求审核或修复）或 allow（放行）
#
# 依赖：
#   python3 + pyyaml — YAML 解析（安装: pip3 install pyyaml）
#   jq — JSON 输出（macOS: brew install jq, Linux: apt install jq）
#
# 数据流：
#   config.yaml                  ← hook 读取所有配置项
#   issue/{id}.md                ← hook 读取（判断 closed）
#   issue/audit/{issueid}.txt    ← 审核 agent 写入（verdict），hook 读取决策
#   audit-prompt.md              ← hook 读取（审核标准模板）
#
# 无状态文件！每次触发都重新检查。

set -euo pipefail

HOOK_INPUT=$(cat)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# =========================
# 从 config.yaml 加载配置
# =========================
CONFIG_FILE="$SCRIPT_DIR/config.yaml"

# 用 python3 解析 YAML 输出为 shell 可读格式
eval "$(python3 -c "
import yaml, sys
with open('$CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)
def val(v):
    if isinstance(v, str):
        # escape for shell eval
        v = v.replace(\"'\", \"'\\\\''\")
        return f\"'{v}'\"
    return str(v)
print(f\"export ISSUE_DIR={val(cfg['issue']['dir'])}\")
print(f\"export ISSUE_FILE_PATTERN={val(cfg['issue']['file_pattern'])}\")
print(f\"export STATUS_FIELD={val(cfg['status']['field_name'])}\")
print(f\"export CLOSED_VALUE={val(cfg['status']['closed_value'].lower())}\")
print(f\"export OPEN_VALUE={val(cfg['status']['open_value'].lower())}\")
print(f\"export AUDIT_DIR={val(cfg['audit']['dir'])}\")
print(f\"export AUDIT_FILE_PATTERN={val(cfg['audit']['file_pattern'])}\")
print(f\"export VERDICT_FIELD={val(cfg['verdict']['verdict_field'])}\")
print(f\"export APPROVED_VALUE={val(cfg['verdict']['approved_value'])}\")
print(f\"export REJECTED_VALUE={val(cfg['verdict']['rejected_value'])}\")
print(f\"export REASON_FIELD={val(cfg['verdict']['reason_field'])}\")
")"

# =========================
# 查找当前目录下的所有 issue 文件
# =========================
CURRENT_DIR=$(echo "$HOOK_INPUT" | jq -r '.cwd // ""')
if [[ -n "$CURRENT_DIR" ]] && [[ -d "$CURRENT_DIR" ]]; then
  SCAN_DIR="$CURRENT_DIR"
else
  SCAN_DIR="$PROJECT_ROOT"
fi

# 查找所有 issue 文件
ISSUE_FILES=$(find "$SCAN_DIR/$ISSUE_DIR" -maxdepth 1 -name "$ISSUE_FILE_PATTERN" -type f 2>/dev/null || true)

if [[ -z "$ISSUE_FILES" ]]; then
  exit 0
fi

# =========================
# 两阶段检查：先收集所有 closed issue 的状态，再统一决策
# =========================
NEED_AUDIT_ISSUES=()
REJECTED_ISSUES=()
ALLOW_EXIT=true

for ISSUE_PATH in $ISSUE_FILES; do
  # 检查 frontmatter 中的 status（忽略大小写）
  ISSUE_STATUS=$(grep "^$STATUS_FIELD" "$ISSUE_PATH" | sed "s/$STATUS_FIELD *//" | tr -d '"' | tr -d ' ' | tr '[:upper:]' '[:lower:]')

  if [[ "$ISSUE_STATUS" != "$CLOSED_VALUE" ]]; then
    continue
  fi

  # 从 issue_path 提取 issue 编号
  ISSUE_ID=$(basename "$ISSUE_PATH" .md | sed 's/-.*//')

  # 构建审核文件路径（替换模板变量）
  AUDIT_FILE="$PROJECT_ROOT/$AUDIT_DIR/$(echo "$AUDIT_FILE_PATTERN" | sed "s/{issue_id}/$ISSUE_ID/g")"

  if [[ -f "$AUDIT_FILE" ]]; then
    if grep -q "$VERDICT_FIELD *$APPROVED_VALUE" "$AUDIT_FILE"; then
      # APPROVED：检查 issue 是否在审核后被再次修改（用户更新诉求后重新 close）
      if command -v stat &>/dev/null; then
        ISSUE_MTIME=$(stat -f %m "$ISSUE_PATH" 2>/dev/null || echo 0)
        AUDIT_MTIME=$(stat -f %m "$AUDIT_FILE" 2>/dev/null || echo 0)
      elif command -v date &>/dev/null; then
        # Linux fallback
        ISSUE_MTIME=$(stat -c %Y "$ISSUE_PATH" 2>/dev/null || echo 0)
        AUDIT_MTIME=$(stat -c %Y "$AUDIT_FILE" 2>/dev/null || echo 0)
      else
        ISSUE_MTIME=0
        AUDIT_MTIME=0
      fi

      if [ "$ISSUE_MTIME" -gt "$AUDIT_MTIME" ]; then
        # 用户在 APPROVED 后又更新了 issue 并重新 close → 删除旧审核，重新审核
        rm "$AUDIT_FILE"
        NEED_AUDIT_ISSUES+=("$ISSUE_PATH")
      fi
      continue
    elif grep -q "$VERDICT_FIELD *$REJECTED_VALUE" "$AUDIT_FILE"; then
      # REJECTED：检查 issue 是否已被修改（用户修复后重新 close）
      if command -v stat &>/dev/null; then
        ISSUE_MTIME=$(stat -f %m "$ISSUE_PATH" 2>/dev/null || echo 0)
        AUDIT_MTIME=$(stat -f %m "$AUDIT_FILE" 2>/dev/null || echo 0)
      elif command -v date &>/dev/null; then
        # Linux fallback
        ISSUE_MTIME=$(stat -c %Y "$ISSUE_PATH" 2>/dev/null || echo 0)
        AUDIT_MTIME=$(stat -c %Y "$AUDIT_FILE" 2>/dev/null || echo 0)
      else
        ISSUE_MTIME=0
        AUDIT_MTIME=0
      fi

      if [ "$ISSUE_MTIME" -gt "$AUDIT_MTIME" ]; then
        # 用户已修复并重新 close → 删除旧审核，重新审核
        rm "$AUDIT_FILE"
        NEED_AUDIT_ISSUES+=("$ISSUE_PATH")
      else
        # 未修复，记录 REJECTED
        REJECT_REASON=$(grep "^$REASON_FIELD" "$AUDIT_FILE" | sed "s/$REASON_FIELD *//" || echo "审核 agent 未提供具体原因")
        REJECTED_ISSUES+=("$ISSUE_ID: $REJECT_REASON")
        ALLOW_EXIT=false
      fi
      continue
    fi
  fi

  # closed 但没有审核 verdict → 需要发起审核
  NEED_AUDIT_ISSUES+=("$ISSUE_PATH")
done

# =========================
# 统一决策
# =========================

if [ ${#NEED_AUDIT_ISSUES[@]} -gt 0 ]; then
  # 有 issue 需要审核 → block
  mkdir -p "$PROJECT_ROOT/$AUDIT_DIR"

  ISSUE_LIST=""
  for ISSUE_PATH in "${NEED_AUDIT_ISSUES[@]}"; do
    ISSUE_ID=$(basename "$ISSUE_PATH" .md | sed 's/-.*//')
    AUDIT_FILE="$PROJECT_ROOT/$AUDIT_DIR/$(echo "$AUDIT_FILE_PATTERN" | sed "s/{issue_id}/$ISSUE_ID/g")"
    ISSUE_LIST="$ISSUE_LIST- \`$ISSUE_PATH\` → verdict 写入 \`$AUDIT_FILE\`\n"
  done

  jq -n \
    --arg issues "$ISSUE_LIST" \
    '{
      "decision": "block",
      "reason": ("以下 issue 已标记为 closed，但缺少审核 verdict：\n\n" + $issues + "\n请为每个 issue 执行：\n1. Read 审核标准文件：`hooks/issue-solved/audit-prompt.md`\n2. Spawn 独立审核 agent\n3. 审核 agent 写入 verdict\n4. 用户关闭会话触发 re-check"),
      "systemMessage": "🔍 Issue 审核：请启动独立审核 agent"
    }'
  exit 0
fi

if $ALLOW_EXIT; then
  exit 0
else
  REJECTED_TEXT=""
  for REJECTED in "${REJECTED_ISSUES[@]}"; do
    REJECTED_TEXT="$REJECTED_TEXT- $REJECTED\n"
  done

  jq -n \
    --arg rejected "$REJECTED_TEXT" \
    --arg msg "❌ Issue 审核未通过" \
    '{
      "decision": "block",
      "reason": ("审核 agent 认为以下 issue 的核心诉求尚未解决：\n\n" + $rejected + "\n请针对上述问题进行实质性修复，完成后更新 issue 内容并再次 close。\n\n注意：修复后再次关闭会话时，hook 会自动识别 issue 已更新并触发重新审核。"),
      "systemMessage": $msg
    }'
  exit 0
fi