"""A4 调用小票去重：重试造成的完全重复记录只保留最后一条 + retry_count。"""
from impl.core import context_store
from impl.core.schema.context import ContextRecord


def _isolate(tmp_path, monkeypatch) -> None:
    store_root = tmp_path / "impl" / "data" / "context_store"
    context = context_store.DEFAULT_ACTIVE_ARTIFACT_REGISTRY.context(
        context_store.REPOSITORY_ROOT,
        environ={"CONTEXT_STORE_ROOT": str(store_root)},
    )
    monkeypatch.setattr(context_store, "_ACTIVE_ARTIFACT_CONTEXT", context)


def _record(record_id: str, message: str, *, error=None) -> ContextRecord:
    return ContextRecord(
        record_id=record_id,
        trace_id="trace-1",
        project_id="demo",
        caller="judge",
        messages=[{"role": "user", "content": message}],
        created_at="2026-07-19T12:00:00Z",
        error=error,
    )


def test_identical_prompt_and_outcome_is_merged_into_one_record(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    context_store.save_context(_record("attempt-one", "同一个 prompt", error="Prompt too large (204473 chars)"))
    context_store.save_context(_record("attempt-two", "同一个 prompt", error="Prompt too large (204473 chars)"))

    records = context_store.load_contexts_by_trace("demo", "trace-1")
    assert len(records) == 1
    assert records[0].record_id == "attempt-two"
    assert records[0].retry_count == 1


def test_records_with_different_prompt_or_outcome_are_kept(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    context_store.save_context(_record("first-failure", "prompt A", error="结构化输出约束"))
    context_store.save_context(_record("retry-success", "prompt A"))
    context_store.save_context(_record("other-call", "prompt B"))

    records = context_store.load_contexts_by_trace("demo", "trace-1")
    assert {record.record_id for record in records} == {"first-failure", "retry-success", "other-call"}
    assert all(record.retry_count == 0 for record in records)
