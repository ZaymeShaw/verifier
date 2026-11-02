import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERVIEW_JS = ROOT / "impl" / "frontend" / "axes_overview.js"
SUMMARY_HTML = ROOT / "impl" / "frontend" / "summary.html"


def _run(script: str, payload) -> dict:
    prelude = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{ globalThis: {{}} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(OVERVIEW_JS))}, 'utf8'), context);
const A = context.globalThis.AxesOverview;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
"""
    result = subprocess.run(["node", "-e", prelude + script], input=json.dumps(payload),
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _item(label, link, value, reason=""):
    return {"key": f"{label} @ {link}", "value": value, "reason": reason}


CASES = [
    {"id": "A", "fulfillment": "not_fulfilled", "axes": [
        {"type_id": "tool_execution", "title": "工具执行", "status": "succeeded", "verdict": "problematic", "items": [
            # 同一次超时违反两条义务：同一环节同一取值只计 1 次，另 1 条记为同环节重复
            _item("调用无执行错误", "χ:t1", "fail", "TIMEOUT"),
            _item("返回可用", "χ:t1", "fail", "TIMEOUT"),
            _item("调用无执行错误", "χ:t2", "pass"),
            _item("耗时合规", "χ:t2", "contract_missing"),
            _item("调用无执行错误", "new:6", "fail", "bridge"),
        ]},
        # 非过程轴：条目自成单元，key 是本例的断言 / 期望编号
        {"type_id": "truthfulness", "title": "真实性", "status": "succeeded", "verdict": None, "items": [
            {"key": "等待期 90 天", "value": "refuted", "reason": "条款写 180 天"},
            {"key": "保额 50 万", "value": "verified", "reason": ""},
            {"key": "可续保", "value": "unverifiable", "reason": ""},
        ]},
        {"type_id": "fulfillment", "title": "能力兑现", "status": "succeeded", "verdict": "not_fulfilled", "items": [
            {"key": "E1", "value": "not_fulfilled", "reason": "没给保单"},
            {"key": "E2", "value": "fulfilled", "reason": ""},
        ]},
        {"type_id": "trace_analysis", "title": "过程案卷", "status": "succeeded", "verdict": "complete", "items": []},
    ]},
    {"id": "B", "fulfillment": "fulfilled", "axes": [
        {"type_id": "tool_execution", "title": "工具执行", "status": "succeeded", "verdict": "problematic",
         "items": [_item("调用无执行错误", "χ:t9", "fail", "ERROR")]},
        {"type_id": "truthfulness", "title": "真实性", "status": "succeeded", "verdict": None,
         "items": [{"key": "免赔额 1 万", "value": "refuted", "reason": "条款写 5000"}]},
        {"type_id": "fulfillment", "title": "能力兑现", "status": "succeeded", "verdict": "fulfilled",
         "items": [{"key": "E1", "value": "fulfilled", "reason": ""}]},
        {"type_id": "carryability", "title": "承载性", "status": "succeeded", "verdict": None,
         "items": [{"key": "E3", "value": "说不清", "reason": ""}, {"key": "E4", "value": "说不清", "reason": ""}]},
        {"type_id": "trace_analysis", "title": "过程案卷", "status": "blocked", "items": []},
        {"type_id": "context_memory", "status": "disabled", "items": []},
    ]},
]


TYPES = [
    {"type_id": "tool_execution", "title": "工具执行", "verdict_scope": "axis",
     "verdict_enum": [{"value": v} for v in ("sound", "problematic", "not_evaluable", "not_applicable")]},
    {"type_id": "truthfulness", "title": "真实性", "verdict_scope": "item",
     "verdict_enum": [{"value": v} for v in ("verified", "refuted", "unverifiable")]},
    {"type_id": "fulfillment", "title": "能力兑现", "verdict_scope": "axis",
     "verdict_enum": [{"value": v} for v in ("fulfilled", "not_fulfilled", "not_evaluable")]},
    {"type_id": "carryability", "title": "承载性", "verdict_scope": "item",
     "verdict_enum": [{"value": v} for v in ("做不了", "做错了", "说不清")]},
    {"type_id": "trace_analysis", "title": "过程案卷", "verdict_scope": "axis",
     "verdict_enum": [{"value": v} for v in ("complete", "partial")]},
]


def _aggregate(types=TYPES):
    return _run("""
const s = A.aggregate(input.cases, input.types);
process.stdout.write(JSON.stringify({axes: Object.fromEntries(s.axes.map(a => [a.id, a])), order: s.axes.map(a => a.id),
  groups: s.groups, matrix: s.matrix}));
""", {"cases": CASES, "types": types})


def test_axes_are_discovered_from_data():
    out = _aggregate()
    # 顺序按首次出现；disabled 不算轴；标题和级别取类型声明
    assert out["order"] == ["tool_execution", "truthfulness", "fulfillment", "trace_analysis", "carryability"]
    assert out["axes"]["truthfulness"]["scope"] == "item"


def test_verdicts_keep_axis_enum_without_polarity():
    axes = _aggregate()["axes"]
    t, ta = axes["tool_execution"], axes["trace_analysis"]
    # 声明的枚举全部保留（没出现的计 0），不折算成好坏
    assert t["verdictOrder"] == ["sound", "problematic", "not_evaluable", "not_applicable"]
    assert t["verdicts"] == {"problematic": 2}
    # 没跑成的单列一档，不并进任何枚举值
    assert ta["verdicts"] == {"complete": 1, "未跑成": 1} and ta["verdictOrder"] == ["complete", "partial", "未跑成"]
    assert "valueClass" not in _run("process.stdout.write(JSON.stringify(Object.keys(A)));", None)


def test_process_units_are_link_instances():
    t = _aggregate()["axes"]["tool_execution"]
    # A: t1(fail×2) t2(pass, contract_missing) new:6(fail)；B: t9(fail) → 4 个环节
    assert t["units"] == 4 and t["linked"] is True
    assert t["unitValues"] == {"fail": 3, "pass": 1, "contract_missing": 1}
    assert t["itemValues"] == {"fail": 4, "pass": 1, "contract_missing": 1}
    assert t["repeatedInUnit"] == {"fail": 1} and t["offMap"] == {"fail": 1}
    assert t["valueOrder"] == ["fail", "pass", "contract_missing"]


def test_item_axes_count_cases_per_value():
    axes = _aggregate()["axes"]
    tr, ca = axes["truthfulness"], axes["carryability"]
    assert tr["valueOrder"] == ["verified", "refuted", "unverifiable"]
    assert tr["unitValues"] == {"refuted": 2, "verified": 1, "unverifiable": 1}
    # 出现过该取值的用例数：refuted 两例都有，其余只在 A
    assert tr["caseValues"] == {"refuted": 2, "verified": 1, "unverifiable": 1}
    assert ca["caseValues"] == {"说不清": 1} and ca["unitValues"] == {"说不清": 2}


def test_without_types_falls_back_to_observed_values():
    t = _aggregate(types=[])["axes"]["tool_execution"]
    assert t["title"] == "工具执行" and t["verdictOrder"] == ["problematic"]


def test_groups_only_use_cross_case_fields():
    groups = _aggregate()["groups"]
    top = groups[0]
    assert (top["axisId"], top["value"], top["label"], top["family"], top["caseCount"]) == ("tool_execution", "fail", "调用无执行错误", "χ", 2)
    # 真实性两例的不同断言按（轴 × 取值）同组，断言原文进明细
    refuted = next(g for g in groups if g["axisId"] == "truthfulness" and g["value"] == "refuted")
    assert refuted["label"] == "" and refuted["caseCount"] == 2
    assert {i["subject"] for i in refuted["items"]} == {"等待期 90 天", "免赔额 1 万"}
    # 能力兑现的 E1 两例取值不同，不会因为编号相同被并到一起
    fulfil = [g for g in groups if g["axisId"] == "fulfillment"]
    assert {(g["value"], tuple(g["cases"])) for g in fulfil} == {("not_fulfilled", ("A",)), ("fulfilled", ("A", "B"))}
    assert any(g["family"] == "地图外" for g in groups)


def test_link_family_and_key_parsing():
    out = _run("""process.stdout.write(JSON.stringify({
  f: ['κ:input:abc', 'χ:turn1/x', 'σ:turn1', 'new:3', 'ρ:repeat:t2', ''].map(A.linkFamily),
  k: A.parseItemKey('义务 @ 名 @ κ:step:a→b')}));""", None)
    assert out["f"] == ["κ:input", "χ", "σ", "地图外", "ρ:repeat", ""]
    assert out["k"] == {"label": "义务 @ 名", "linkId": "κ:step:a→b"}


def test_page_renders_star_or_bars_and_escapes():
    cases = [{"id": "<x>", "axes": [{"type_id": "tool_execution", "status": "succeeded", "verdict": "problematic",
                                     "items": [_item("输出契约", "μ:c1", "fail", "<script>alert(1)</script>")]},
                                    {"type_id": "trace_analysis", "status": "succeeded", "verdict": "partial", "items": []}]}]
    out = _run("process.stdout.write(JSON.stringify(A.renderPage(A.aggregate(input.cases, input.types), {project: 'p'})));",
               {"cases": cases, "types": TYPES})
    # 工具执行 4 个枚举 → 星图；过程案卷 2 个枚举 → 横条
    assert out.count('aria-label="星图（固定 0–100%）"') == 1 and 'class="bars"' in out
    assert "<script>alert(1)</script>" not in out and "&lt;script&gt;" in out and "&lt;x&gt;" in out


@pytest.mark.parametrize("counts", [[50, 25, 10, 0], [0, 0, 0, 0], [100, 60, 40, 0]])
def test_star_uses_fixed_percentage_radius(counts):
    spokes = [{"value": f"enum_{i}", "count": n} for i, n in enumerate(counts)]
    svg = ET.fromstring(_run(
        "process.stdout.write(JSON.stringify(A.renderStar(input, 100, '#2563eb')));", spokes))
    points = svg.find("polygon[@class='star-values']").get("points").split()
    for point, line, count in zip(points, svg.findall("line"), counts, strict=True):
        x, y = map(float, point.split(","))
        cx, cy = float(line.get("x1")), float(line.get("y1"))
        end_x, end_y = float(line.get("x2")), float(line.get("y2"))
        # 按分母 100 定位，50 必须在半径一半；全零留在中心，多取值合计过百也不重新归一化。
        assert x == pytest.approx(cx + (end_x - cx) * count / 100, abs=0.1)
        assert y == pytest.approx(cy + (end_y - cy) * count / 100, abs=0.1)
    assert [t.text for t in svg.findall("text") if t.get("class") != "star-label"] == ["25%", "50%", "75%", "100%"]


def test_star_shows_original_labels_not_numbered_legend():
    labels = ["sound", "insufficient_evidence", "contract_missing", "未跑成", "<script>&"]
    spokes = [{"value": label, "count": 5, "title": "<原始描述>"} for label in labels]
    out = _run("process.stdout.write(JSON.stringify(A.renderStar(input, 10, '#2563eb')));", spokes)
    svg = ET.fromstring(out)
    marks = svg.findall("text[@class='star-label']")
    assert [mark.find("tspan").text for mark in marks] == labels
    assert all(mark.findall("tspan")[1].text == "5 · 50%" for mark in marks)
    assert all(mark.find("title").text == "<原始描述>" for mark in marks)
    assert "<ol" not in out and "<script>" not in out


def test_summary_page_loads_overview_with_types():
    source = SUMMARY_HTML.read_text(encoding="utf-8")
    assert "axes_overview.js" in source and "openAxesOverview()" in source
    assert "aggregate(cases,axesTypesCache)" in source and "/api/eval_axes/types" in source


def test_internal_analysis_does_not_become_evaluation_dimension():
    script = """
    const fs = require('fs');
    eval(fs.readFileSync('impl/frontend/axes_overview.js','utf8'));
    const result = globalThis.AxesOverview.aggregate([{id:'one',axes:[
      {type_id:'expectations',status:'succeeded',verdict:'complete'},
      {type_id:'trace_analysis',role:'analysis',status:'succeeded',verdict:'complete'},
      {type_id:'model_capability',status:'succeeded',verdict:'sound'}]}],
      [{type_id:'expectations',role:'analysis'}]);
    console.log(JSON.stringify(result.axes.map(a => a.id)));
    """
    output = subprocess.check_output(['node', '-e', script], cwd=ROOT, text=True)
    assert json.loads(output) == ['model_capability']
