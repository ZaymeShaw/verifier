"""过程轴：context_memory 义务配对与缺证口径、选材统计不进明细。"""
from __future__ import annotations


from impl.projects.llm_probe.eval_axes.adapters import context_memory as cm
from impl.projects.llm_probe.eval_axes.adapters import intent_understanding as intent


def test_subcapabilities_have_chinese_names():
    assert all(c.name and c.when and c.duty for c in intent.SUBCAPABILITIES)
    assert intent.SUBCAPABILITIES[0].name == "对象与字段一致"


def test_trace_analysis_summary_has_no_selection_count_items():
    from impl.projects.llm_probe.eval_axes.adapters import trace_analysis as ta
    import inspect
    src = inspect.getsource(ta.run)
    assert "选入材料数" not in src
    assert "可疑环节" in src
