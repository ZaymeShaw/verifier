"""过程轴：context_memory 义务配对与缺证口径、选材统计不进明细。"""
from __future__ import annotations


from impl.projects.llm_probe.eval_axes.adapters import context_memory as cm
from impl.projects.llm_probe.eval_axes.adapters import intent_understanding as intent


def test_context_memory_redacted_input_is_left_to_the_judge_not_preset():
    from impl.projects.llm_probe.business_trace.links import build_links
    from impl.projects.llm_probe.eval_axes.adapters import process_common as common
    dossier = {"records": [], "model_calls": [{"id": "call1", "scope": "current", "input": {"status": "redacted"}}]}
    decided, pending = common.pair_up(cm.OBLIGATIONS, build_links(dossier, axis_id="context_memory")["links"])
    assert decided == {}
    assert pending == [("input_assembled", "context_memory:input:call1"), ("history_and_state", "context_memory:input:call1")]


def test_process_obligations_have_chinese_labels():
    assert all(ob.label for ob in intent.OBLIGATIONS)
    assert intent.OBLIGATIONS[0].label == "对象与字段一致"


def test_trace_analysis_summary_has_no_selection_count_items():
    from impl.projects.llm_probe.eval_axes.adapters import trace_analysis as ta
    import inspect
    src = inspect.getsource(ta.run)
    assert "选入材料数" not in src
    assert "可疑环节" in src
