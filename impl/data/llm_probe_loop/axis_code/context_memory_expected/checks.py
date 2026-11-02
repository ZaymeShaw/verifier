"""context_memory 本应清单的程序检查（同现方案 process_expected._expected_list 的检查）。"""
from impl.projects.llm_probe_loop.process_axes import ANALYSIS, check_expected

AXIS = "context_memory"


def check(view):
    links = next(v for v in view.materials[ANALYSIS]["views"] if v["axis"] == AXIS)["links"]
    ids = {e["expectation_id"] for e in view.materials["result.expectations"]["expectations"]}
    return check_expected(view.own, links, ids)
