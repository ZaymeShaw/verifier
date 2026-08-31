#!/bin/bash
set -euo pipefail

# 全量部署 verifier 到远端（docs/external-eval-deployment.md「更新代码」一节的封装）。
# 资料（impl/data 下的 capability / materials / mock / case 池）随代码一起过去，大约数 MB。
# 排除项锚定到仓库根（前导 /）：不覆盖远端 /.env，也不送本地评测痕迹
# （context_store / context_runtime，约数十 MB）和报告、调查循环历史（.state）。
# rsync 不用 --delete：评测机上多出来的文件会留着。
# capability 预设的 service.url 部署后写回评测机原值（本机是 8000，评测机是 1500X）。
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
  sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'
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
# impl/data 要传（资料不多）；只剔本地运行痕迹。
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
  --exclude /impl/data/context_store
  --exclude /impl/data/context_runtime
  --exclude .DS_Store
  --exclude __pycache__
  --exclude .state
)

_snapshot_capability_services() {
  ssh "$HOST" "python3 - '$REMOTE_PATH'" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1]) / "impl/data"
out = {}
if root.exists():
    for path in sorted(root.glob("*/capability_map.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        services = {}
        for name, entry in data.items():
            service = entry.get("service") if isinstance(entry, dict) else None
            if isinstance(service, dict) and str(service.get("url") or "").strip():
                services[name] = service
        if services:
            out[path.parent.name] = services
print(json.dumps(out, ensure_ascii=False))
PY
}

_restore_capability_services() {
  python3 - "$1" "$HOST" "$REMOTE_PATH" <<'PY'
import json, shlex, subprocess, sys
from pathlib import Path

saved = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
host, remote_path = sys.argv[2], sys.argv[3]
if not saved:
    sys.exit(0)
for project, services in saved.items():
    local = Path("impl/data") / project / "capability_map.json"
    if not local.is_file():
        continue
    data = json.loads(local.read_text(encoding="utf-8"))
    dirty = False
    for name, service in services.items():
        entry = data.get(name)
        if not isinstance(entry, dict):
            continue
        if entry.get("service") != service:
            entry["service"] = service
            dirty = True
    if not dirty:
        continue
    dest = f"{remote_path}/impl/data/{project}/capability_map.json"
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    subprocess.run(["ssh", host, f"cat > {shlex.quote(dest)}"], input=payload, check=True)
    urls = ", ".join(f"{name}={service.get('url')}" for name, service in services.items())
    print(f"已保留评测机探测 URL：{project} {urls}")
PY
}

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

SNAP_FILE=$(mktemp)
trap 'rm -f "$SNAP_FILE"' EXIT
_snapshot_capability_services > "$SNAP_FILE"

rsync "${RSYNC_FLAGS[@]}" --stats "${EXCLUDES[@]}" ./ "$HOST:$REMOTE_PATH/"
_restore_capability_services "$SNAP_FILE"

if [ "$RESTART" = 1 ]; then
  ssh "$HOST" 'systemctl restart verifier'
  echo "部署完成并已重启 verifier：$HOST:$REMOTE_PATH"
else
  echo "部署完成（未重启）：$HOST:$REMOTE_PATH"
fi
