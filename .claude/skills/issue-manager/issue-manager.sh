#!/usr/bin/env bash
# issue-manager wrapper script
# 统一入口：所有 issue 操作都通过此脚本调用 Python manage.py
# 这避免了 prompt 误推分支的风险 - 用户/Claude 只能用此脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGE_PY="$SCRIPT_DIR/manage.py"

# 安全检查：禁止任何形式的 git push 直接调用
# 所有 push 必须通过 manage.py publish 命令
if [[ "$#" -ge 1 ]] && [[ "$1" == "push" ]]; then
    echo "============================================================"
    echo "BLOCKED: 直接 push 命令被禁止"
    echo "请使用: issue-manager publish <issue_id>"
    echo "该命令会硬编码推送到 issue-{N}-{slug}-pr 分支"
    echo "============================================================"
    exit 2
fi

# 验证 Python 可用
if ! command -v python3 &> /dev/null; then
    echo "✗ python3 不可用"
    exit 1
fi

# 转发到 manage.py
exec python3 "$MANAGE_PY" "$@"
