from __future__ import annotations

import difflib
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from scripts.record_golden import execute_case
from tests.support import cassette
from scripts.trace_canonicalize import canonical_json

GOLDEN_ROOT = Path(__file__).parent / "golden"
GOLDEN_DIRS = sorted(path for path in GOLDEN_ROOT.glob("*/*") if path.is_dir())


@pytest.mark.parametrize(
    "directory",
    GOLDEN_DIRS
    or [
        pytest.param(
            None, marks=pytest.mark.skip(reason="No golden recordings")
        ),
    ],
    ids=[str(path.relative_to(GOLDEN_ROOT)) for path in GOLDEN_DIRS]
    or ["no-goldens"],
)
def test_golden_replay(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """阶段 1 门禁：多轮录制回放产出逐字节相同的规范 trace。"""

    project_id = directory.parent.name
    case = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    execution = json.loads(
        (directory / "execution.json").read_text(encoding="utf-8")
    )
    expected = (directory / "trace.canonical.json").read_text(encoding="utf-8")
    monkeypatch.setenv("VERIFIER_CASSETTE", "replay")
    monkeypatch.setenv("VERIFIER_CASSETTE_DIR", str(directory))
    network_calls = []

    def no_network(*args: Any, **kwargs: Any) -> Any:
        network_calls.append((args, kwargs))
        raise AssertionError("Golden replay attempted a real network call")

    cassette.install()
    try:
        monkeypatch.setattr(urllib.request, "urlopen", no_network)
        trace = execute_case(project_id, case, replay=True, **execution)
        actual = canonical_json(trace, project_id)
        cassette.assert_exhausted()
        assert not network_calls, "Golden replay attempted network access"
        assert actual == expected, "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=str(directory / "trace.canonical.json"),
                tofile="replay",
            )
        )
    finally:
        cassette.uninstall()
