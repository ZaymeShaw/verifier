"""需求按轮写：每轮一份，只选本轮的原话与历史；场景对需求轴的描述由框架按本轴描述槽位放进每一份。
本轮用户原话没记录的轮次不分发（没有可写的需求）。"""
from impl.projects.llm_probe_loop.eval_axes.requirements import turn_materials


def dispatch(view):
    parts = []
    for turn, part in turn_materials(view.materials["case.requirements"]):
        if not any(s["component"] == "user" for s in part["sources"]):
            continue
        ids = ",".join(s["id"] for s in part["sources"])
        parts.append({"id": turn, "materials": [f"case.requirements.sources[id={ids}]"]})
    return parts
