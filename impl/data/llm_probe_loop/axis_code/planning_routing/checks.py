"""planning_routing 实际清单的程序检查（同现方案 process_expected.check_actual）。"""
from impl.projects.llm_probe_loop.process_axes import check_actual

AXIS = "planning_routing"


def check(view):
    return check_actual(view.own, view.materials[f"result.{AXIS}_expected"], view.resources)
