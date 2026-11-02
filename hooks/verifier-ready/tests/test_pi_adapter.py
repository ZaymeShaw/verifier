"""Exercise TypeScript directly, including the installed pi extension runtime."""
import os
from pathlib import Path
import shutil
import subprocess

from common import HERE


def test_pi_adapter_in_node_and_actual_extension_runner():
    executable = shutil.which('pi')
    assert executable, 'Independent hook verification requires the installed pi runtime'
    package = Path(executable).resolve().parents[2]
    assert (package / 'dist/core/extensions/loader.js').is_file()
    env = {**os.environ, 'PI_GATE_TEST_PACKAGE': str(package)}
    result = subprocess.run(['node', '--test', str(HERE / 'tests/test_pi_hook.mjs')], env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
