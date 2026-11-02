"""侦探交的发现：环节编号在表里、新环节有端点、出处都是读过的（spec/alg/axis_loop.md §12.2.2）。"""
from impl.projects.llm_probe_loop.process_axes import TRACE, check_analysis


def check(view):
    read = {str(i) for c in view.calls if c.tool == "read_material" and not c.is_error for i in (c.args.get("ids") or [])}
    return check_analysis(view.materials[TRACE], view.own, read)
