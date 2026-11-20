"""intent_understanding 实际清单的程序检查（spec/alg/process-axes.md §4）。"""
from impl.projects.llm_probe_loop.process_axes import check_actual

AXIS = "intent_understanding"


def check(view):
    return check_actual(AXIS, view.own, view.materials[f"result.{AXIS}_expected"],
                        view.materials["result.expectations"], view.resources)
