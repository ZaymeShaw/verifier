#!/usr/bin/env bash
# Manual helper for Bash/Zsh. Use source so exports remain in the current shell:
#   source scripts/import-env.sh [path/to/.env-dynamic]
# This helper is not part of run.sh or the application's configuration loader.

if [ -n "${BASH_VERSION-}" ] && [ "${BASH_SOURCE[0]}" = "$0" ]; then
    printf '%s\n' '请用 source scripts/import-env.sh；直接执行不能设置当前终端的环境变量。' >&2
    exit 1
elif [ -n "${ZSH_VERSION-}" ] && [[ "$ZSH_EVAL_CONTEXT" != *:file ]]; then
    printf '%s\n' '请用 source scripts/import-env.sh；直接执行不能设置当前终端的环境变量。' >&2
    exit 1
fi

_verifier_import_env() {
    local script_path repo_root env_exports
    if [ -n "${ZSH_VERSION-}" ]; then
        script_path=${(%):-%x}
    else
        script_path=${BASH_SOURCE[0]}
    fi
    repo_root=$(cd -- "$(dirname -- "$script_path")/.." && pwd) || return 1
    env_exports=$(python3 -B - "$repo_root" "${1:-$repo_root/.env-dynamic}" <<'PY'
import shlex
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from impl.core.config_bootstrap import parse_dotenv

path = Path(sys.argv[2])
if not path.is_file():
    sys.exit(f"环境变量文件不存在：{path}")
try:
    values = parse_dotenv(path)
except ValueError as exc:
    sys.exit(str(exc))
for name, value in values.items():
    print(f"export {name}={shlex.quote(value)}")
PY
    ) || return 1
    # Only evaluate validated names and shell-quoted literal values, never file text.
    eval "$env_exports"
}

if _verifier_import_env "$@"; then
    unset -f _verifier_import_env
else
    unset -f _verifier_import_env
    return 1
fi
