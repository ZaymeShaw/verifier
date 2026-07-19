from __future__ import annotations

import json

from impl.context.__main__ import main


def test_context_init_without_project_adapter_exits_safely(tmp_path, capsys):
    main(["init", "--project", "QA", "--data-root", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["project_id"] == "QA"
    assert payload["adapter_count"] == 0
    assert payload["record_count"] == 0
    assert payload["project_adapters"] == []
    assert payload["message"] == "project has no configured context units yet"
