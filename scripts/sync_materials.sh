#!/bin/bash
set -euo pipefail

# 把物化/自由资料按目录同步到远端评测机（只拷 impl/data/<project>/materials/<id>/，
# 绝不全量覆盖 impl/data，评测机上的运行数据不受影响）。
#
# 用法：
#   scripts/sync_materials.sh --host user@host --project <id> --ids id1,id2 [--remote-path /opt/verifier]
#   bash run.sh cli materialize --project X --role judge --apply \
#       | scripts/sync_materials.sh --host user@host --project X --from-materialize-json -
#   scripts/sync_materials.sh --host user@host --project X --all-free
#
# 资料来源三选一：
#   --ids                    逗号分隔的资料 id
#   --from-materialize-json  materialize CLI 的 stdout JSON（文件路径或 - 表示 stdin），取 written[].id
#   --all-free               本机该项目的全部自由资料
#
# Windows 用户请在 WSL 里运行（依赖 bash/rsync/ssh）。

cd "$(dirname "$0")/.."

usage() {
  sed -n '4,18p' "$0" | sed 's/^# \{0,1\}//'
}

HOST=""
REMOTE_PATH="/opt/verifier"
PROJECT=""
IDS=""
FROM_JSON=""
ALL_FREE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2;;
    --remote-path) REMOTE_PATH="$2"; shift 2;;
    --project) PROJECT="$2"; shift 2;;
    --ids) IDS="$2"; shift 2;;
    --from-materialize-json) FROM_JSON="$2"; shift 2;;
    --all-free) ALL_FREE=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 1;;
  esac
done

if [ -z "$HOST" ] || [ -z "$PROJECT" ]; then
  echo "--host 与 --project 必填" >&2
  usage >&2
  exit 1
fi

selectors=0
[ -n "$IDS" ] && selectors=$((selectors + 1))
[ -n "$FROM_JSON" ] && selectors=$((selectors + 1))
[ "$ALL_FREE" = 1 ] && selectors=$((selectors + 1))
if [ "$selectors" -ne 1 ]; then
  echo "--ids / --from-materialize-json / --all-free 三选一" >&2
  exit 1
fi

if [ -n "$IDS" ]; then
  MATERIAL_IDS=$(echo "$IDS" | tr ',' '\n' | sed '/^$/d')
elif [ -n "$FROM_JSON" ]; then
  SRC="$FROM_JSON"
  [ "$SRC" = "-" ] && SRC=/dev/stdin
  MATERIAL_IDS=$(python3 -c '
import json, sys
data = json.load(open(sys.argv[1]))
ids = [str(item["id"]) for item in data.get("written") or [] if item.get("id")]
print("\n".join(ids))
' "$SRC")
else
  MATERIAL_IDS=$(bash run.sh python -c '
import sys
from impl.core.materials_store import list_materials
print("\n".join(item["id"] for item in list_materials(sys.argv[1])["free"]))
' "$PROJECT")
fi

MATERIAL_IDS=$(echo "$MATERIAL_IDS" | sed '/^$/d')
if [ -z "$MATERIAL_IDS" ]; then
  echo "没有可同步的资料 id" >&2
  exit 1
fi

REMOTE_MATERIALS="$REMOTE_PATH/impl/data/$PROJECT/materials"
ssh "$HOST" "mkdir -p '$REMOTE_MATERIALS'"

COUNT=0
while IFS= read -r id; do
  local_dir="impl/data/$PROJECT/materials/$id"
  if [ ! -d "$local_dir" ]; then
    echo "本地资料目录不存在: $local_dir" >&2
    exit 1
  fi
  echo "同步 $id ..."
  rsync -az --delete "$local_dir/" "$HOST:$REMOTE_MATERIALS/$id/"
  COUNT=$((COUNT + 1))
done <<< "$MATERIAL_IDS"

echo "完成：$COUNT 份资料 → $HOST:$REMOTE_MATERIALS"
