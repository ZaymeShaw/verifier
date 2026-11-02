"""调用记录落档契约：带机器绝对路径的内容不能把整条记录弄丢。

实测背景：整理阶段用了工具、模型把记录编号写成文件路径（tool_args.path = /Users/...），
路径契约抛 PathContractError，而 _track_context 把异常吞掉 —— 整条调用记录静默消失，
成本审计看不到用了工具的调用。更早的旧批次轴记录目录整个是空的，同一个原因。
"""
from impl.core import context_store
from impl.core.context_store import save_context
from impl.core.llm_client import _portable, _track_context
from impl.core.schema.context import ContextRecord


def test_portable_redacts_machine_absolute_paths():
    assert _portable("/Users/a/b.json") == "<绝对路径已隐去>"
    assert _portable("读 /tmp/x/y 与 /home/z/w") == "读 <绝对路径已隐去> 与 <绝对路径已隐去>"
    assert _portable({"tool_args": {"path": "/Users/a/b.json"}}) == {
        "tool_args": {"path": "<绝对路径已隐去>"}
    }
    assert _portable([{"content": "见 /private/var/t.json"}]) == [{"content": "见 <绝对路径已隐去>"}]


def test_portable_redacts_any_absolute_path_in_a_path_named_field():
    """模型会把记录编号当成 JSON 路径写成 /records/run：路径字段里的绝对路径同样被契约拒绝。"""
    assert _portable({"tool_args": {"path": "/records/run/content"}}) == {
        "tool_args": {"path": "<绝对路径已隐去>"}
    }
    assert _portable({"root": "~/x"}) == {"root": "<绝对路径已隐去>"}
    assert _portable({"file": "file://x/y"}) == {"file": "<绝对路径已隐去>"}


def test_portable_keeps_normal_strings_and_relative_paths():
    for value in ("turn1/records/run", "/api/v1/query", "保单号 P002", "", "见 spec/adapter/x.md"):
        assert _portable(value) == value


def _isolate(tmp_path, monkeypatch) -> None:
    store_root = tmp_path / "impl" / "data" / "context_store"
    context = context_store.DEFAULT_ACTIVE_ARTIFACT_REGISTRY.context(
        context_store.REPOSITORY_ROOT,
        environ={"CONTEXT_STORE_ROOT": str(store_root)},
    )
    monkeypatch.setattr(context_store, "_ACTIVE_ARTIFACT_CONTEXT", context)


class _Result:
    """最小 RunOutput 替身：一条带 tool_args.path 的 tool 消息。"""

    metrics = None
    status = type("Status", (), {"value": "COMPLETED"})()

    def __init__(self, path: str):
        from agno.models.message import Message

        self.messages = [
            Message(role="assistant", content="calling dossier_read"),
            Message(role="tool", content='{"ok": true}', tool_name="dossier_read", tool_args={"path": path}),
        ]
        self.content = '{"ok": true}'

    def to_dict(self):
        return {"content": self.content}


def test_tool_args_with_absolute_path_still_lands_in_the_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    client = type("C", (), {"_project_id": "demo", "_caller": "judge", "model": "m"})()

    request = [{"role": "system", "content": "system"}, {"role": "user", "content": "user"}]
    _track_context(client, request, _Result("/Users/xiaozijian/WorkSpace/x.json"),
                   "trace-path", {}, 10, None)

    records = context_store.load_contexts_by_trace("demo", "trace-path")
    assert len(records) == 1
    assert records[0].messages == request
    tool_messages = [m for m in records[0].response["run_messages"] if m.get("role") == "tool"]
    assert tool_messages and tool_messages[0]["tool_args"]["path"] == "<绝对路径已隐去>"


def test_save_context_rejects_absolute_paths_so_redaction_is_required(tmp_path, monkeypatch):
    """反向证据：不隐去就写不进去。这条锁住「必须隐去」这个前提，避免以后误删 _portable。"""
    _isolate(tmp_path, monkeypatch)
    record = ContextRecord(
        record_id="abs-path",
        trace_id="trace-abs",
        project_id="demo",
        caller="judge",
        messages=[{"role": "tool", "tool_args": {"path": "/Users/a/b.json"}}],
        created_at="2026-07-19T12:00:00Z",
    )

    try:
        save_context(record)
    except Exception as exc:  # PathContractError
        assert "PATH_SCHEMA_BYPASS" in str(exc)
    else:
        raise AssertionError("路径契约应当拒绝含机器绝对路径的记录")


def test_load_context_matches_caller_exactly_and_returns_latest(tmp_path, monkeypatch):
    """同一 trace 下同 caller 会落多条（重试、ToolLoop 按段）；caller 名互为前缀也不能串。"""
    _isolate(tmp_path, monkeypatch)

    def record(rid: str, caller: str, stage: str, created_at: str) -> ContextRecord:
        return ContextRecord(
            record_id=rid, trace_id="trace-seg", project_id="demo", caller=caller,
            messages=[{"role": "user", "content": rid}],
            response={"runtime": {"stage": stage}}, created_at=created_at,
        )

    save_context(record("r0", "judge", "main:s0", "2026-07-19T12:00:00Z"))
    save_context(record("r1", "judge", "main:s1", "2026-07-19T12:00:02Z"))
    save_context(record("r2", "judge_reviewer", "review", "2026-07-19T12:00:05Z"))

    assert context_store.load_context("demo", "trace-seg", "judge").record_id == "r1"
    assert context_store.load_context("demo", "trace-seg", "judge_reviewer").record_id == "r2"
    assert context_store.load_context("demo", "trace-seg", "jud") is None
    stages = {s.record_id: s.stage for s in context_store.list_recent_contexts("demo")}
    assert stages == {"r0": "main:s0", "r1": "main:s1", "r2": "review"}
