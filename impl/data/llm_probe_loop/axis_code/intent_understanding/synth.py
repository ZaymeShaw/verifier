"""intent_understanding 轴级五值、组成、问题记录（同现方案 process_expected 的 aggregate + issues_of）。"""
from impl.projects.llm_probe_loop.process_axes import actual_result

AXIS = "intent_understanding"


def synthesize(view):
    return actual_result(AXIS, view.own, view.materials[f"result.{AXIS}_expected"])
