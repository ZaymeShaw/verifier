#!/bin/bash
set -euo pipefail

# 全量部署 verifier 代码到远端（docs/external-eval-deployment.md「更新代码」一节的封装）。
# 排除项锚定到仓库根（前导 /）：绝不覆盖远端 /impl/data、/.env；
# 也不把报告、调查循环历史（draft/.state）送上去。
# 不锚定的 --exclude experiments 会误伤调查包里的 experiments/ 冻结产物。
#
# 用法：
#   scripts/deploy_verifier.sh user@host [/opt/verifier] [--no-restart] [--dry-run]
#
# 默认部署后 ssh 执行 systemctl restart verifier；--no-restart 跳过。
# --dry-run 只预览相对远端内容会变更的文件（按 checksum 比较，清单 + 总大小），不改远端。
# Windows 用户请在 WSL 里运行（依赖 bash/rsync/ssh）。

cd "$(dirname "$0")/.."

usage() {
  sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'
}

HOST=""
REMOTE_PATH="/opt/verifier"
RESTART=1
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --no-restart) RESTART=0;;
    --dry-run) DRY_RUN=1;;
    -h|--help) usage; exit 0;;
    -*) echo "未知参数: $arg" >&2; usage >&2; exit 1;;
    *)
      if [ -z "$HOST" ]; then HOST="$arg"
      else REMOTE_PATH="$arg"
      fi
      ;;
  esac
done

if [ -z "$HOST" ]; then
  echo "缺少远端主机（user@host）" >&2
  usage >&2
  exit 1
fi

# 锚定仓库根的目录排除；.DS_Store / __pycache__ / .state 不锚定，匹配任意层级。
# 不排除 .agents / .claude / .codex / .github，以及 search-test-case / demand / hooks / agents / data。
EXCLUDES=(
  --exclude /.git
  --exclude /.env
  --exclude /.pytest_cache
  --exclude /.tmp-model-channel
  --exclude /tmp
  --exclude /experiments
  --exclude /issues
  --exclude /issue
  --exclude /tests
  --exclude /info-dense
  --exclude /report
  --exclude /reviews-of-propose
  --exclude /openspec
  --exclude /impl/data
  --exclude .DS_Store
  --exclude __pycache__
  --exclude .state
)

_print_checksum_delta() {
  local dest="$1"
  python3 -c '
import os, sys
from collections import defaultdict

dest = sys.argv[1]
rows = []  # (kind, path)
for raw in sys.stdin:
    line = raw.strip()
    if not line or line[0] not in "<>.":
        continue
    parts = line.split(None, 1)
    if len(parts) < 2:
        continue
    code, path = parts
    if path in (".",) or code.startswith(("cd", ".d", "cL")):
        continue
    if not (code.startswith("<f") or code.startswith(">f")):
        continue
    flags = code[2:]
    if flags and all(ch == "+" for ch in flags):
        kind = "新建"
    elif "s" in flags or "c" in flags:
        kind = "内容变更"
    else:
        continue  # 仅时间戳/权限，checksum 下不会传内容
    rows.append((kind, path))

def human(n):
    units = ("B", "KB", "MB", "GB")
    i, f = 0, float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{n} B" if i == 0 else f"{f:.1f} {units[i]}"

print("=== 相对远端内容会变更的文件（checksum） ===")
if not rows:
    print("  （无）")
    print()
    print(f"相对远端内容会变更的文件：0 个文件，合计 0 B → {dest}")
    print()
    sys.exit(0)

sized = []
for kind, path in rows:
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    sized.append((kind, path, size))

groups = defaultdict(lambda: [0, 0])
for kind, path, size in sized:
    top = path.split("/", 1)[0]
    groups[top][0] += 1
    groups[top][1] += size

print("--- 顶层目录 ---")
for top, (count, total) in sorted(groups.items(), key=lambda item: -item[1][1]):
    print(f"  {top:<28} {count:>6} 个文件  {human(total)}")
print()
print("--- 文件清单 ---")
for kind, path, size in sorted(sized, key=lambda item: item[1]):
    print(f"  [{kind}] {path}  ({human(size)})")
print()
total_n = len(sized)
total_b = sum(size for _, _, size in sized)
print(f"相对远端内容会变更的文件：{total_n} 个文件，合计 {human(total_b)}（{total_b} bytes）→ {dest}")
print()
' "$dest"
}

# -c/--checksum：按内容比较，忽略 checkout 造成的 mtime 差异。
RSYNC_FLAGS=(-azc)

if [ "$DRY_RUN" = 1 ]; then
  DELTA_OUT=$(rsync "${RSYNC_FLAGS[@]}" -n --itemize-changes "${EXCLUDES[@]}" ./ "$HOST:$REMOTE_PATH/")
  echo "$DELTA_OUT" | _print_checksum_delta "${HOST}:${REMOTE_PATH}"
  echo "dry-run 完成，未改动远端。"
  exit 0
fi

rsync "${RSYNC_FLAGS[@]}" --stats "${EXCLUDES[@]}" ./ "$HOST:$REMOTE_PATH/"

if [ "$RESTART" = 1 ]; then
  ssh "$HOST" 'systemctl restart verifier'
  echo "部署完成并已重启 verifier：$HOST:$REMOTE_PATH"
else
  echo "部署完成（未重启）：$HOST:$REMOTE_PATH"
fi
