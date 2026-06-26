import io
import importlib.util
from pathlib import Path


def load_worktree_create_module():
    script = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "worktree_create.py"
    spec = importlib.util.spec_from_file_location("worktree_create", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worktree_create_echoes_plain_created_path(monkeypatch, tmp_path, capsys):
    module = load_worktree_create_module()
    repo = tmp_path / "repo"
    repo.mkdir()

    calls = []

    class Result:
        def __init__(self, stdout=""):
            self.stdout = stdout

    def fake_run(args, cwd=None):
        calls.append(args)
        if args[:4] == ["git", "-C", str(repo), "rev-parse"]:
            return Result(str(repo) + "\n")
        if args[:4] == ["git", "-C", str(repo), "worktree"]:
            worktree_path = Path(args[-2])
            worktree_path.mkdir(parents=True)
            return Result()
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(module.uuid, "uuid4", lambda: type("U", (), {"hex": "abcdef1234567890"})())
    monkeypatch.setattr(module.sys, "stdin", io.StringIO('{"cwd": "' + str(repo) + '"}'))

    module.main()

    out = capsys.readouterr().out.strip()
    expected = repo / ".claude" / "worktrees" / "claude-agent-abcdef123456"
    assert out == str(expected)
    assert expected.is_dir()
