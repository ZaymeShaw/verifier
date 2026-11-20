"""侦探的程序填字段：合并可疑环节、全部环节（含表外）、每轴 input / full 两份材料与指的记录。"""
from impl.projects.llm_probe_loop.process_axes import TRACE, analysis_result


def synthesize(view):
    return analysis_result(view.materials[TRACE], view.own)
