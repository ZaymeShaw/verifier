"""intent_understanding 实际清单的程序检查（同现方案 process_expected.check_actual）。"""
from impl.projects.llm_probe_loop.process_axes import ANALYSIS, check_actual, record_texts

AXIS = "intent_understanding"


def check(view):
    full = next(v for v in view.materials[ANALYSIS]["views"] if v["axis"] == AXIS)["full"]
    return check_actual(view.own, view.materials[f"result.{AXIS}_expected"], record_texts(full))
