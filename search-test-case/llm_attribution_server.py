#!/usr/bin/env python3
"""Static report server with an LLM-backed failure attribution endpoint."""
import argparse
import concurrent.futures
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent

MODEL_DEFAULT = "deepseek-v4-pro"
BASE_URL_DEFAULT = "https://api.deepseek.com/v1/chat/completion"
CASE_POOL_PATH = ROOT / "attribution_case_pool.json"
CASE_POOL_LIBRARY_PATH = ROOT / "attribution_case_pool_library.json"
CUSTOM_CASE_POOL_PATH = ROOT / "attribution_custom_case_pool.json"
ATTRIBUTION_SUMMARIES_DIR = ROOT / "attribution_summaries"
ATTRIBUTION_SUMMARY_INDEX_PATH = ATTRIBUTION_SUMMARIES_DIR / "index.json"
ATTRIBUTION_SUMMARY_LATEST_PATH = ATTRIBUTION_SUMMARIES_DIR / "latest.json"
ATTRIBUTION_STORE_DIR = ROOT / "attribution_store"
CASES_MASTER_PATH = ATTRIBUTION_STORE_DIR / "cases_master.json"
CASE_ATTRIBUTIONS_PATH = ATTRIBUTION_STORE_DIR / "case_attributions.json"
CASE_JUDGEMENTS_PATH = ATTRIBUTION_STORE_DIR / "case_judgements.json"
CASE_BATCHES_PATH = ATTRIBUTION_STORE_DIR / "case_batches.json"
NAMED_POOLS_STORE_PATH = ATTRIBUTION_STORE_DIR / "named_pools.json"
SUMMARY_STORE_INDEX_PATH = ATTRIBUTION_STORE_DIR / "summaries_index.json"
SUMMARY_STORE_DIR = ATTRIBUTION_STORE_DIR / "summaries"
ATTRIBUTION_JOBS_DIR = ROOT / "attribution_jobs"
ATTRIBUTION_TASK_STATE_PATH = ROOT / "attribution_task_state.json"
ATTRIBUTION_TASK_STATE_MAX_JOBS = 50
CUSTOM_POOL_LOCK = threading.Lock()
ATTRIBUTION_STORE_LOCK = threading.Lock()
ACTIVE_ATTRIBUTE_JOBS = set()
ACTIVE_ATTRIBUTE_JOBS_LOCK = threading.Lock()
CHAIN_PROBE_PATH = ROOT / "chain_probe_results.json"

CONTEXT_FILES = [
    "src/main/python/steps/query_router.py",
    "src/main/python/steps/level2_enhanced_matcher.py",
    "src/main/python/steps/level4_llm_parser.py",
    "src/main/python/config/enhanced_rules_args.yaml",
    "src/main/python/config/field_definitions_args.yaml",
    ".claude/skills/evals/material/prompt.md",
]

FIELD_HINTS = {
    "年龄": ["clientAge", "clientBirthday", "birthdayMd"],
    "岁": ["clientAge", "clientBirthday"],
    "保费": ["annPremSegNum"],
    "年缴": ["annPremSegNum"],
    "年交": ["annPremSegNum"],
    "保额": ["insnoSumInsSeqNum"],
    "VIP": ["vipType"],
    "vip": ["vipType"],
    "寿险": ["pCategorys", "isBuyPension", "polNoInfo.plancodeinfo"],
    "养老": ["isBuyPension", "pCategorys", "polNoInfo.plancodeinfo"],
    "子女": ["familyInfo.familyrelation", "familyInfo.familyclientbirthday"],
    "小孩": ["familyInfo.familyrelation", "familyInfo.familyclientbirthday"],
    "生日": ["birthdayMd", "clientBirthday"],
    "投保": ["appntDate", "effDate"],
    "承保": ["effDate"],
    "退保": ["surrenderDate"],
    "生存金": ["polNoInfo.payamountdue"],
    "年收入": ["annual_income"],
}


def load_env_md_value(key, default=""):
    env_path = ROOT / "run/env.md"
    if not env_path.exists():
        return default
    patterns = {
        "DEEPSEEK_API_KEY": ["deepseek key:"],
        "DEEPSEEK_BASE_URL": ["deepseek base-url:", "deepseek base_url:"],
    }
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        for prefix in patterns.get(key, []):
            if lowered.startswith(prefix):
                return stripped.split(":", 1)[1].strip().strip('"\'') or default
    return default


def load_yaml_value(key, default):
    env_aliases = {
        "LLM_API_KEY": ["LLM_ATTRIBUTION_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY"],
        "LLM_BASE_URL": ["LLM_ATTRIBUTION_BASE_URL", "DEEPSEEK_BASE_URL", "LLM_BASE_URL"],
    }
    for env_key in env_aliases.get(key, [key]):
        if os.environ.get(env_key):
            return os.environ[env_key]
    if key == "LLM_API_KEY":
        value = load_env_md_value("DEEPSEEK_API_KEY", "")
        if value:
            return value
    if key == "LLM_BASE_URL":
        value = load_env_md_value("DEEPSEEK_BASE_URL", "")
        if value:
            return value
    cfg_path = PROJECT_ROOT / "src/main/python/config/dev_client_search_args.yaml"
    if not cfg_path.exists():
        return default
    for line in cfg_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(key + ":"):
            value = line.split(":", 1)[1].strip().strip('"\'')
            return value or default
    return default


def read_lines(path, start=None, end=None):
    full = PROJECT_ROOT / path
    if not full.exists():
        return ""
    lines = full.read_text(encoding="utf-8", errors="ignore").splitlines()
    if start is None:
        selected = lines[:120]
        base = 1
    else:
        selected = lines[max(0, start - 1):end]
        base = start
    return "\n".join(f"{idx}\t{line}" for idx, line in enumerate(selected, base))


def grep_context(path, terms, max_hits=28, radius=4):
    full = PROJECT_ROOT / path
    if not full.exists():
        return ""
    lines = full.read_text(encoding="utf-8", errors="ignore").splitlines()
    hit_lines = []
    lowered_terms = [t.lower() for t in terms if t]
    for idx, line in enumerate(lines, 1):
        low = line.lower()
        if any(t.lower() in low for t in lowered_terms):
            hit_lines.append(idx)
        if len(hit_lines) >= max_hits:
            break
    ranges = []
    for idx in hit_lines:
        ranges.append((max(1, idx - radius), min(len(lines), idx + radius)))
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    chunks = []
    for start, end in merged[:8]:
        chunks.append(read_lines(path, start, end))
    return "\n...\n".join(chunks)


def infer_terms(query, actual):
    terms = set()
    for key, values in FIELD_HINTS.items():
        if key in query:
            terms.update(values)
            terms.add(key)
    for condition in (actual or {}).get("conditions") or []:
        field = condition.get("field")
        if field:
            terms.add(field)
            for part in str(field).split("."):
                terms.add(part)
    if not terms:
        terms.update(["match", "route_with_peeling", "conditions", "field"])
    return sorted(terms)


def hint_fields_from_query(query):
    fields = []
    for key, values in FIELD_HINTS.items():
        if key in query:
            fields.extend(values)
    return list(dict.fromkeys(fields))


def expected_fields_from_query(query):
    return hint_fields_from_query(query)


def premium_query_expected_conditions(query):
    expected = []
    if "VIP" in query or "vip" in query:
        expected.append("当前 query 包含 VIP 意图；需由 judge 或同 query 链路探针确认字段、操作符和值")
    if any(word in query for word in ["保费", "年缴", "年交"]):
        expected.append("当前 query 包含保费意图；需由 judge 或同 query 链路探针确认金额阈值和单位")
    return expected


def same_topic_chain_probe(query, item):
    expected = set(expected_fields_from_query(query))
    probe_expected = set(item.get("expected_fields") or [])
    if not expected or not probe_expected:
        return False
    return expected == probe_expected or probe_expected.issubset(expected)


def build_context(query, actual):
    terms = infer_terms(query, actual)
    snippets = [
        "## query_router route_with_peeling / L4 fallback / validation\n"
        + read_lines("src/main/python/steps/query_router.py", 477, 640),
        "## query_router finalize and validate conditions\n"
        + read_lines("src/main/python/steps/query_router.py", 260, 332),
        "## query_router validation invalid-field behavior\n"
        + grep_context("src/main/python/steps/query_router.py", ["非法字段", "_validate_conditions", "return []"], max_hits=12, radius=4),
        "## level2 bare value weak-query guard\n"
        + read_lines("src/main/python/steps/level2_enhanced_matcher.py", 702, 724),
        "## level2 composite expansion / pattern compile / matching flow\n"
        + read_lines("src/main/python/steps/level2_enhanced_matcher.py", 726, 980),
        "## query_router final output normalization: single CONTAINS and family age birthday conversion\n"
        + read_lines("src/main/python/steps/query_router.py", 355, 426)
        + "\n"
        + read_lines("src/main/python/steps/query_router.py", 729, 829),
        "## family relation enhanced rules\n"
        + read_lines("src/main/python/config/enhanced_rules_args.yaml", 2731, 2775),
        "## family member field definitions\n"
        + read_lines("src/main/python/config/field_definitions_args.yaml", 1877, 2194),
        "## level4 RAG retrieval and field injection\n"
        + read_lines("src/main/python/steps/level4_llm_parser.py", 107, 188),
        "## level4 parse fallback behavior\n"
        + read_lines("src/main/python/steps/level4_llm_parser.py", 374, 430),
        "## enhanced_rules_args gender and age rules\n"
        + read_lines("src/main/python/config/enhanced_rules_args.yaml", 90, 267),
        "## enhanced_rules_args annual premium rules\n"
        + read_lines("src/main/python/config/enhanced_rules_args.yaml", 1231, 1284),
        "## field_definitions_args gender and age definitions\n"
        + read_lines("src/main/python/config/field_definitions_args.yaml", 101, 185),
        "## field_definitions_args annual premium definitions\n"
        + read_lines("src/main/python/config/field_definitions_args.yaml", 992, 1086),
    ]
    chain_context = build_chain_probe_context(query, actual)
    if chain_context:
        snippets.insert(0, chain_context)
    for path in CONTEXT_FILES[3:]:
        ctx = grep_context(path, terms)
        if ctx:
            snippets.append(f"## {path} matched snippets\n{ctx}")
    text = "\n\n".join(snippets)
    return text[:56000]


def normalize_query_text(text):
    return re.sub(r"\s+", "", str(text or ""))


def normalized_condition_values(condition):
    value = condition.get("value") if isinstance(condition, dict) else None
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)] if value not in (None, "") else []


def condition_operator_semantically_equivalent(expected, actual):
    expected_operator = str(expected.get("operator") or "").upper()
    actual_operator = str(actual.get("operator") or "").upper()
    if expected_operator == actual_operator:
        return True
    if {expected_operator, actual_operator} <= {"MATCH", "CONTAINS"}:
        expected_values = normalized_condition_values(expected)
        actual_values = normalized_condition_values(actual)
        return len(expected_values) == 1 and len(actual_values) == 1 and expected_values == actual_values
    return False


def condition_semantically_equivalent(expected, actual):
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return False
    if expected.get("field") != actual.get("field"):
        return False
    if not condition_operator_semantically_equivalent(expected, actual):
        return False
    return normalized_condition_values(expected) == normalized_condition_values(actual)


def condition_sets_semantically_equivalent(expected_conditions, actual_conditions):
    expected_conditions = [item for item in expected_conditions or [] if isinstance(item, dict)]
    actual_conditions = [item for item in actual_conditions or [] if isinstance(item, dict)]
    if len(expected_conditions) != len(actual_conditions):
        return False
    unmatched = list(actual_conditions)
    for expected in expected_conditions:
        for index, actual in enumerate(unmatched):
            if condition_semantically_equivalent(expected, actual):
                unmatched.pop(index)
                break
        else:
            return False
    return True


def judge_conditions_equivalent(judgement, actual):
    expected = judgement.get("expected") or {}
    expected_conditions = expected.get("conditions") or []
    actual_conditions = (judgement.get("actual") or actual or {}).get("conditions") or []
    if expected.get("query_logic") and (judgement.get("actual") or actual or {}).get("query_logic"):
        if expected.get("query_logic") != (judgement.get("actual") or actual or {}).get("query_logic"):
            return False
    return condition_sets_semantically_equivalent(expected_conditions, actual_conditions)


def reconcile_judge_verdict(judgement, actual):
    if judgement.get("verdict") != "incorrect":
        return judgement
    if any(judgement.get(key) for key in ["missing_conditions", "wrong_conditions", "extra_conditions"]):
        return judgement
    if not judge_conditions_equivalent(judgement, actual):
        return judgement
    judgement["verdict"] = "correct"
    judgement["review_verdict"] = "通过"
    judgement["failure_category"] = "无失败"
    judgement["failure_stage"] = "通过"
    judgement["next_agent"] = "none"
    judgement["verdict_reconciled"] = "expected_actual_semantically_equivalent"
    return judgement


def condition_fields(conditions):
    return [condition.get("field") for condition in conditions or [] if isinstance(condition, dict) and condition.get("field")]


def get_step_conditions(step):
    if not isinstance(step, dict):
        return []
    return step.get("conditions") or (step.get("parsed") or {}).get("conditions") or []


def find_trace_step(trace, name):
    for step in trace or []:
        if step.get("name") == name:
            return step
    return {}


def infer_breakpoint_proof(item, actual=None):
    stages = item.get("stages") or {}
    key = stages.get("key_functions") or {}
    trace = key.get("trace") or []
    l2_candidates = ((stages.get("l1l2") or {}).get("raw") or {}).get("l2_candidate_conditions") or []
    l4_step = find_trace_step(trace, "level4.parse")
    merge_step = find_trace_step(trace, "router._merge_l2_candidate_conditions")
    finalize_step = find_trace_step(trace, "router._finalize_l4_result")
    l4_conditions = get_step_conditions(l4_step)
    merged_conditions = get_step_conditions(merge_step)
    final_conditions = get_step_conditions(finalize_step) or (actual or {}).get("conditions") or []
    candidate_fields = set(condition_fields(l2_candidates))
    l4_fields = set(condition_fields(l4_conditions))
    expected_fields = set(item.get("expected_fields") or [])
    l4_unexpected_fields = sorted(field for field in l4_fields if field not in expected_fields and field not in candidate_fields)
    candidate_missing_after_merge = sorted(field for field in candidate_fields if field in expected_fields and field not in condition_fields(merged_conditions))
    likely_issue = []
    if l4_unexpected_fields:
        likely_issue.append(f"L4 输出了非期望/非候选字段 {','.join(l4_unexpected_fields)}")
    if candidate_missing_after_merge:
        likely_issue.append(f"merge 未用 L2 候选补齐 {','.join(candidate_missing_after_merge)}")
    if merged_conditions and not final_conditions:
        likely_issue.append("_finalize_l4_result 将非空条件清空")
    return {
        "before_breakpoint": {
            "function": "level2.recall_candidate_conditions",
            "conditions": summarize_conditions(l2_candidates),
            "judgement": "候选层已识别到可用于修复/合并的核心字段" if l2_candidates else "候选层未召回核心字段",
        },
        "l4_parse": {
            "function": "level4.parse",
            "ok": l4_step.get("ok"),
            "conditions": summarize_conditions(l4_conditions),
            "judgement": "L4 产出条件但字段需与候选/字段定义对齐" if l4_conditions else "L4 未产出条件",
        },
        "merge_result": {
            "function": "router._merge_l2_candidate_conditions",
            "ok": merge_step.get("ok"),
            "conditions": summarize_conditions(merged_conditions),
            "judgement": "merge 后仍保留 L4 字段，未替换为缺失的正确候选字段" if candidate_missing_after_merge else "merge 后未发现候选字段缺失",
        },
        "breakpoint": {
            "function": "router._finalize_l4_result -> _finalize_conditions -> _validate_conditions",
            "output": f"matched_level={(actual or {}).get('matched_level', (stages.get('full_api') or {}).get('matched_level'))}, conditions={len(final_conditions)} 条",
            "judgement": "上一步有条件但 finalize 后为空，是当前关键断点" if merged_conditions and not final_conditions else "finalize 不是当前唯一断点",
        },
        "field_diff": {
            "expected_fields": sorted(expected_fields),
            "l2_candidate_fields": sorted(candidate_fields),
            "l4_fields": sorted(l4_fields),
            "l4_unexpected_fields": l4_unexpected_fields,
            "candidate_missing_after_merge": candidate_missing_after_merge,
        },
        "likely_actual_issue": "；".join(likely_issue) or item.get("diagnosis") or "未识别到确定性断点",
        "code_evidence": [
            "src/main/python/steps/query_router.py:260-265 _finalize_conditions 调用 _validate_conditions",
            "src/main/python/steps/query_router.py:322-327 _build_l4_result 在 final_conditions 为空时返回 empty result",
            "src/main/python/steps/query_router.py:_validate_conditions 对非法字段返回空条件",
        ],
    }


def find_chain_probe_item(query):
    wanted = normalize_query_text(query)
    if not wanted:
        return None
    try:
        data = load_chain_probe_results()
    except Exception:
        return None
    for item in data.get("items") or []:
        if normalize_query_text(item.get("query")) == wanted:
            return item
    candidates = []
    for item in data.get("items") or []:
        item_query = normalize_query_text(item.get("query"))
        if item_query and (item_query in wanted or wanted in item_query):
            candidates.append(item)
    for item in candidates:
        if same_topic_chain_probe(query, item):
            return item
    return None


def summarize_conditions(conditions):
    out = []
    for condition in conditions or []:
        if isinstance(condition, dict):
            out.append(f"{condition.get('field')} {condition.get('operator')} {condition.get('value')}")
    return out


def build_chain_probe_context(query, actual=None):
    item = find_chain_probe_item(query)
    if not item:
        return ""
    stages = item.get("stages") or {}
    key = stages.get("key_functions") or {}
    trace_lines = []
    for step in key.get("trace") or []:
        trace_lines.append({
            "name": step.get("name"),
            "ok": step.get("ok"),
            "evidence": step.get("evidence"),
            "conditions": summarize_conditions(get_step_conditions(step)),
        })
    compact = {
        "probe_id": item.get("id"),
        "query": item.get("query"),
        "expected_fields": item.get("expected_fields"),
        "failed_stage": item.get("failed_stage"),
        "diagnosis": item.get("diagnosis"),
        "missing_expected_fields": item.get("missing_expected_fields"),
        "suggested_action": item.get("suggested_action"),
        "breakpoint_proof": infer_breakpoint_proof(item, actual),
        "l1es_recalled_fields": (stages.get("l1es") or {}).get("recalled_fields"),
        "l1l2_conditions": summarize_conditions((stages.get("l1l2") or {}).get("conditions")),
        "full_api_conditions": summarize_conditions((stages.get("full_api") or {}).get("conditions")),
        "full_api_matched_level": (stages.get("full_api") or {}).get("matched_level"),
        "first_key_failure": key.get("first_key_failure"),
        "last_ok_step": key.get("last_ok_step"),
        "key_function_trace": trace_lines,
    }
    return "## deterministic chain_probe_results.json evidence for same/similar query\n" + json.dumps(compact, ensure_ascii=False, indent=2)


def build_prompt(payload):
    query = payload.get("query") or ""
    actual = payload.get("actual") or {}
    main_judge = payload.get("general_eval_judge_result") or {}
    context = build_context(query, actual)
    return f"""你是客户搜索解析系统的问题定位专家。你的任务不是泛泛分类，而是基于 API 实际输出、matched_level、conditions、代码/配置片段，做接近代码 debug 粒度的问题定位。不要声称你已经修改业务代码。

硬性要求：
- suspected_files 只能引用下方“相关代码/配置片段”里真实出现的路径和行号范围，禁止编造路径。
- 如果根因只是推断，evidence_chain 必须写清“已确认事实”和“待验证假设”。
- 不要把可疑函数当成已确认根因；必须用 actual 输出、chain_probe_results 确定性探针、路由代码、规则/字段定义四者串起来。
- 如果有 deterministic chain_probe_results.json evidence，必须优先使用其中 breakpoint_proof 判断断点；llm_diagnosis_detail 必须复述 breakpoint_proof 的具体函数输出，不能输出与它矛盾的字段名或原因。
- 如果 breakpoint_proof.field_diff.l4_unexpected_fields 非空，必须优先分析这些字段为什么导致后续失败；不能把未出现在 L4 输出里的字段当作 L4 正常输出。
- evidence_chain 每一项必须包含可核验来源，例如 actual.conditions、matched_level、chain_probe 的函数名、配置文件行号或代码函数名。
- 对 matched_level=0 且 conditions=[]，必须说明 L1/L2/L4/finalize 哪一步最可能导致空结果，以及下一步如何验证。
- 对多条件 query，expected_conditions 必须逐项列出所有核心意图；修改建议/patch plan 必须覆盖每个缺失核心条件，或说明为什么某项不是根因。
- 对 matched_level=0 且 conditions=[]，如果用户 query 明显包含年龄/性别/保费等多个条件，不能只给单字段方案。
- 修复建议必须可直接转成 patch：写清要改哪个 YAML 规则段/字段定义/prompt/函数，以及新增什么规则或回归用例。
- 必须输出 llm_diagnosis_detail，按“断点前函数结果正常 → 断点函数结果异常 → 具体异常原因 → 对应代码/配置落点 → 应该怎么改”的结构详细说明。
- llm_diagnosis_detail 必须写出关键函数名和具体结果，例如 fun1 输出 conditions=[...] 正常，func2 输出 conditions=[] 不正常。
- 如果 breakpoint_proof 显示 L4 输出字段和 L2 candidate/expected 不一致，llm_diagnosis_detail 必须点名实际错误字段、候选正确字段、merge 后是否仍错误、finalize 后具体结果。
- 如果 payload 包含 general_eval_judge_result，必须把它作为主口径：wrong_conditions 是已判错的 actual 条件，禁止把 wrong_conditions 写进 expected_conditions、config_or_code_change_suggestion 或 proposed_patch_plan；patch plan 必须解释如何消除 wrong condition、补正确支持逻辑或明确输出不支持提示。

请只输出一个短 JSON 对象，不要 markdown，不要输出长段落。每个数组最多 4 项，每项不超过 80 字。JSON schema:
{{
  "llm_diagnosis_summary": "一句话根因，必须指出具体模块/字段/配置",
  "llm_owner_module": "L1规则|L2增强规则|L4大模型解析|后处理校验|字段定义|枚举配置|评估口径|不确定",
  "llm_confidence": 0.0,
  "llm_diagnosis_detail": "详细说明关键断点：断点前哪个函数输出了什么、为什么正常；断点函数输出了什么、为什么异常；具体怀疑哪一行代码或哪个配置段；应该怎么改。",
  "expected_conditions": ["字段+操作符+值"],
  "actual_problem": ["实际输出问题"],
  "evidence_chain": ["用户意图", "实际输出", "代码/配置证据", "推断和待验证点"],
  "suspected_files": [{{"file":"必须使用下方真实路径", "line_range":"必须来自片段里的行号", "symbol":"函数/规则/字段", "reason":"怀疑原因"}}],
  "config_or_code_change_suggestion": ["明确修改方案；必须具体到改哪个规则/字段定义/检索文本/后处理逻辑；不要写泛泛检查"],
  "business_impact": "业务影响",
  "what_to_verify_next": ["下一步验证"],
  "proposed_patch_plan": ["不直接改代码，但给出可执行修改步骤，如在某配置补什么关键词/规则/阈值"]
}}

可用真实路径只能从这些里面选：
- src/main/python/steps/query_router.py
- src/main/python/steps/level2_enhanced_matcher.py
- src/main/python/steps/level4_llm_parser.py
- src/main/python/config/enhanced_rules_args.yaml
- src/main/python/config/field_definitions_args.yaml
- .claude/skills/evals/material/prompt.md

用户 query:
{query}

API actual extra_output_params:
{json.dumps(actual, ensure_ascii=False, indent=2)}

Live 请求信息:
{json.dumps(payload.get('request') or {}, ensure_ascii=False, indent=2)}

general_eval 主 judge_result（若存在则为唯一主口径）:
{json.dumps(main_judge, ensure_ascii=False, indent=2)}

相关代码/配置片段:
{context}
"""


def extract_json_object(content):
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    start = content.find("{")
    if start < 0:
        raise json.JSONDecodeError("no json object found", content, 0)
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(content)):
        ch = content[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(content[start:i + 1])
    raise json.JSONDecodeError("unterminated json object", content, start)


def completion_url(base_url):
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/chat/completion"):
        return base + "s"
    return base + "/chat/completions"


def validate_llm_model_provider(model, base_url):
    base = (base_url or "").lower()
    model = model or MODEL_DEFAULT
    if "dashscope.aliyuncs.com" in base and model.startswith("claude-"):
        raise RuntimeError(f"DashScope compatible endpoint 不支持 Claude model id: {model}；请使用兼容的模型或切换到兼容的 LLM_BASE_URL。")
    if "api.deepseek.com" in base and not model.startswith("deepseek-"):
        raise RuntimeError(f"DeepSeek endpoint 只用于 judge/attribute 的 deepseek 模型，当前 model={model}。live parser 请走 8000 原项目 API。")
    return model


def has_reference_only_expected(judge):
    expected = (judge or {}).get("expected")
    if not isinstance(expected, dict):
        return False
    return any(str(key).startswith("reference_only_") for key in expected)


def judge_currentness(judge):
    if not judge:
        return "pending"
    method = str(judge.get("judge_method") or "").strip()
    source = str(judge.get("judge_source") or "").strip()
    verdict = judge.get("verdict")
    if verdict == "judge_unavailable":
        return "judge_unavailable"
    if has_reference_only_expected(judge):
        return "reference_only"
    if method == "local-heuristic-fallback":
        return "local_heuristic_fallback"
    if method == "migration-without-final-verdict":
        return "migration_without_final_verdict"
    if "migration" in source and method != "server-side-llm-judge":
        return "reference_only"
    if is_valid_server_judge(judge):
        return "current"
    if verdict in {"correct", "incorrect"}:
        return "needs_rerun"
    return "pending"


def attribution_currentness(item, judge=None):
    judge_state = judge_currentness(judge or (item.get("judge_result") if isinstance(item.get("judge_result"), dict) else item))
    if judge_state != "current":
        return judge_state
    if item.get("stale") or item.get("attribution_status") in {"needs_rerun", "needs_work"}:
        return "stale"
    analysis = item.get("llm_analysis") or {}
    method = analysis.get("analysis_method") or item.get("analysis_method") or ""
    if not method or method == "migration-without-final-verdict":
        return "needs_rerun"
    quality = item_analysis_quality(item)
    if item.get("verdict") == "incorrect" and quality.get("passed") is not True:
        return "needs_work"
    return "current"


def is_valid_server_judge(judge):
    return (judge or {}).get("verdict") in {"correct", "incorrect"} and (judge or {}).get("judge_method") == "server-side-llm-judge"


def item_analysis_quality(item):
    analysis = item.get("llm_analysis") or {}
    return analysis.get("analysis_quality") or item.get("analysis_quality") or {}


def is_canonical_attribution_item(item):
    return attribution_currentness(item) == "current" and item.get("verdict") == "incorrect"


def normalized_judgement_record(record):
    if not isinstance(record, dict):
        return record
    normalized = dict(record)
    state = judge_currentness(normalized)
    normalized["judge_currentness"] = state
    normalized["currentness"] = state
    return normalized


def normalized_attribution_record(record, judgement=None):
    if not isinstance(record, dict):
        return record
    normalized = dict(record)
    item = normalized.get("attribution_item") if isinstance(normalized.get("attribution_item"), dict) else None
    judge = judgement or (item.get("judge_result") if isinstance(item, dict) and isinstance(item.get("judge_result"), dict) else {}) or {}
    status = normalized.get("attribution_status") or "pending"
    if item:
        item = dict(item)
        item["judge_currentness"] = judge_currentness(judge)
        item["currentness"] = attribution_currentness({**item, "attribution_status": status}, judge)
        normalized["attribution_item"] = item
        normalized["currentness"] = item["currentness"]
        normalized["judge_currentness"] = item["judge_currentness"]
    elif status in {"parser_failed", "judge_failed", "analysis_failed", "attribution_failed"}:
        normalized["currentness"] = "needs_rerun"
    else:
        normalized["currentness"] = status if status in {"pending", "needs_rerun", "needs_work", "stale"} else "pending"
    return normalized


def quality_filtered_items(items):
    return [item for item in items if is_canonical_attribution_item(item)]


def noncanonical_attribution_reasons(items):
    reasons = {}
    for item in items or []:
        if item.get("verdict") != "incorrect":
            continue
        reason = None
        state = attribution_currentness(item)
        if state != "current":
            reason = state
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def needs_review_case_rows(items):
    rows = []
    for item in items or []:
        if item.get("verdict") != "incorrect" or is_canonical_attribution_item(item):
            continue
        reason = attribution_currentness(item)
        row = compact_case_evidence(item)
        row["excluded_reason"] = reason
        row["currentness"] = reason
        row["suggested_action"] = item.get("suggested_action") or item.get("fix_hint") or "重跑 judge/attribute 链路，直到归因质量通过后再进入正式聚簇"
        row["failure_category"] = item.get("failure_category") or "未分类"
        row["failure_stage"] = item.get("failure_stage") or "不确定"
        rows.append(row)
    rows.sort(key=lambda row: (row.get("excluded_reason") or "", row.get("id") or ""))
    return rows


def attribution_health():
    api_key = load_yaml_value("LLM_API_KEY", "")
    base_url = load_yaml_value("LLM_BASE_URL", BASE_URL_DEFAULT).rstrip("/")
    model = load_yaml_value("LLM_ATTRIBUTION_MODEL", MODEL_DEFAULT)
    thinking_mode = load_yaml_value("LLM_ATTRIBUTION_THINKING_MODE", "max")
    context_files = []
    for path in CONTEXT_FILES:
        context_files.append({"file": path, "exists": (PROJECT_ROOT / path).exists()})
    return {
        "ok": True,
        "service": "llm_attribution_server",
        "server_root": str(ROOT),
        "endpoint": "/llm_failure_analysis",
        "method": "POST",
        "llm_config": {
            "has_api_key": bool(api_key),
            "base_url": base_url,
            "completion_url": completion_url(base_url),
            "model": model,
            "thinking_mode": thinking_mode if model == "deepseek-v4-pro" else "default",
        },
        "chain_readiness": {
            "parser": "check http://localhost:8000/health",
            "judge": "configured" if api_key else "missing_api_key",
            "attribute": "configured" if api_key else "blocked_until_judge_ready",
            "canonical_requirement": "只有 server-side-llm-judge 的 correct/incorrect 可进入正式 judge/attribute/summary 链路；judge_unavailable 只能作为待判定状态。",
        },
        "context_files": context_files,
        "status_hint": "health ok means this page is served by llm_attribution_server; run a live query then POST /llm_failure_analysis for real LLM attribution.",
    }


def analysis_from_raw_content(content, summary, confidence=0.6):
    return {
        "llm_diagnosis_summary": summary,
        "llm_owner_module": "大模型原始归因",
        "llm_confidence": confidence,
        "llm_diagnosis_detail": content[:4000],
        "expected_conditions": [],
        "actual_problem": [],
        "evidence_chain": [content[:4000]],
        "suspected_files": [],
        "config_or_code_change_suggestion": [],
        "business_impact": "请查看原始大模型分析文本中的业务影响描述。",
        "what_to_verify_next": ["根据原始归因文本复核疑似代码/配置位置。"],
        "proposed_patch_plan": [],
        "raw_llm_content": content,
    }


def meaningful_problem_entries(values):
    no_problem_words = ["无实际问题", "无问题", "输出完全正确", "与预期相符", "符合预期", "问题不复现", "无需修改"]
    weak_operator_words = ["MATCH", "CONTAINS", "operator", "操作符", "字段定义预期"]
    real_miss_words = ["缺失", "缺少", "未覆盖", "未展开", "漏", "范围", "以上", "以下", "及以上", "及以下", "仅", "只输出", "错误", "不完整"]
    result = []
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        if any(word in text for word in no_problem_words):
            continue
        if any(word in text for word in weak_operator_words) and not any(word in text for word in real_miss_words):
            continue
        result.append(value)
    return result


def judge_record_from_item(case_id, item, source):
    existing = item.get("judge_result") if isinstance(item.get("judge_result"), dict) else None
    if existing and existing.get("verdict") in {"correct", "incorrect"}:
        verdict = existing.get("verdict")
        return {
            "case_id": case_id,
            **existing,
            "verdict": verdict,
            "review_verdict": "通过" if verdict == "correct" else "不通过",
            "judge_source": source,
            "judged_at": existing.get("judged_at") or item.get("updated_at") or now_utc(),
        }
    return {
        "case_id": case_id,
        "status": "judge_unavailable",
        "verdict": "judge_unavailable",
        "review_verdict": "待判定",
        "probability": 0.0,
        "expected": {"query_logic": "AND", "conditions": []},
        "actual": item.get("actual") or {},
        "missing_conditions": [],
        "wrong_conditions": [],
        "extra_conditions": [],
        "evidence": "历史产物未包含 server-side judge 结果；不能用 review_verdict/verdict/source/run_status 迁移为最终正确性判定，需要重跑 parser + judge。",
        "failure_category": "评估口径问题",
        "failure_stage": "评估口径",
        "next_agent": "check",
        "judge_source": source,
        "judge_method": "migration-without-final-verdict",
        "judged_at": item.get("updated_at") or now_utc(),
    }


def heuristic_judge(query, actual):
    matched_level = (actual or {}).get("matched_level")
    hint_fields = hint_fields_from_query(query or "")
    return {
        "status": "judge_unavailable",
        "verdict": "judge_unavailable",
        "review_verdict": "待判定",
        "probability": 0.0,
        "expected": {"query_logic": "AND", "conditions": []},
        "actual": actual or {},
        "missing_conditions": [],
        "wrong_conditions": [],
        "extra_conditions": [],
        "evidence": f"judge LLM 调用失败；matched_level={matched_level} 和字段提示不能作为 correct/incorrect 依据，需要重跑 server-side judge。",
        "failure_category": "标注不确定",
        "failure_stage": "评估口径",
        "debug_hint": "judge 不可用时不产出最终 verdict，避免启发式字段污染归因聚簇。",
        "next_agent": "check",
        "judge_hints": {"fields": hint_fields},
    }


def build_judge_prompt(payload):
    query = payload.get("query") or ""
    actual = payload.get("actual") or {}
    context = build_context(query, actual)
    return f"""你是客户搜索正确性判定 judge agent。只判断 API 输出是否正确，不做根因归因。

硬性原则：
- 不看 HTTP 200、review_verdict、source、run_status、root_cause_cluster 或归因状态来判正确性。
- 必须从当前 query 重新推导 expected intent，不能继承历史 case 或归因结论。
- 以当前字段定义、枚举、prompt、QA 和 actual conditions 判断字段/操作符/值/逻辑是否语义正确。
- 但判定对象是 API 最终 actual output；必须接受当前项目已经明确存在的最终输出归一化：
  1. `query_router.normalize_conditions_for_summary` 会把单值 `CONTAINS [x]` 轻量归并为 `MATCH x`，因此对同一字段单个枚举值，`MATCH x` 与 `CONTAINS [x]` 在下游可执行语义等价时不得仅因操作符/容器形态判错；多值集合、否定缺口仍按 `CONTAINS`/`NOT_CONTAINS` 判断。
  2. `query_router.convert_age_to_birthday` 会把 `familyInfo.familyclientage` 转成 `familyInfo.familyclientbirthday` 日期条件；只要日期边界与当前日期下的年龄语义等价，不得机械要求保留 age 字段。
  3. 如果配置、prompt 示例和后处理存在表述冲突，优先按最终 API actual 是否可执行且语义覆盖用户核心意图判断；把冲突写入 evidence，低置信度或交给 check，但不要一会儿同类判 correct、一会儿同类判 incorrect。
- 最终 verdict 只能是 correct 或 incorrect。

输出 JSON schema:
{{
  "status":"judged",
  "verdict":"correct|incorrect",
  "review_verdict":"通过|不通过",
  "probability":0.95,
  "expected":{{"query_logic":"AND","conditions":[]}},
  "actual":{{}},
  "missing_conditions":[],
  "wrong_conditions":[],
  "extra_conditions":[],
  "evidence":"判定依据",
  "failure_category":"无失败|路由/规则召回问题|Prompt 问题|配置/枚举问题|输出后处理问题|字段不支持|评估口径问题|标注不确定",
  "failure_stage":"通过|L1|L2|L3|L4|后处理|配置|评估口径|不确定",
  "debug_hint":"最小定位提示",
  "next_agent":"none|attribute-analyzer|check"
}}

用户 query:
{query}

API actual extra_output_params:
{json.dumps(actual, ensure_ascii=False, indent=2)}

robot_text:
{payload.get("robot_text") or ""}

参考备注（只能参考，不能覆盖当前 query 与配置）:
{json.dumps(payload.get("reference") or {}, ensure_ascii=False, indent=2)}

相关代码/配置片段:
{context}
"""


def call_judge(payload):
    model = payload.get("judge_model") or load_yaml_value("LLM_ATTRIBUTION_MODEL", MODEL_DEFAULT)
    thinking_mode = payload.get("thinking_mode") or load_yaml_value("LLM_ATTRIBUTION_THINKING_MODE", "max")
    try:
        judgement, meta = call_json_llm(build_judge_prompt(payload), model, thinking_mode, 3000, 0.1, 120)
        judgement.update(meta)
        judgement["judge_method"] = "server-side-llm-judge"
    except Exception as exc:
        judgement = heuristic_judge(payload.get("query") or "", payload.get("actual") or {})
        judgement["judge_method"] = "local-heuristic-fallback"
        judgement["judge_error"] = str(exc)
        judgement["llm_used"] = False
    verdict = judgement.get("verdict")
    if verdict not in {"correct", "incorrect"} and judgement.get("review_verdict") in {"通过", "不通过"}:
        verdict = "correct" if judgement.get("review_verdict") == "通过" else "incorrect"
    if verdict in {"correct", "incorrect"}:
        judgement["verdict"] = verdict
        judgement["review_verdict"] = "通过" if verdict == "correct" else "不通过"
    else:
        judgement["verdict"] = "judge_unavailable"
        judgement["review_verdict"] = "待判定"
    judgement["actual"] = judgement.get("actual") or payload.get("actual") or {}
    judgement = reconcile_judge_verdict(judgement, payload.get("actual") or {})
    judgement["judged_at"] = now_utc()
    return judgement


def analysis_has_actual_problem(analysis):
    return bool(
        meaningful_problem_entries(analysis.get("actual_problem") or [])
        or meaningful_problem_entries(analysis.get("missing_conditions") or [])
        or meaningful_problem_entries(analysis.get("wrong_conditions") or [])
        or meaningful_problem_entries(analysis.get("extra_conditions") or [])
    )


def analysis_quality(analysis):
    suspected = analysis.get("suspected_files") or []
    suggestions = analysis.get("config_or_code_change_suggestion") or []
    evidence = analysis.get("evidence_chain") or []
    impact = analysis.get("business_impact") or ""
    summary = analysis.get("llm_diagnosis_summary") or ""
    patch_plan = analysis.get("proposed_patch_plan") or []
    expected = analysis.get("expected_conditions") or []
    actual_problem = analysis.get("actual_problem") or []
    detail = analysis.get("llm_diagnosis_detail") or ""
    has_problem = analysis_has_actual_problem(analysis)
    missing = []
    if not summary or len(summary) < 12:
        missing.append("缺少明确定位结论")
    if not detail or len(detail) < 80:
        missing.append("缺少关键断点详细说明 llm_diagnosis_detail")
    if detail and not any(word in detail for word in ["输出", "结果", "conditions", "matched_level"]):
        missing.append("llm_diagnosis_detail 缺少函数输出结果证明")
    if not evidence or len(evidence) < 3:
        missing.append("证据链不足")
    if has_problem and not suspected:
        missing.append("缺少疑似代码/配置位置")
    for item in suspected:
        if not isinstance(item, dict):
            continue
        line_range = str(item.get("line_range") or "").strip()
        if not line_range or line_range.upper() == "N/A" or not re.search(r"\d", line_range):
            missing.append("疑似代码/配置位置缺少可核验行号")
            break
    if has_problem and not suggestions:
        missing.append("缺少具体修改建议")
    if has_problem and not patch_plan:
        missing.append("缺少明确修改方案")
    if not expected and not actual_problem:
        missing.append("缺少当前 query 的期望条件或实际问题说明")
    vague_words = ["检查", "优化", "调整", "复核"]
    if has_problem and suggestions and all(any(word in str(item) for word in vague_words) and len(str(item)) < 40 for item in suggestions):
        missing.append("修改建议过于泛泛")
    if has_problem and not impact:
        missing.append("缺少业务影响")
    return {
        "passed": not missing,
        "missing": missing,
        "standard": "必须围绕当前 query 产出明确根因、可核验证据链、疑似文件/配置位置、具体修改建议、明确修改方案和业务影响；期望条件和修改方案必须来自当前 query 或同 query 链路探针，不能引用无关历史 case 字段。正确输出无需提供修改方案，但必须说明期望条件与实际输出一致。",
    }


def call_json_llm(prompt, model=None, thinking_mode=None, max_tokens=4000, temperature=0.1, timeout=90):
    api_key = load_yaml_value("LLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY，请在环境变量或 dev_client_search_args.yaml 中配置。")
    base_url = load_yaml_value("LLM_BASE_URL", BASE_URL_DEFAULT).rstrip("/")
    model = validate_llm_model_provider(model or load_yaml_value("LLM_ATTRIBUTION_MODEL", MODEL_DEFAULT), base_url)
    thinking_mode = thinking_mode or load_yaml_value("LLM_ATTRIBUTION_THINKING_MODE", "max")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出可解析 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if model == "deepseek-v4-pro":
        body["extra_body"] = {"thinking_mode": thinking_mode}
    req = urllib.request.Request(
        completion_url(base_url),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail[:1000]}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"LLM request timed out after {timeout}s. 当前请求已到达 llm_attribution_server.py，但上游模型接口未在限定时间内返回；可改用本地断点归因或稍后重试。") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise RuntimeError(f"LLM request timed out after {timeout}s. 当前请求已到达 llm_attribution_server.py，但上游模型接口未在限定时间内返回；可改用本地断点归因或稍后重试。") from exc
        raise RuntimeError(f"LLM request failed: {exc.reason}") from exc
    elapsed_ms = round((time.time() - start) * 1000)
    data = json.loads(raw)
    content = data["choices"][0]["message"].get("content") or ""
    if not content:
        content = data["choices"][0]["message"].get("reasoning_content") or raw[:4000]
    parsed = extract_json_object(content)
    return parsed, {
        "llm_used": True,
        "analysis_model": model,
        "analysis_thinking_mode": thinking_mode if model == "deepseek-v4-pro" else "default",
        "analysis_elapsed_ms": elapsed_ms,
    }


def enforce_chain_probe_analysis(payload, analysis):
    item = find_chain_probe_item(payload.get("query") or "")
    if not item:
        return analysis
    proof = infer_breakpoint_proof(item, payload.get("actual") or {})
    field_diff = proof.get("field_diff") or {}
    l4_unexpected = field_diff.get("l4_unexpected_fields") or []
    candidate_missing = field_diff.get("candidate_missing_after_merge") or []
    expected_fields = field_diff.get("expected_fields") or []
    query = payload.get("query") or ""
    query_expected = premium_query_expected_conditions(query)
    same_topic_probe = same_topic_chain_probe(query, item)
    detail = (
        f"断点前 level2.recall_candidate_conditions 输出 conditions={proof['before_breakpoint']['conditions']}，"
        f"说明规则候选已识别核心字段。"
        f"level4.parse 输出 conditions={proof['l4_parse']['conditions']}。"
        f"router._merge_l2_candidate_conditions 输出 conditions={proof['merge_result']['conditions']}。"
        f"断点 router._finalize_l4_result->_finalize_conditions->_validate_conditions 输出 {proof['breakpoint']['output']}。"
        f"字段差异：expected={expected_fields}，L2候选={field_diff.get('l2_candidate_fields')}，L4实际={field_diff.get('l4_fields')}。"
        f"实际问题：{proof.get('likely_actual_issue')}。"
        "代码落点：src/main/python/steps/query_router.py:260-265 finalize 调 _validate_conditions，"
        "src/main/python/steps/query_router.py:322-327 L4 final_conditions 为空会返回 empty result。"
    )
    if same_topic_probe:
        detail += (
            "字段配置落点应以当前 query 命中的字段定义和同 query 链路探针为准。"
            "修改方向：先确认当前 query 的 L2/L4/merge/finalize 首个异常点，再按断点证据修规则、字段召回或 L4 prompt。"
        )
    else:
        detail += "当前 query 与链路探针不是同一字段主题，链路探针只能作为缺少同 query 断点证据的提示，不能注入其它 query 的期望条件。"
    if l4_unexpected or candidate_missing or proof.get("breakpoint", {}).get("output", "").endswith("conditions=0 条"):
        analysis["llm_diagnosis_detail"] = detail
        if l4_unexpected:
            analysis["llm_diagnosis_summary"] = f"L4 输出错误字段 {','.join(l4_unexpected)}，merge 未修复，finalize 校验后清空条件"
            analysis["llm_owner_module"] = "L4大模型解析"
        if same_topic_probe:
            analysis["expected_conditions"] = analysis.get("expected_conditions") or query_expected or []
        problems = analysis.get("actual_problem") or []
        if l4_unexpected:
            problems.insert(0, f"L4 实际输出错误字段 {','.join(l4_unexpected)}")
        if candidate_missing:
            problems.insert(0, f"merge 后缺少正确候选字段 {','.join(candidate_missing)}")
        analysis["actual_problem"] = list(dict.fromkeys(problems))[:4]
        evidence = [
            f"chain_probe level2.recall_candidate_conditions={proof['before_breakpoint']['conditions']}",
            f"chain_probe level4.parse={proof['l4_parse']['conditions']}",
            f"chain_probe merge={proof['merge_result']['conditions']}",
            f"chain_probe finalize={proof['breakpoint']['output']}",
        ]
        analysis["evidence_chain"] = list(dict.fromkeys(evidence + (analysis.get("evidence_chain") or [])))[:6]
        suspected = analysis.get("suspected_files") or []
        common_suspected = [
            {"file": "src/main/python/steps/level4_llm_parser.py", "line_range": "107-188", "symbol": "RAG字段注入", "reason": "L4 最终选择了与字段定义不一致的字段"},
            {"file": "src/main/python/steps/query_router.py", "line_range": "322-327", "symbol": "_build_l4_result", "reason": "finalize 后为空时返回 matched_level=0"},
        ]
        if same_topic_probe:
            for field in expected_fields[:2]:
                common_suspected.append({"file": "src/main/python/config/field_definitions_args.yaml", "line_range": f"搜索 {field}", "symbol": field, "reason": "当前 query 的期望字段需要按现有字段定义和同 query 断点证据核对"})
        analysis["suspected_files"] = (common_suspected + suspected)[:4]
        if same_topic_probe:
            suggestions = analysis.get("config_or_code_change_suggestion") or []
            suggestions = [
                "按同 query 链路探针确认首个异常函数，不使用历史样例字段或数值生成修法。",
                "只围绕当前 query 的 expected-vs-actual gap 修规则、字段召回或 L4 prompt。",
                "补充当前 query 回归，断言 judge missing/wrong/extra diff 被修复且 analyzer 质量门通过。",
            ] + suggestions
            analysis["config_or_code_change_suggestion"] = list(dict.fromkeys(suggestions))[:4]
            patch_plan = analysis.get("proposed_patch_plan") or []
            patch_plan = [
                "运行当前 query 的 run_chain_probes.py 断点探针。",
                "确认 L2/L4/merge/finalize 中第一个与 expected-vs-actual gap 不一致的位置。",
                "按断点证据做最小修复并重跑 judge -> analyzer -> check gate。",
            ] + patch_plan
            analysis["proposed_patch_plan"] = list(dict.fromkeys(patch_plan))[:4]
            analysis.setdefault("business_impact", "当前查询的结构化条件错误会导致目标客户名单过宽、过窄或为空。")
        analysis["deterministic_breakpoint_proof"] = proof
    return analysis


def local_breakpoint_analysis(payload, error=None):
    analysis = {
        "llm_used": False,
        "analysis_model": load_yaml_value("LLM_ATTRIBUTION_MODEL", MODEL_DEFAULT),
        "analysis_thinking_mode": load_yaml_value("LLM_ATTRIBUTION_THINKING_MODE", "max"),
        "analysis_elapsed_ms": 0,
        "analysis_method": "deterministic-chain-debug-fallback",
        "llm_error": str(error) if error else "",
        "llm_diagnosis_summary": "上游大模型超时或不可用，已使用本地链路探针和当前 API 输出生成可复核断点归因。",
        "llm_diagnosis_detail": "未找到匹配链路探针；请先运行 run_chain_probes.py 生成 key_functions.trace，再重新归因。",
        "expected_conditions": [],
        "actual_problem": [],
        "evidence_chain": [],
        "suspected_files": [],
        "config_or_code_change_suggestion": [],
        "proposed_patch_plan": [],
        "business_impact": "当前查询无法形成可信归因时，开发无法判断应修规则、字段召回还是 L4 输出。",
    }
    analysis = enforce_chain_probe_analysis(payload, analysis)
    if not analysis.get("evidence_chain"):
        actual = payload.get("actual") or {}
        query = payload.get("query") or ""
        expected = premium_query_expected_conditions(query)
        if expected:
            analysis["expected_conditions"] = expected
            analysis["llm_diagnosis_detail"] = (
                f"API 当前输出 matched_level={actual.get('matched_level')}，conditions={actual.get('conditions') or []}。"
                f"当前 query 的核心期望条件是 {expected}。"
                "没有命中 chain_probe_results.json 中同 query 的 key_functions.trace，无法证明条件在哪个函数丢失。"
                "下一步先为该 query 运行链路探针，再按首个异常函数修规则、字段召回或 L4 prompt。"
            )
            analysis["actual_problem"] = ["缺少同 query 可复现链路探针证据"]
            analysis["evidence_chain"] = [
                f"live actual matched_level={actual.get('matched_level')} conditions={actual.get('conditions') or []}",
                f"当前 query 推导期望条件={expected}",
                "FIELD_HINTS 仅作为当前 query 字段提示，不能替代同 query 链路证据或注入无关字段",
            ]
            hinted_fields = hint_fields_from_query(query)
            analysis["suspected_files"] = [
                {"file": "search-test-case/run_chain_probes.py", "line_range": "运行同 query 探针", "symbol": "key_functions.trace", "reason": "当前 fallback 没有同 query 断点证据，不能直接给最终 patch plan"},
                {"file": "src/main/python/config/field_definitions_args.yaml", "line_range": "搜索 " + " / ".join(hinted_fields[:3]), "symbol": "当前 query 字段定义", "reason": "仅核对字段承载与单位，不作为无探针时的最终根因"},
            ]
            analysis["config_or_code_change_suggestion"] = ["先补该 query 的链路探针，再根据首个异常函数决定是否修改规则、字段召回或 L4 prompt。"]
            analysis["proposed_patch_plan"] = ["运行 run_chain_probes.py 复现该 query", "确认期望字段在 L2/L4/merge/finalize 哪一步丢失", "只按同 query 断点证据提出业务代码/配置修改方案"]
            analysis["business_impact"] = "当前查询缺少可信断点证据时，直接给规则修法容易把历史样例结论误注入当前 query。"
        else:
            analysis["llm_diagnosis_detail"] = (
                f"API 当前输出 matched_level={actual.get('matched_level')}，conditions={actual.get('conditions') or []}。"
                "没有命中 chain_probe_results.json 中同 query 的 key_functions.trace，无法证明具体函数断点。"
                "下一步先运行 python3 search-test-case/run_chain_probes.py，为该 query 补 normalize/L1/L2/L4/finalize 断点证据。"
            )
            analysis["actual_problem"] = ["缺少可复现链路探针证据"]
            analysis["evidence_chain"] = [f"live actual matched_level={actual.get('matched_level')} conditions={actual.get('conditions') or []}"]
            analysis["config_or_code_change_suggestion"] = ["先补该 query 的链路探针，再根据首个异常函数决定是否修改规则、字段召回或 L4 prompt。"]
            analysis["proposed_patch_plan"] = ["运行 run_chain_probes.py 复现该 query", "确认首个异常函数输出", "只按断点证据提出业务代码/配置修改方案"]
    analysis["analysis_quality"] = analysis_quality(analysis)
    return analysis


def external_general_eval_judgement(payload):
    judgement = payload.get("general_eval_judge_result")
    if not isinstance(judgement, dict):
        return None
    if judgement.get("verdict") not in {"correct", "incorrect"}:
        return None
    normalized = dict(judgement)
    normalized["judge_source"] = normalized.get("judge_source") or "general_eval_judge_result"
    normalized["judge_method"] = normalized.get("judge_method") or "external-general-eval-live-semantic-judge"
    normalized["external_judge_result_used"] = True
    normalized["actual"] = normalized.get("actual") or payload.get("actual") or {}
    return normalized


def analyze_after_judge(payload, judgement):
    if judgement.get("verdict") == "judge_unavailable":
        return {
            "analysis_method": "blocked-judge-unavailable",
            "analysis_quality": {"passed": False, "missing": ["judge 不可用，不能进入正式失败归因"]},
            "llm_diagnosis_summary": "judge 未完成 server-side 正确性裁决，按标准链路阻断归因。",
            "evidence_chain": [judgement.get("judge_error") or judgement.get("evidence") or "judge_unavailable"],
            "suspected_files": [],
            "proposed_patch_plan": ["修复 LLM_API_KEY/模型服务配置后重跑 parser -> judge -> attribute 链路"],
            "verdict": "judge_unavailable",
            "review_verdict": "待判定",
        }
    if judgement.get("verdict") != "incorrect":
        return {
            "analysis_method": "skipped-unless-judge-incorrect",
            "analysis_quality": {"passed": True, "missing": []},
            "llm_diagnosis_summary": "judge 未判为 incorrect，按标准链路不执行失败归因。",
            "evidence_chain": [judgement.get("evidence") or "judge 未判为 incorrect"],
            "suspected_files": [],
            "proposed_patch_plan": [],
        }
    return call_llm(payload, judgement)


def call_llm(payload, judgement=None):
    model = payload.get("analysis_model") or load_yaml_value("LLM_ATTRIBUTION_MODEL", MODEL_DEFAULT)
    thinking_mode = payload.get("thinking_mode") or load_yaml_value("LLM_ATTRIBUTION_THINKING_MODE", "max")
    try:
        analysis, meta = call_json_llm(build_prompt(payload), model, thinking_mode, 4000, 0.1, 120)
    except json.JSONDecodeError as exc:
        analysis = analysis_from_raw_content(str(exc), "LLM 返回内容不是完整可解析 JSON；已保留错误信息供排查。", 0.3)
        meta = {
            "llm_used": True,
            "analysis_model": model,
            "analysis_thinking_mode": thinking_mode if model == "deepseek-v4-pro" else "default",
            "analysis_elapsed_ms": 0,
        }
    except Exception as exc:
        analysis = local_breakpoint_analysis(payload, exc)
        if judgement:
            analysis = apply_analysis_check_gate(payload, analysis, judgement)
        return analysis
    analysis.update(meta)
    analysis = enforce_chain_probe_analysis(payload, analysis)
    analysis["analysis_method"] = "server-side-llm-chain-debug"
    if judgement:
        analysis = apply_analysis_check_gate(payload, analysis, judgement)
    else:
        analysis["analysis_quality"] = analysis_quality(analysis)
    return analysis


def artifact_items_with_judgements(items):
    attributions = {item.get("case_id"): item for item in load_case_attributions().get("items") or [] if item.get("case_id")}
    judgements = {item.get("case_id") or item.get("id"): item for item in load_case_judgements().get("items") or [] if item.get("case_id") or item.get("id")}
    merged = []
    for item in items:
        case_id = item.get("case_id") or item.get("id")
        attr_record = attributions.get(case_id) or {}
        attr_item = attr_record.get("attribution_item") if isinstance(attr_record.get("attribution_item"), dict) else None
        if attr_item:
            merged_item = {**item, **attr_item, "id": case_id, "case_id": case_id}
            for key in ["attribution_status", "analysis_quality"]:
                if attr_record.get(key) is not None:
                    merged_item[key] = attr_record.get(key)
        else:
            merged_item = item
        judgement = judgements.get(case_id) or (merged_item.get("judge_result") if isinstance(merged_item.get("judge_result"), dict) else {}) or {}
        if judgement:
            currentness = judge_currentness(judgement)
            merged_item = {**merged_item, "judge_result": judgement, "judge_currentness": currentness}
            for key in ["verdict", "review_verdict", "missing_conditions", "wrong_conditions", "extra_conditions", "evidence", "failure_category", "failure_stage"]:
                if judgement.get(key) is not None:
                    merged_item[key] = judgement.get(key)
            if currentness == "current" and judgement.get("expected"):
                merged_item["expected"] = judgement.get("expected")
                if isinstance(judgement.get("expected"), dict) and judgement["expected"].get("conditions"):
                    merged_item["expected_conditions"] = judgement["expected"].get("conditions")
        merged_item["currentness"] = attribution_currentness(merged_item, judgement)
        merged.append(merged_item)
    return merged


def build_summary_from_artifacts():
    failure_path = ROOT / "failure_analysis.json"
    clusters_path = ROOT / "root_cause_clusters.json"
    if not failure_path.exists():
        raise RuntimeError("缺少 failure_analysis.json，请先生成逐条归因结果。")
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    clusters_file = json.loads(clusters_path.read_text(encoding="utf-8")) if clusters_path.exists() else {}
    items = artifact_items_with_judgements(failure.get("items") or [])
    all_incorrect = [item for item in items if item.get("verdict") == "incorrect"]
    incorrect = quality_filtered_items(items)
    excluded_reasons = noncanonical_attribution_reasons(items)
    needs_review = needs_review_case_rows(items)
    cluster_entries, unclustered, clustered_ids = semantic_cluster_entries(incorrect, items)
    return {
        "generated_at": now_utc(),
        "generated_by": "llm_attribution_server independent semantic recluster",
        "llm_used": False,
        "totals": {
            "total_cases": failure.get("total") or len(items),
            "incorrect_cases": len(incorrect),
            "source_incorrect_cases": len(all_incorrect),
            "excluded_noncanonical_cases": sum(excluded_reasons.values()),
            "clustered_cases": len(clustered_ids),
            "unclustered_cases": len(unclustered),
            "cluster_count": len(cluster_entries),
        },
        "by_failure_category": failure.get("by_failure_category") or {},
        "by_failure_stage": failure.get("by_failure_stage") or {},
        "top_priorities": [{"id": c["id"], "title": c["title"], "affected_count": c["affected_count"], "priority": c["priority"], "solution": c["solution"]} for c in cluster_entries[:5]],
        "clusters": cluster_entries,
        "unclustered_cases": unclustered,
        "needs_review_cases": needs_review,
        "agent_flow": "parser -> judge -> 不通过 -> attribute-analyzer -> check gate -> 独立语义聚簇；总不通过以 judge 不通过为准，正式聚簇只使用归因质量通过的子集",
        "cluster_merge_gate": "独立聚簇由当前 query、failure_stage/failure_category、impacted_fields、likely_root_cause、fix_hint、suspected_locations 的语义主题生成 canonical_cluster_key；source_cluster_hint、legacy_reference_cluster 和历史 root_cause_clusters 仅作展示/覆盖参考，不参与正式分组。",
        "quality": {
            "passed": bool(cluster_entries),
            "excluded_noncanonical_reasons": excluded_reasons,
            "canonical_filter": "server-side judge 判定不通过 + 归因质量通过 + analysis_method 当前有效 + 非 reference-only/非 stale/非 fallback/非需重跑",
            "note": "按当前逐条 judge 与 attribute-analyzer 结果独立语义重聚簇；不复用 root_cause_clusters 作为正式分组依据。" + " " + (clusters_file.get("recluster_review") or {}).get("changed", "") + " 总不通过=judge 判定 parser 输出不正确的数量；进入正式聚簇=这些不通过里归因也通过质量门、可放进默认总结的数量；需复核=parser 已判不正确，但归因结果过期、需重跑或质量不够，暂不放进正式总结。",
        },
    }


def local_case_pool_from_summary(summary):
    cases = []
    for cluster in summary.get("clusters") or []:
        cluster_id = cluster.get("id") or "cluster"
        title = str(cluster.get("title") or cluster.get("root_cause") or cluster_id).strip()
        root_cause = str(cluster.get("root_cause") or title).strip()
        fields = [str(field) for field in cluster.get("impacted_fields") or [] if field]
        field_hint = "、".join(fields[:3]) if fields else "相关字段"
        query = f"验证{title}：围绕{field_hint}补充一个当前配置支持的客户搜索 query"
        cases.append({
            "id": f"generated-{cluster_id}-01",
            "query": query,
            "source_cluster_hint": cluster_id,
            "legacy_reference_cluster": "",
            "cluster_binding": "reference_only",
            "expected_intent": root_cause,
            "expected_conditions": [],
            "reason": "基于当前正式 summary 证据生成的回归候选骨架，需再跑解析 API、judge 和 attribute agent 标注；来源簇只作覆盖参考，不作为正式聚簇依据。",
            "source": "current_summary_skeleton",
        })
    return cases



def now_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def safe_case_id(value, prefix="uploaded"):
    raw = str(value or "").strip()
    raw = re.sub(r"[^0-9A-Za-z_\-]+", "-", raw).strip("-")
    return raw[:80] or f"{prefix}-{int(time.time())}"


SOURCE_LABELS = {
    "user_upload": "用户上传",
    "current_summary_skeleton": "当前 summary 证据骨架",
    "llm_generated": "大模型生成",
    "named_pool": "命名用例池",
    "saved_case_pool": "已保存候选池",
    "基础用例": "基础用例",
}

SUMMARY_SOURCE_LABELS = {
    "default": "默认正式聚簇",
    "custom": "自定义/上传用例聚簇",
    "mixed": "默认+自定义混合聚簇",
    "default_selected": "默认选择子集聚簇",
    "saved": "已保存聚簇报告",
}


def source_label(source):
    return SOURCE_LABELS.get(source) or source or "候选用例"


def case_batch_display_name(item):
    if not item:
        return "候选用例"
    import_batch_id = str(item.get("import_batch_id") or "").strip()
    if import_batch_id:
        return import_batch_id
    pool_name = str(item.get("pool_name") or item.get("case_pool_name") or "").strip()
    if pool_name:
        return pool_name
    source = item.get("source") or "user_upload"
    return source_label(source)


def unique_case_pool_names(items):
    names = []
    for item in items or []:
        if not item:
            continue
        name = case_batch_display_name(item)
        if name and name not in names:
            names.append(name)
    return names


def unique_import_batch_ids(items):
    batch_ids = []
    for item in items or []:
        batch_id = str((item or {}).get("import_batch_id") or "").strip()
        if batch_id and batch_id not in batch_ids:
            batch_ids.append(batch_id)
    return batch_ids


def generated_summary_name(name):
    text = str(name or "").strip()
    case_fallback = re.match(r"^自定义/上传用例聚簇\s+case\b", text)
    generated_markers = ["｜总", "｜错", "｜簇", "用例集:", "自定义/上传用例聚簇", "默认+自定义混合聚簇", "默认选择子集聚簇"]
    return not text or text == "归因聚簇结果" or bool(case_fallback) or any(marker in text for marker in generated_markers)


def summary_display_name(summary, source=None):
    source = source or summary.get("source") or "custom"
    batch_ids = [str(name) for name in (summary.get("import_batch_ids") or []) if name]
    if batch_ids:
        base = "、".join(batch_ids[:3])
    else:
        pool_names = [str(name) for name in (summary.get("case_pool_names") or []) if name]
        if pool_names:
            base = "、".join(pool_names[:3])
        else:
            explicit = str(summary.get("display_name") or summary.get("name") or "").strip()
            if explicit and not generated_summary_name(explicit):
                base = explicit
            elif source in {"custom", "mixed"}:
                base = "未记录导入批次的自定义/上传用例聚簇"
            else:
                base = SUMMARY_SOURCE_LABELS.get(source, source or "自定义聚簇")
    hidden_count = len(summary.get("hidden_clusters") or [])
    return f"{base}（已隐藏{hidden_count}簇）" if hidden_count else base


def canonical_summary_name(summary, source=None):
    return summary_display_name(summary, source)


def normalize_summary_names(summary, source=None):
    name = canonical_summary_name(summary, source)
    summary["name"] = name
    summary["display_name"] = name
    return summary


def normalize_case_pool_metadata(pool):
    changed = False
    for case in pool.get("cases") or []:
        item = case.get("attribution_item")
        if not isinstance(item, dict):
            continue
        for key in ("source", "pool_name", "import_batch_id"):
            value = case.get(key) or ""
            if (item.get(key) or "") != value:
                item[key] = value
                changed = True
    return changed


def normalize_case_input(item, idx=0, batch_id=None, pool_name=None):
    if isinstance(item, str):
        item = {"query": item}
    if not isinstance(item, dict):
        return None
    query = str(item.get("query") or item.get("user_text") or item.get("prompt") or "").strip()
    if not query:
        return None
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:8]
    case_id = safe_case_id(item.get("id") or f"uploaded-{digest}-{idx + 1:03d}")
    source = item.get("source") if item.get("source") in {"user_upload", "current_summary_skeleton", "llm_generated", "named_pool"} else "user_upload"
    pool = str(pool_name or item.get("pool_name") or item.get("case_pool_name") or "").strip()
    legacy_reference_cluster = str(item.get("legacy_reference_cluster") or "").strip()
    source_cluster_hint = str(item.get("source_cluster_hint") or item.get("target_cluster") or item.get("root_cause_cluster") or "").strip()
    cluster_binding = str(item.get("cluster_binding") or "").strip()
    if source_cluster_hint and not cluster_binding:
        cluster_binding = "reference_only"
    return {
        "id": case_id,
        "query": query,
        "source_cluster_hint": source_cluster_hint,
        "legacy_reference_cluster": legacy_reference_cluster,
        "cluster_binding": cluster_binding,
        "expected_intent": str(item.get("expected_intent") or item.get("intent") or "").strip(),
        "expected_conditions": item.get("expected_conditions") or [],
        "reason": str(item.get("reason") or "用户上传/导入候选用例").strip(),
        "source": source,
        "import_batch_id": batch_id or item.get("import_batch_id"),
        "pool_name": pool,
        "imported_at": item.get("imported_at") or now_utc(),
        "has_attribution": bool(item.get("has_attribution") or item.get("attribution_item")),
        "run_status": item.get("run_status") or ("attributed" if item.get("attribution_item") else "pending"),
        **({"parser_result": item.get("parser_result")} if item.get("parser_result") else {}),
        **({"attribution_item": item.get("attribution_item")} if item.get("attribution_item") else {}),
    }


def canonical_case_id(value, prefix="case"):
    return safe_case_id(value, prefix)


def canonical_case_record(item, origin_type=None, origin_ref=None, source_label_value=None):
    if not isinstance(item, dict):
        return None
    case_id = canonical_case_id(item.get("case_id") or item.get("id"), "case")
    query = str(item.get("query") or item.get("user_text") or item.get("prompt") or "").strip()
    if not case_id or not query:
        return None
    now = now_utc()
    legacy_reference_cluster = str(item.get("legacy_reference_cluster") or "").strip()
    source_cluster_hint = str(item.get("source_cluster_hint") or item.get("target_cluster") or "").strip()
    cluster_binding = str(item.get("cluster_binding") or "").strip()
    if source_cluster_hint and not cluster_binding:
        cluster_binding = "reference_only"
    return {
        "case_id": case_id,
        "id": case_id,
        "query": query,
        "origin_type": origin_type or item.get("origin_type") or item.get("source") or "unknown",
        "origin_ref": origin_ref or item.get("origin_ref") or item.get("import_batch_id") or item.get("pool_name") or "",
        "source": item.get("source") or origin_type or "unknown",
        "source_label": source_label_value or item.get("source_label") or source_label(item.get("source") or origin_type or "unknown"),
        "source_cluster_hint": source_cluster_hint,
        "legacy_reference_cluster": legacy_reference_cluster,
        "cluster_binding": cluster_binding,
        "expected_intent": str(item.get("expected_intent") or item.get("intent") or item.get("intent_summary") or "").strip(),
        "expected_conditions": item.get("expected_conditions") or [],
        "reason": str(item.get("reason") or item.get("evidence") or "").strip(),
        "created_at": item.get("created_at") or item.get("imported_at") or item.get("generated_at") or now,
        "updated_at": item.get("updated_at") or now,
        "deleted": bool(item.get("deleted")),
    }


def ensure_attribution_store_dir():
    ATTRIBUTION_STORE_DIR.mkdir(exist_ok=True)
    SUMMARY_STORE_DIR.mkdir(exist_ok=True)


def read_json_file(path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return data if isinstance(data, type(default)) else default


def write_json_file(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_cases_master():
    ensure_canonical_store_initialized()
    data = read_json_file(CASES_MASTER_PATH, {"cases": []})
    data["cases"] = data.get("cases") or []
    return data


def save_cases_master(data):
    ensure_attribution_store_dir()
    data["cases"] = data.get("cases") or []
    data["updated_at"] = now_utc()
    return write_json_file(CASES_MASTER_PATH, data)


def load_case_attributions():
    ensure_canonical_store_initialized()
    data = read_json_file(CASE_ATTRIBUTIONS_PATH, {"items": []})
    judgements = {item.get("case_id") or item.get("id"): item for item in load_case_judgements().get("items") or [] if item.get("case_id") or item.get("id")}
    data["items"] = [normalized_attribution_record(item, judgements.get(item.get("case_id") or item.get("id"))) for item in data.get("items") or []]
    return data


def save_case_attributions(data):
    ensure_attribution_store_dir()
    data["items"] = data.get("items") or []
    data["updated_at"] = now_utc()
    return write_json_file(CASE_ATTRIBUTIONS_PATH, data)


def load_case_judgements():
    ensure_canonical_store_initialized()
    data = read_json_file(CASE_JUDGEMENTS_PATH, {"items": []})
    data["items"] = [normalized_judgement_record(item) for item in data.get("items") or []]
    return data


def save_case_judgements(data):
    ensure_attribution_store_dir()
    data["items"] = data.get("items") or []
    data["updated_at"] = now_utc()
    return write_json_file(CASE_JUDGEMENTS_PATH, data)


def load_case_batches():
    ensure_canonical_store_initialized()
    data = read_json_file(CASE_BATCHES_PATH, {"batches": [], "memberships": []})
    data["batches"] = data.get("batches") or []
    data["memberships"] = data.get("memberships") or []
    return data


def save_case_batches(data):
    ensure_attribution_store_dir()
    data["batches"] = data.get("batches") or []
    data["memberships"] = data.get("memberships") or []
    data["updated_at"] = now_utc()
    return write_json_file(CASE_BATCHES_PATH, data)


def load_named_pools_store():
    ensure_canonical_store_initialized()
    data = read_json_file(NAMED_POOLS_STORE_PATH, {"pools": [], "memberships": []})
    data["pools"] = data.get("pools") or []
    data["memberships"] = data.get("memberships") or []
    return data


def save_named_pools_store(data):
    ensure_attribution_store_dir()
    data["pools"] = data.get("pools") or []
    data["memberships"] = data.get("memberships") or []
    data["updated_at"] = now_utc()
    return write_json_file(NAMED_POOLS_STORE_PATH, data)


def load_summary_store_index():
    ensure_canonical_store_initialized()
    data = read_json_file(SUMMARY_STORE_INDEX_PATH, {"summaries": []})
    data["summaries"] = data.get("summaries") or []
    return data


def save_summary_store_index(data):
    ensure_attribution_store_dir()
    data["summaries"] = data.get("summaries") or []
    data["updated_at"] = now_utc()
    return write_json_file(SUMMARY_STORE_INDEX_PATH, data)


def upsert_by_key(items, item, key):
    value = item.get(key)
    if not value:
        return items
    return [existing for existing in items if existing.get(key) != value] + [item]


def ensure_canonical_store_initialized():
    if globals().get("_CANONICAL_STORE_INITIALIZING"):
        return
    if CASES_MASTER_PATH.exists() and CASE_ATTRIBUTIONS_PATH.exists() and CASE_BATCHES_PATH.exists() and NAMED_POOLS_STORE_PATH.exists() and SUMMARY_STORE_INDEX_PATH.exists():
        if not CASE_JUDGEMENTS_PATH.exists():
            ensure_attribution_store_dir()
            judgement_items = []
            for attr in read_json_file(CASE_ATTRIBUTIONS_PATH, {"items": []}).get("items") or []:
                item = attr.get("attribution_item")
                case_id = attr.get("case_id")
                if case_id and isinstance(item, dict):
                    judgement_items = upsert_by_key(judgement_items, judge_record_from_item(case_id, item, "existing attribution migration"), "case_id")
            write_json_file(CASE_JUDGEMENTS_PATH, {"created_at": now_utc(), "updated_at": now_utc(), "items": judgement_items})
        return
    globals()["_CANONICAL_STORE_INITIALIZING"] = True
    try:
        ensure_attribution_store_dir()
        now = now_utc()
        cases = []
        attributions = []
        judgements = []
        batches = []
        batch_memberships = []
        pools = []
        pool_memberships = []
        summaries = []
        case_by_id = {}

        def add_case(item, origin_type, origin_ref="", source_label_value=None):
            record = canonical_case_record(item, origin_type, origin_ref, source_label_value)
            if not record:
                return None
            existing = case_by_id.get(record["case_id"], {})
            merged = {**existing, **{k: v for k, v in record.items() if v not in (None, "", [])}}
            merged["case_id"] = record["case_id"]
            merged["id"] = record["case_id"]
            case_by_id[record["case_id"]] = merged
            return merged

        failure_path = ROOT / "failure_analysis.json"
        failure = read_json_file(failure_path, {"items": []})
        for item in failure.get("items") or []:
            record = add_case(item, "default", "failure_analysis.json", "基础用例")
            if record:
                attr_item = {**item, "id": record["case_id"], "case_id": record["case_id"], "source": "基础用例"}
                attributions = upsert_by_key(attributions, {
                    "case_id": record["case_id"],
                    "attribution_status": "attributed",
                    "parser_result": item.get("parser_result"),
                    "parser_error": "",
                    "attribution_item": attr_item,
                    "updated_at": item.get("updated_at") or now,
                }, "case_id")
                judgements = upsert_by_key(judgements, judge_record_from_item(record["case_id"], attr_item, "failure_analysis.json migration"), "case_id")

        saved = read_json_file(CASE_POOL_PATH, {"cases": [], "latest_batch": None, "source_clusters": []})
        saved_batch_id = "saved_case_pool"
        saved_cases = saved.get("cases") or []
        if saved_cases:
            batches.append({"batch_id": saved_batch_id, "batch_type": "saved_case_pool", "display_name": "已保存候选池", "description": "旧 attribution_case_pool.json 迁移", "created_at": saved.get("generated_at") or now, "deleted": False})
        for item in saved_cases:
            record = add_case({**item, "source": item.get("source") or "saved_case_pool"}, "saved_case_pool", "attribution_case_pool.json")
            if record:
                batch_memberships.append({"batch_id": saved_batch_id, "case_id": record["case_id"]})

        custom = read_json_file(CUSTOM_CASE_POOL_PATH, {"cases": [], "batches": []})
        for batch in custom.get("batches") or []:
            batch_id = str(batch.get("import_batch_id") or batch.get("name") or "").strip()
            if not batch_id:
                continue
            batches.append({"batch_id": batch_id, "batch_type": batch.get("source") or "user_upload", "display_name": batch_id, "description": batch.get("pool_name") or "", "created_at": batch.get("generated_at") or now, "deleted": False})
        for item in custom.get("cases") or []:
            batch_id = str(item.get("import_batch_id") or "").strip()
            record = add_case(item, item.get("source") or "user_upload", batch_id or "attribution_custom_case_pool.json")
            if not record:
                continue
            if batch_id:
                if not any(batch.get("batch_id") == batch_id for batch in batches):
                    batches.append({"batch_id": batch_id, "batch_type": item.get("source") or "user_upload", "display_name": batch_id, "description": item.get("pool_name") or "", "created_at": item.get("imported_at") or now, "deleted": False})
                batch_memberships.append({"batch_id": batch_id, "case_id": record["case_id"]})
            attr_item = item.get("attribution_item")
            if attr_item or item.get("parser_error"):
                attr_item = ({**attr_item, "id": record["case_id"], "case_id": record["case_id"]} if isinstance(attr_item, dict) else None)
                attributions = upsert_by_key(attributions, {
                    "case_id": record["case_id"],
                    "attribution_status": item.get("run_status") or ("attributed" if attr_item else "parser_failed"),
                    "parser_result": item.get("parser_result"),
                    "parser_error": item.get("parser_error") or "",
                    "attribution_item": attr_item,
                    "updated_at": item.get("updated_at") or now,
                }, "case_id")
                if attr_item:
                    judgements = upsert_by_key(judgements, judge_record_from_item(record["case_id"], attr_item, "custom pool migration"), "case_id")

        library = read_json_file(CASE_POOL_LIBRARY_PATH, {"pools": []})
        for pool in library.get("pools") or []:
            pool_id = str(pool.get("id") or pool.get("pool_id") or "").strip()
            if not pool_id:
                continue
            pools.append({"pool_id": pool_id, "id": pool_id, "name": pool.get("name") or pool_id, "description": pool.get("description") or "", "created_at": pool.get("created_at") or now, "deleted": False})
            for item in pool.get("cases") or []:
                record = add_case({**item, "source": item.get("source") or "named_pool"}, "named_pool", pool_id)
                if record:
                    pool_memberships.append({"pool_id": pool_id, "case_id": record["case_id"]})

        old_index = read_json_file(ATTRIBUTION_SUMMARY_INDEX_PATH, {"summaries": []})
        for entry in old_index.get("summaries") or []:
            if not entry.get("summary_id"):
                continue
            source_path = ROOT / (entry.get("json_path") or f"attribution_summaries/{entry.get('summary_id')}.json")
            summary = read_json_file(source_path, {}) if source_path.exists() else {}
            case_scope = summary.get("case_scope") or {
                "case_ids": summary.get("case_ids") or entry.get("case_ids") or [],
                "batch_ids": summary.get("import_batch_ids") or entry.get("import_batch_ids") or [],
                "pool_ids": [],
            }
            new_entry = {**entry, "case_scope": case_scope, "deleted": bool(entry.get("deleted"))}
            summaries = upsert_by_key(summaries, new_entry, "summary_id")
            if summary:
                summary_copy = {**summary, "case_scope": case_scope}
                write_json_file(SUMMARY_STORE_DIR / f"{entry.get('summary_id')}.json", summary_copy)

        cases = list(case_by_id.values())
        write_json_file(CASES_MASTER_PATH, {"created_at": now, "updated_at": now, "cases": cases})
        write_json_file(CASE_ATTRIBUTIONS_PATH, {"created_at": now, "updated_at": now, "items": attributions})
        write_json_file(CASE_JUDGEMENTS_PATH, {"created_at": now, "updated_at": now, "items": judgements})
        unique_batches = []
        for batch in batches:
            unique_batches = upsert_by_key(unique_batches, batch, "batch_id")
        unique_memberships = [dict(t) for t in {tuple(sorted(item.items())) for item in batch_memberships}]
        write_json_file(CASE_BATCHES_PATH, {"created_at": now, "updated_at": now, "batches": unique_batches, "memberships": unique_memberships})
        unique_pools = []
        for pool in pools:
            unique_pools = upsert_by_key(unique_pools, pool, "pool_id")
        unique_pool_memberships = [dict(t) for t in {tuple(sorted(item.items())) for item in pool_memberships}]
        write_json_file(NAMED_POOLS_STORE_PATH, {"created_at": now, "updated_at": now, "pools": unique_pools, "memberships": unique_pool_memberships})
        write_json_file(SUMMARY_STORE_INDEX_PATH, {"created_at": now, "updated_at": now, "summaries": summaries})
    finally:
        globals()["_CANONICAL_STORE_INITIALIZING"] = False


def active_batch_memberships(batches_store=None):
    batches_store = batches_store or load_case_batches()
    active_batch_ids = {batch.get("batch_id") for batch in batches_store.get("batches") or [] if batch.get("batch_id") and not batch.get("deleted")}
    return [
        member for member in batches_store.get("memberships") or []
        if member.get("case_id") and member.get("batch_id") in active_batch_ids and not member.get("deleted")
    ]


def active_pool_memberships(named_store=None):
    named_store = named_store or load_named_pools_store()
    active_pool_ids = {pool.get("pool_id") or pool.get("id") for pool in named_store.get("pools") or [] if (pool.get("pool_id") or pool.get("id")) and not pool.get("deleted")}
    return [
        member for member in named_store.get("memberships") or []
        if member.get("case_id") and member.get("pool_id") in active_pool_ids and not member.get("deleted")
    ]


def case_catalog_view():
    master = load_cases_master()
    attribution_by_id = {item.get("case_id"): item for item in load_case_attributions().get("items") or [] if item.get("case_id")}
    judgement_by_id = {item.get("case_id"): item for item in load_case_judgements().get("items") or [] if item.get("case_id")}
    batches_store = load_case_batches()
    named_store = load_named_pools_store()
    batch_by_case = {}
    for member in active_batch_memberships(batches_store):
        batch_by_case.setdefault(member.get("case_id"), []).append(member.get("batch_id"))
    pool_by_case = {}
    for member in active_pool_memberships(named_store):
        pool_by_case.setdefault(member.get("case_id"), []).append(member.get("pool_id"))
    batches = [batch for batch in batches_store.get("batches") or [] if not batch.get("deleted")]
    pools = [pool for pool in named_store.get("pools") or [] if not pool.get("deleted")]
    cases = []
    for case in master.get("cases") or []:
        if case.get("deleted"):
            continue
        case_id = case.get("case_id") or case.get("id")
        attr = attribution_by_id.get(case_id) or {}
        judgement = judgement_by_id.get(case_id) or {}
        status = attr.get("attribution_status") or "pending"
        item = attr.get("attribution_item")
        active_batch_ids = [batch_id for batch_id in batch_by_case.get(case_id, []) if batch_id]
        cases.append({
            **case,
            "id": case_id,
            "case_id": case_id,
            "batch_ids": active_batch_ids,
            "pool_ids": [pool_id for pool_id in pool_by_case.get(case_id, []) if pool_id],
            "attribution_status": status,
            "run_status": status,
            "has_attribution": bool(item),
            "parser_result": attr.get("parser_result"),
            "parser_error": attr.get("parser_error") or "",
            "attribution_item": item,
            "judge_result": judgement or None,
            "judge_currentness": judge_currentness(judgement),
            "currentness": attribution_currentness({**(item or {}), "attribution_status": status}, judgement),
            "verdict": judgement.get("verdict") or (item or {}).get("verdict") or case.get("verdict"),
            "review_verdict": judgement.get("review_verdict") or (item or {}).get("review_verdict") or case.get("review_verdict"),
            "import_batch_id": active_batch_ids[0] if active_batch_ids else "",
        })
    return {"cases": cases, "batches": batches, "named_pools": pools, "stats": {"case_count": len(cases), "batch_count": len(batches), "named_pool_count": len(pools)}}


def resolve_scope_case_ids(payload):
    requested = set(payload.get("case_ids") or payload.get("custom_case_ids") or payload.get("base_case_ids") or [])
    batch_ids = {str(x).strip() for x in (payload.get("batch_ids") or []) if str(x).strip()}
    pool_ids = {str(x).strip() for x in (payload.get("pool_ids") or []) if str(x).strip()}
    if not requested and payload.get("scope"):
        scope = payload.get("scope") or {}
        requested.update(scope.get("case_ids") or [])
        batch_ids.update(str(x).strip() for x in (scope.get("batch_ids") or []) if str(x).strip())
        pool_ids.update(str(x).strip() for x in (scope.get("pool_ids") or []) if str(x).strip())
    for member in active_batch_memberships(load_case_batches()):
        if member.get("batch_id") in batch_ids:
            requested.add(member.get("case_id"))
    for member in active_pool_memberships(load_named_pools_store()):
        if member.get("pool_id") in pool_ids:
            requested.add(member.get("case_id"))
    active_case_ids = {case.get("case_id") or case.get("id") for case in load_cases_master().get("cases") or [] if not case.get("deleted")}
    return [case_id for case_id in requested if case_id and case_id in active_case_ids]


def attributed_items_for_case_ids(case_ids):
    case_id_set = set(case_ids or [])
    cases = {case.get("case_id"): case for case in load_cases_master().get("cases") or [] if not case.get("deleted")}
    attrs = {item.get("case_id"): item for item in load_case_attributions().get("items") or [] if item.get("case_id")}
    judgements = {item.get("case_id"): item for item in load_case_judgements().get("items") or [] if item.get("case_id")}
    catalog = {case.get("case_id"): case for case in case_catalog_view().get("cases") or []}
    items = []
    for case_id in case_id_set:
        case = cases.get(case_id)
        attr = attrs.get(case_id) or {}
        item = attr.get("attribution_item")
        judgement = judgements.get(case_id) or {}
        if not case or not item:
            continue
        view = catalog.get(case_id) or {}
        batch_ids = view.get("batch_ids") or []
        merged_item = {
            **item,
            "id": case_id,
            "case_id": case_id,
            "query": item.get("query") or case.get("query"),
            "source": item.get("source") or case.get("source"),
            "pool_name": item.get("pool_name") or "",
            "import_batch_id": item.get("import_batch_id") or (batch_ids[0] if batch_ids else ""),
        }
        if judgement:
            currentness = judge_currentness(judgement)
            merged_item.update({
                "verdict": judgement.get("verdict") or merged_item.get("verdict"),
                "review_verdict": judgement.get("review_verdict") or merged_item.get("review_verdict"),
                "missing_conditions": judgement.get("missing_conditions") or merged_item.get("missing_conditions") or [],
                "wrong_conditions": judgement.get("wrong_conditions") or merged_item.get("wrong_conditions") or [],
                "extra_conditions": judgement.get("extra_conditions") or merged_item.get("extra_conditions") or [],
                "evidence": judgement.get("evidence") or merged_item.get("evidence"),
                "failure_category": judgement.get("failure_category") or merged_item.get("failure_category"),
                "failure_stage": judgement.get("failure_stage") or merged_item.get("failure_stage"),
                "judge_result": judgement,
                "judge_currentness": currentness,
            })
            if currentness == "current":
                merged_item["expected"] = judgement.get("expected") or merged_item.get("expected")
        merged_item["currentness"] = attribution_currentness(merged_item, judgement)
        items.append(merged_item)
    return items


def summary_scope_is_active(summary, catalog):
    scope = summary.get("case_scope") or {}
    active_case_ids = {case.get("case_id") for case in catalog.get("cases") or [] if case.get("case_id")}
    active_batch_ids = {batch.get("batch_id") for batch in catalog.get("batches") or [] if batch.get("batch_id")}
    active_pool_ids = {pool.get("pool_id") or pool.get("id") for pool in catalog.get("named_pools") or [] if pool.get("pool_id") or pool.get("id")}
    case_ids = {case_id for case_id in scope.get("case_ids") or summary.get("case_ids") or [] if case_id}
    batch_ids = {batch_id for batch_id in scope.get("batch_ids") or summary.get("import_batch_ids") or [] if batch_id}
    pool_ids = {pool_id for pool_id in scope.get("pool_ids") or [] if pool_id}
    if not case_ids and not batch_ids and not pool_ids:
        return (summary.get("source") or "").startswith("default")
    if batch_ids and batch_ids.isdisjoint(active_batch_ids):
        return False
    if pool_ids and pool_ids.isdisjoint(active_pool_ids):
        return False
    if case_ids and case_ids.isdisjoint(active_case_ids):
        return False
    return True


def summary_catalog_view():
    catalog = case_catalog_view()
    summaries = [
        dict(item) for item in load_summary_store_index().get("summaries") or []
        if not item.get("deleted") and summary_scope_is_active(item, catalog)
    ]
    saved_scope_keys = set()
    for summary in summaries:
        scope = summary.get("case_scope") or {}
        for batch_id in scope.get("batch_ids") or summary.get("import_batch_ids") or []:
            saved_scope_keys.add(f"batch:{batch_id}")
        for pool_id in scope.get("pool_ids") or []:
            saved_scope_keys.add(f"pool:{pool_id}")
    for batch in catalog.get("batches") or []:
        batch_id = batch.get("batch_id")
        if not batch_id or f"batch:{batch_id}" in saved_scope_keys:
            continue
        batch_cases = [case for case in catalog.get("cases") or [] if batch_id in (case.get("batch_ids") or [])]
        attributed = [case for case in batch_cases if case.get("has_attribution")]
        if not attributed:
            continue
        summaries.append({
            "summary_id": f"__ephemeral__:batch:{batch_id}",
            "source": "custom",
            "display_name": batch.get("display_name") or batch_id,
            "name": batch.get("display_name") or batch_id,
            "case_scope": {"batch_ids": [batch_id], "case_ids": [], "pool_ids": []},
            "import_batch_ids": [batch_id],
            "case_pool_names": [batch.get("display_name") or batch_id],
            "total_cases": len(attributed),
            "incorrect_cases": "-",
            "cluster_count": "-",
            "ephemeral": True,
        })
    for pool in catalog.get("named_pools") or []:
        pool_id = pool.get("pool_id") or pool.get("id")
        if not pool_id or f"pool:{pool_id}" in saved_scope_keys:
            continue
        pool_cases = [case for case in catalog.get("cases") or [] if pool_id in (case.get("pool_ids") or [])]
        attributed = [case for case in pool_cases if case.get("has_attribution")]
        if not attributed:
            continue
        summaries.append({
            "summary_id": f"__ephemeral__:pool:{pool_id}",
            "source": "custom",
            "display_name": pool.get("name") or pool_id,
            "name": pool.get("name") or pool_id,
            "case_scope": {"batch_ids": [], "case_ids": [], "pool_ids": [pool_id]},
            "case_pool_names": [pool.get("name") or pool_id],
            "total_cases": len(attributed),
            "incorrect_cases": "-",
            "cluster_count": "-",
            "ephemeral": True,
        })
    return {"summaries": summaries}

def import_case_pool(payload):
    pool_name = str(payload.get("pool_name") or payload.get("name") or payload.get("description") or "").strip()
    batch_id = safe_case_id(payload.get("import_batch_id") or pool_name or f"upload-{int(time.time())}", "upload")
    incoming = payload.get("cases") or []
    normalized = []
    skipped = 0
    for idx, item in enumerate(incoming):
        case = normalize_case_input(item, idx, batch_id, pool_name)
        if case:
            case["pool_scope"] = "custom"
            normalized.append(case)
        else:
            skipped += 1
    with CUSTOM_POOL_LOCK:
        master = load_cases_master()
        existing_ids = {case.get("case_id") for case in master.get("cases") or [] if case.get("case_id")}
        master_cases = list(master.get("cases") or [])
        imported = []
        for case in normalized:
            case_id = case.get("id")
            if case_id in existing_ids:
                suffix = hashlib.sha1((case.get("query", "") + batch_id).encode("utf-8")).hexdigest()[:6]
                case_id = safe_case_id(f"{case_id}-{suffix}")
                case["id"] = case_id
            record = canonical_case_record(case, case.get("source") or "user_upload", batch_id, source_label(case.get("source") or "user_upload"))
            if not record:
                continue
            existing_ids.add(record["case_id"])
            master_cases = upsert_by_key(master_cases, record, "case_id")
            imported.append({**case, "id": record["case_id"], "case_id": record["case_id"]})
        master["cases"] = master_cases
        save_cases_master(master)

        batches = load_case_batches()
        batch = {"batch_id": batch_id, "batch_type": "user_upload", "display_name": batch_id, "description": pool_name, "created_at": now_utc(), "deleted": False}
        batches["batches"] = upsert_by_key(batches.get("batches") or [], batch, "batch_id")
        existing_members = {(m.get("batch_id"), m.get("case_id")) for m in batches.get("memberships") or []}
        for case in imported:
            key = (batch_id, case.get("case_id") or case.get("id"))
            if key not in existing_members:
                batches.setdefault("memberships", []).append({"batch_id": key[0], "case_id": key[1]})
                existing_members.add(key)
        save_case_batches(batches)

        attrs = load_case_attributions()
        attr_items = attrs.get("items") or []
        for case in imported:
            attr_items = upsert_by_key(attr_items, {"case_id": case.get("id"), "attribution_status": "pending", "parser_result": None, "parser_error": "", "attribution_item": None, "updated_at": now_utc()}, "case_id")
        attrs["items"] = attr_items
        save_case_attributions(attrs)

    latest_batch = {"generated_at": now_utc(), "source": "user_upload", "import_batch_id": batch_id, "pool_name": pool_name, "cases": imported, "quality": {"passed": bool(imported), "missing": [] if imported else ["没有有效上传用例"]}, "llm_used": False}
    return {"imported": len(imported), "skipped": skipped, "imported_cases": imported, "case_pool": combined_case_pool(), "case_catalog": case_catalog_view(), "summary_catalog": summary_catalog_view(), "custom_case_pool": {"latest_batch": latest_batch, "cases": imported, "batches": [latest_batch]}}


def call_parser_api(query, base_url, timeout=8):
    url = base_url.rstrip("/") + "/api/v1/client_search_query_parse_no_encipher"
    body = json.dumps({
        "user_text": query,
        "user_id": "eval-user",
        "trace_id": f"upload-attribution-{int(time.time())}",
        "session_id": "upload-attribution-session",
        "source": "askbob",
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    attempts = [timeout]
    retry_timeout = max(float(timeout) * 3, 30.0)
    if retry_timeout > float(timeout):
        attempts.append(retry_timeout)
    last_exc = None
    for attempt_timeout in attempts:
        try:
            with urllib.request.urlopen(req, timeout=attempt_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            extra = ((data.get("data") or {}).get("extra_output_params") or {})
            return data, extra, (data.get("data") or {}).get("robot_text")
        except TimeoutError as exc:
            last_exc = exc
    raise last_exc


def condition_values(condition):
    value = condition.get("value")
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)] if value is not None else []


def strings_from_analysis(value):
    texts = []
    if isinstance(value, dict):
        texts.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    elif isinstance(value, list):
        for item in value:
            texts.extend(strings_from_analysis(item))
    elif value is not None:
        texts.append(str(value))
    return texts


def judge_diff_texts(judgement):
    texts = []
    expected = (judgement.get("expected") or {}).get("conditions") or []
    for key in ["missing_conditions", "wrong_conditions", "extra_conditions"]:
        texts.extend(strings_from_analysis(judgement.get(key) or []))
    texts.extend(strings_from_analysis(expected))
    return texts


def analyzer_semantic_texts(analysis):
    texts = []
    for key in [
        "expected_conditions",
        "actual_problem",
        "missing_conditions",
        "wrong_conditions",
        "extra_conditions",
        "impacted_fields",
        "suspected_files",
        "config_or_code_change_suggestion",
        "proposed_patch_plan",
        "llm_diagnosis_summary",
        "llm_diagnosis_detail",
    ]:
        texts.extend(strings_from_analysis(analysis.get(key)))
    return texts


def analyzer_value_texts(analysis):
    texts = []
    for key in [
        "expected_conditions",
        "actual_problem",
        "missing_conditions",
        "wrong_conditions",
        "extra_conditions",
        "config_or_code_change_suggestion",
        "proposed_patch_plan",
        "llm_diagnosis_summary",
        "llm_diagnosis_detail",
    ]:
        texts.extend(strings_from_analysis(analysis.get(key)))
    return texts


def analyzer_plan_texts(analysis):
    texts = []
    for key in [
        "expected_conditions",
        "actual_problem",
        "missing_conditions",
        "wrong_conditions",
        "extra_conditions",
        "config_or_code_change_suggestion",
        "proposed_patch_plan",
        "llm_diagnosis_summary",
    ]:
        texts.extend(strings_from_analysis(analysis.get(key)))
    return texts


def tokens_from_texts(texts):
    tokens = set()
    for text in texts:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.]{1,}|\d+(?:\.\d+)?|[一-鿿]{2,}", str(text)):
            tokens.add(token)
    return tokens


def condition_signature(condition):
    if not isinstance(condition, dict):
        return None
    return (
        str(condition.get("field")) if condition.get("field") is not None else None,
        str(condition.get("operator")) if condition.get("operator") is not None else None,
        str(condition.get("value")) if condition.get("value") is not None else None,
    )


def condition_signature_in_text(signature, text):
    if not signature:
        return False
    return all(part is None or part in text for part in signature)


def wrong_condition_is_recommended(signature, text, *, strict_field_only=False):
    if not signature:
        return False
    text = str(text or "")
    parts = [part for part in signature if part]
    if strict_field_only and parts:
        return parts[0] in text
    if not all(part in text for part in parts):
        return False
    field = signature[0] or ""
    correction_markers = ["删除", "移除", "修正", "改为", "替换", "不应", "禁止", "反例", "无关", "错误", "wrong", "actual", "实际"]
    if field:
        for marker in correction_markers:
            if re.search(rf"{marker}.{{0,80}}{re.escape(field)}|{re.escape(field)}.{{0,80}}{marker}", text):
                return False
    return True


def analyzer_uses_wrong_condition_as_solution(analysis, judgement):
    wrong_signatures = [condition_signature(item) for item in judgement.get("wrong_conditions") or []]
    wrong_signatures = [signature for signature in wrong_signatures if signature]
    if not wrong_signatures:
        return []
    violations = []
    expected_texts = strings_from_analysis(analysis.get("expected_conditions"))
    solution_texts = []
    for key in ["config_or_code_change_suggestion", "proposed_patch_plan"]:
        solution_texts.extend(strings_from_analysis(analysis.get(key)))
    for signature in wrong_signatures:
        for text in expected_texts:
            if wrong_condition_is_recommended(signature, text, strict_field_only=True):
                violations.append("analyzer 把 judge 已判错的 wrong condition 当作 expected: " + " ".join(part for part in signature if part))
                break
        for text in solution_texts:
            if wrong_condition_is_recommended(signature, text):
                violations.append("analyzer 把 judge 已判错的 wrong condition 当作修复建议: " + " ".join(part for part in signature if part))
                break
    return list(dict.fromkeys(violations))


def analyzer_contradicts_judge(analysis, judgement):
    analysis_blob = "\n".join(str(text) for text in analyzer_value_texts(analysis))
    contradictions = []
    no_problem_words = ["无实际异常", "无问题", "输出正常", "符合预期", "无需修复", "无需修改"]
    if any(word in analysis_blob for word in no_problem_words):
        contradictions.append("analyzer 判为无问题，但 judge 已判定 incorrect")
    for condition in judgement.get("wrong_conditions") or []:
        if not isinstance(condition, dict):
            continue
        field = condition.get("field")
        expected_value = condition.get("expected_value")
        actual_value = condition.get("actual_value")
        if expected_value not in (None, "") and actual_value not in (None, ""):
            expected_text = str(expected_value)
            actual_text = str(actual_value)
            if actual_text in analysis_blob and expected_text not in analysis_blob:
                label = field or "字段值"
                contradictions.append(f"analyzer 继续采用 judge 判错的 actual 值: {label}={actual_text}")
        issue = str(condition.get("issue") or condition.get("reason") or "")
        if "应为" in issue and field and field in analysis_blob:
            right_side = issue.split("应为", 1)[1]
            expected_field_match = re.search(r"([A-Za-z][A-Za-z0-9_.]{1,})", right_side)
            if expected_field_match and expected_field_match.group(1) not in analysis_blob:
                contradictions.append(f"analyzer 继续围绕 judge 判错字段归因: {field}")
    return list(dict.fromkeys(contradictions))


def check_analysis_against_judge(payload, analysis, judgement):
    if judgement.get("verdict") != "incorrect":
        return {"passed": True, "missing": []}
    missing = []
    query = payload.get("query") or ""
    allowed_texts = [query] + judge_diff_texts(judgement) + strings_from_analysis(payload.get("actual") or {})
    analysis_texts = analyzer_semantic_texts(analysis)
    query_hint_fields = set(hint_fields_from_query(query))
    judge_fields = set(condition_fields((judgement.get("expected") or {}).get("conditions") or []))
    for key in ["missing_conditions", "wrong_conditions", "extra_conditions"]:
        for item in judgement.get(key) or []:
            if isinstance(item, dict):
                field = item.get("field")
                if field:
                    judge_fields.add(field)
    allowed_fields = query_hint_fields | judge_fields | set(condition_fields((payload.get("actual") or {}).get("conditions") or []))
    analyzer_fields = set(analysis.get("impacted_fields") or [])
    analyzer_fields |= set(condition_fields(analysis.get("expected_conditions") or []))
    for item in analysis.get("suspected_files") or []:
        if isinstance(item, dict) and item.get("field"):
            analyzer_fields.add(item.get("field"))
    unrelated_fields = sorted(field for field in analyzer_fields if field and field not in allowed_fields)
    if unrelated_fields:
        missing.append("analyzer 含当前 query/actual 无关字段: " + ",".join(unrelated_fields[:6]))
    suspicious_terms = []
    for term in ["vipType", "VIP", "familyclientsex", "survivalbenefitdue"]:
        if any(term in text for text in analysis_texts) and not any(term in text for text in allowed_texts):
            suspicious_terms.append(term)
    if suspicious_terms:
        missing.append("analyzer 含历史/无关链路词: " + ",".join(suspicious_terms))
    if analysis.get("analysis_method") == "deterministic-chain-debug-fallback" and not analysis.get("deterministic_breakpoint_proof"):
        missing.append("deterministic fallback 缺少同 query 链路探针，不能作为 canonical 归因")
    missing.extend(analyzer_contradicts_judge(analysis, judgement))
    missing.extend(analyzer_uses_wrong_condition_as_solution(analysis, judgement))
    return {"passed": not missing, "missing": missing}


def resolve_suspected_file_lines(analysis):
    suspected = analysis.get("suspected_files") or []
    for item in suspected:
        if not isinstance(item, dict):
            continue
        line_range = str(item.get("line_range") or "").strip()
        if line_range and line_range.upper() != "N/A" and re.search(r"\d", line_range):
            continue
        path = item.get("file")
        full = PROJECT_ROOT / path if path else None
        if not full or not full.exists():
            continue
        symbol = str(item.get("symbol") or "").strip()
        reason = str(item.get("reason") or "").strip()
        candidates = []
        if symbol:
            candidates.append(symbol)
            candidates.extend(part for part in symbol.split(".") if len(part) >= 4)
            candidates.extend(
                token for token in re.findall(r"[A-Za-z][A-Za-z0-9_.]{3,}", symbol)
                if token.lower() not in {"yaml", "field", "fields", "definition", "definitions", "prompt", "condition", "conditions"}
            )
        candidates.extend(
            token for token in re.findall(r"[A-Za-z][A-Za-z0-9_.]{3,}", reason)
            if token.lower() not in {"yaml", "field", "fields", "definition", "definitions", "prompt", "condition", "conditions"}
        )
        candidates = [candidate for candidate in dict.fromkeys(candidates) if candidate]
        lines = full.read_text(encoding="utf-8", errors="ignore").splitlines()
        best_idx = None
        for candidate in sorted(candidates, key=len, reverse=True):
            for idx, line in enumerate(lines, 1):
                if candidate in line:
                    best_idx = idx
                    break
            if best_idx:
                break
        if best_idx:
            item["line_range"] = f"{max(1, best_idx - 3)}-{min(len(lines), best_idx + 3)}"
            item["line_evidence"] = f"matched {best_idx}: {lines[best_idx - 1].strip()[:120]}"
    return analysis


def apply_analysis_check_gate(payload, analysis, judgement):
    analysis = resolve_suspected_file_lines(analysis)
    base_quality = analysis_quality(analysis)
    check_quality = check_analysis_against_judge(payload, analysis, judgement)
    missing = list(dict.fromkeys((base_quality.get("missing") or []) + (check_quality.get("missing") or [])))
    quality = {
        **base_quality,
        "passed": not missing,
        "missing": missing,
        "check_gate": "judge-analyzer-consistency",
        "status": "pass" if not missing else "needs_work",
    }
    if missing:
        quality["reason"] = "；".join(missing)
    analysis["analysis_quality"] = quality
    return analysis


def attribution_item_from_analysis(case, parser_response, actual, robot_text, analysis, judgement):
    quality = analysis.get("analysis_quality") or {}
    passed = judgement.get("verdict") == "correct"
    quality_passed = quality.get("passed") is True
    cluster = analysis.get("root_cause_cluster") or semantic_cluster_id(analysis)
    title = analysis.get("root_cause_title") or analysis.get("llm_diagnosis_summary") or "上传用例归因问题"
    return {
        "id": case.get("id"),
        "query": case.get("query"),
        "verdict": judgement.get("verdict"),
        "review_verdict": judgement.get("review_verdict"),
        "review_title": f"{case.get('id')} - {judgement.get('review_verdict')}",
        "source": "user_upload",
        "import_batch_id": case.get("import_batch_id"),
        "pool_name": case.get("pool_name") or "",
        "actual": actual,
        "robot_text": robot_text,
        "parser_response": parser_response,
        "judge_result": judgement,
        "judge_method": judgement.get("judge_method"),
        "failure_category": judgement.get("failure_category") or ("无失败" if passed else (analysis.get("llm_owner_module") or "上传用例实时归因")),
        "failure_stage": judgement.get("failure_stage") or ("通过" if passed else (analysis.get("llm_owner_module") or "当前 API 输出")),
        "root_cause_cluster": "通过" if passed else cluster,
        "root_cause_title": "通过" if passed else title,
        "stale": judgement.get("verdict") == "incorrect" and not quality_passed,
        "currentness": "current" if is_valid_server_judge(judgement) and (passed or quality_passed) else "needs_work",
        "canonical_attribution": judgement.get("verdict") == "incorrect" and is_valid_server_judge(judgement) and quality_passed and bool(analysis.get("analysis_method")),
        "expected_conditions": (judgement.get("expected") or {}).get("conditions") or analysis.get("expected_conditions") or case.get("expected_conditions") or [],
        "missing_conditions": meaningful_problem_entries(judgement.get("missing_conditions") or analysis.get("missing_conditions") or []),
        "wrong_conditions": meaningful_problem_entries((judgement.get("wrong_conditions") or []) + (analysis.get("wrong_conditions") or []) + (analysis.get("actual_problem") or [])),
        "extra_conditions": meaningful_problem_entries(judgement.get("extra_conditions") or analysis.get("extra_conditions") or []),
        "evidence": judgement.get("evidence") or analysis.get("llm_diagnosis_detail") or analysis.get("llm_diagnosis_summary") or "上传用例实时归因结果",
        "debug_hint": judgement.get("debug_hint") or analysis.get("llm_diagnosis_detail") or "",
        "suggested_action": "；".join(analysis.get("config_or_code_change_suggestion") or analysis.get("proposed_patch_plan") or []),
        "fix_hint": "；".join(analysis.get("proposed_patch_plan") or []),
        "business_impact": analysis.get("business_impact") or "",
        "likely_root_cause": analysis.get("llm_diagnosis_summary") or "",
        "suspected_locations": analysis.get("suspected_files") or [],
        "impacted_fields": analysis.get("impacted_fields") or [],
        "analysis_quality": quality,
        "llm_analysis": analysis,
        "field_hints": hint_fields_from_query(case.get("query") or ""),
    }


SEMANTIC_CLUSTER_THEMES = [
    ("temporal", "时间窗口/日期语义", ["生日", "下月", "本月", "去年", "前年", "三年前", "近一个月", "未来", "日期", "时间", "月份", "退保", "购买过", "缴费期满"]),
    ("income_value", "收入/价值分层条件缺失", ["收入", "年收入", "中温", "保费", "vip", "VIP", "价值", "高价值", "名单"]),
    ("product_scope", "产品/险种作用域语义", ["百万医疗", "医疗", "财富", "产品", "购买", "未购买", "没有购买", "险", "理赔", "学平", "养老", "年金", "寿险"]),
]


MECHANISM_CLUSTER_PROFILES = {
    "temporal": {
        "mechanism": "时间窗口/日期语义解析机制不稳定",
        "root_cause": "簇内样本都涉及相对时间、日期窗口或时间字段选择；共同问题不是同一个字段缺失，而是 L2/L4/RAG/后处理对时间表达、时间字段和业务动作之间的映射不稳定，导致解析到错误字段、漏算时间窗口或拒绝生成支持条件。",
        "solution": "建立统一的时间语义解析与验证链路：补充相对时间到 RANGE 的标准转换；校准 field_definitions/RAG 中购买、退保、生日、缴费期满等时间字段的召回文本；增加 L2/L4/后处理断点测试，覆盖下月生日、三年前购买、近一个月退保等同机制样本。",
        "verification": ["相对时间表达能转换为明确 RANGE", "时间字段选择与业务动作一致", "L2/L4 输出进入后处理后不被错误清空或改写"],
    },
    "income_value": {
        "mechanism": "收入/价值分层数值条件召回机制不稳定",
        "root_cause": "簇内样本都涉及收入、保费、VIP/价值分层等数值或分层条件；共同问题是短数值表达、分层别名和金额字段召回没有统一口径，导致 L4/L2 漏召回或映射到不稳定字段。",
        "solution": "统一价值分层与金额类字段的召回口径：补齐收入/保费/VIP/价值标签的字段定义和别名映射；为短数值表达建立单位换算和比较符断点测试；确保 judge、attribute 和 summary 使用同一套金额字段语义。",
        "verification": ["短数值金额表达能稳定召回字段", "单位换算和比较符符合 prompt 规则", "价值分层别名不会落到无关字段"],
    },
    "product_scope": {
        "mechanism": "产品/险种作用域语义召回机制不稳定",
        "root_cause": "簇内样本都涉及产品、险种、购买/未购买或保障责任作用域；共同问题是产品词、险种词和保单/理赔/家庭成员等作用域没有稳定区分，导致 L2/L4 召回范围或字段作用域错误。",
        "solution": "统一产品/险种作用域解析：整理产品词、险种词、已购买/未购买/理赔等动作到字段的映射边界；补充增强规则和 RAG 字段描述中的作用域约束；增加同机制回归样本验证不会把产品条件落到无关保单或家庭成员字段。",
        "verification": ["产品词与险种词字段边界清晰", "购买/未购买/理赔动作映射到正确作用域", "同类产品 query 不再互相污染字段"],
    },
}


def semantic_cluster_theme(item):
    texts = [
        item.get("query"),
        item.get("evidence"),
        item.get("debug_hint"),
        item.get("likely_root_cause"),
        item.get("fix_hint"),
        item.get("suggested_action"),
        item.get("failure_category"),
        item.get("failure_stage"),
    ]
    text = " ".join(str(value or "") for value in texts)
    scores = []
    for theme_key, title, keywords in SEMANTIC_CLUSTER_THEMES:
        score = sum(1 for keyword in keywords if keyword in text)
        if score:
            scores.append((score, theme_key, title))
    if scores:
        _, theme_key, title = sorted(scores, reverse=True)[0]
        return theme_key, title
    fields = sorted({str(field).strip() for field in item.get("impacted_fields") or [] if str(field).strip()})
    if fields:
        return "fields_" + hashlib.sha1(",".join(fields).encode("utf-8")).hexdigest()[:8], "同字段归因问题"
    category = str(item.get("failure_category") or "未分类").strip() or "未分类"
    return "category_" + hashlib.sha1(category.encode("utf-8")).hexdigest()[:8], category


def semantic_cluster_key_for_item(item):
    theme_key, _ = semantic_cluster_theme(item)
    digest = hashlib.sha1(theme_key.encode("utf-8")).hexdigest()[:10]
    return f"CCK_{digest}"


def independent_cluster_merge_allowed(existing_items, item):
    if not existing_items:
        return True
    existing_theme, _ = semantic_cluster_theme(existing_items[0])
    item_theme, _ = semantic_cluster_theme(item)
    return existing_theme == item_theme


def correct_reference_rows_for_cluster(cluster_items, reference_items=None, limit=5):
    if not reference_items or not cluster_items:
        return [], {"total": 0, "shown": 0, "truncated": 0, "limit": limit, "reasons": {}}
    theme_key, _ = semantic_cluster_theme(cluster_items[0])
    cluster_fields = {field for item in cluster_items for field in (item.get("impacted_fields") or [])}
    existing_ids = {item.get("id") or item.get("case_id") for item in cluster_items if item.get("id") or item.get("case_id")}
    candidates = []
    reason_counts = {}
    for item in reference_items:
        case_id = item.get("id") or item.get("case_id")
        verdict = (item.get("judge_result") or {}).get("verdict") or item.get("verdict")
        if verdict != "correct" or not case_id or case_id in existing_ids:
            continue
        item_theme_key, _ = semantic_cluster_theme(item)
        item_fields = set(item.get("impacted_fields") or [])
        shared_fields = sorted(cluster_fields.intersection(item_fields)) if cluster_fields and item_fields else []
        same_theme = item_theme_key == theme_key
        if not shared_fields:
            continue
        reason = "shared_impacted_field"
        strength = "strong"
        row = compact_case_evidence(item)
        row["reference_role"] = "correct_reference"
        row["reference_reason"] = reason
        row["reference_strength"] = strength
        row["reference_note"] = f"共享影响字段：{'、'.join(shared_fields[:5])}"
        candidates.append(row)
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    candidates.sort(key=lambda row: (0 if row.get("reference_strength") == "strong" else 1, row.get("id") or ""))
    shown = candidates[:limit]
    return shown, {"total": len(candidates), "shown": len(shown), "truncated": max(0, len(candidates) - len(shown)), "limit": limit, "reasons": reason_counts}


def sample_rows_for_cluster(cluster_items, reference_items=None):
    rows = [compact_case_evidence(item) for item in cluster_items]
    reference_rows, _ = correct_reference_rows_for_cluster(cluster_items, reference_items)
    rows.extend(reference_rows)
    rows.sort(key=lambda row: 0 if (row.get("verdict") or (row.get("judge") or {}).get("verdict")) == "incorrect" else 1)
    return rows


def cluster_commonality(cluster_items, categories, stages, fields):
    theme_key, theme_title = semantic_cluster_theme(cluster_items[0])
    profile = MECHANISM_CLUSTER_PROFILES.get(theme_key)
    shared_fields = sorted([field for field, count in fields.items() if count == len(cluster_items)])
    location_counts = {}
    for item in cluster_items:
        seen = set()
        for loc in item.get("suspected_locations") or []:
            if isinstance(loc, dict):
                label = loc.get("file") or loc.get("target") or loc.get("function") or loc.get("path")
            else:
                label = str(loc or "")
            if label:
                seen.add(label)
        for label in seen:
            location_counts[label] = location_counts.get(label, 0) + 1
    shared_locations = sorted([label for label, count in location_counts.items() if count == len(cluster_items)])
    main_category = max(categories.items(), key=lambda kv: kv[1])[0] if categories else "未分类"
    main_stage = max(stages.items(), key=lambda kv: kv[1])[0] if stages else "不确定"
    stage_consistency = max(stages.values()) / len(cluster_items) if stages and cluster_items else 0
    category_consistency = max(categories.values()) / len(cluster_items) if categories and cluster_items else 0
    if profile:
        confidence = "mechanism"
        reason = "簇内样本共享同一机制主题，可用同一套归因逻辑和验证方式解释；字段/落点可以不同，但修复入口同属该机制。"
        summary = profile["mechanism"]
        root_cause = profile["root_cause"]
        solution = profile["solution"]
        verification = profile["verification"]
    else:
        confidence = "strong" if len(cluster_items) == 1 or shared_fields or shared_locations else "weak"
        summary_bits = [f"{main_stage}/{main_category}"]
        if shared_fields:
            summary_bits.append("共同字段：" + "、".join(shared_fields[:5]))
        if shared_locations:
            summary_bits.append("共同落点：" + "、".join(shared_locations[:3]))
        summary = "；".join(summary_bits)
        root_cause = summary
        solution = "需先复核/拆分该弱聚合组，再生成机制级修复建议。" if confidence == "weak" else "按共同字段/共同落点修复并增加对应回归断点测试。"
        verification = ["复核 expected vs actual", "确认共同字段/落点", "增加回归断点测试"]
        reason = "簇内样本存在稳定共同字段或共同疑似落点。" if confidence == "strong" else "簇内样本只共享粗粒度失败阶段/类型，缺少稳定机制主题、共同字段或共同落点；应优先复核是否需要拆分。"
    return {
        "confidence": confidence,
        "theme_key": theme_key,
        "theme_title": theme_title,
        "summary": summary,
        "root_cause": root_cause,
        "solution": solution,
        "verification": verification,
        "reason": reason,
        "shared_impacted_fields": shared_fields,
        "shared_locations": shared_locations,
        "dominant_stage": main_stage,
        "dominant_category": main_category,
        "stage_consistency": round(stage_consistency, 3),
        "category_consistency": round(category_consistency, 3),
    }


def build_cluster_entry(cluster_id, cluster_items, reference_items=None):
    first = cluster_items[0]
    categories = {}
    stages = {}
    fields = {}
    original_clusters = []
    legacy_clusters = []
    for item in cluster_items:
        categories[item.get("failure_category") or "未分类"] = categories.get(item.get("failure_category") or "未分类", 0) + 1
        stages[item.get("failure_stage") or "不确定"] = stages.get(item.get("failure_stage") or "不确定", 0) + 1
        original_cluster = item.get("original_root_cause_cluster") or item.get("root_cause_cluster")
        if original_cluster and original_cluster not in original_clusters:
            original_clusters.append(original_cluster)
        legacy_cluster = item.get("legacy_reference_cluster") or item.get("source_cluster_hint")
        if legacy_cluster and legacy_cluster not in legacy_clusters:
            legacy_clusters.append(legacy_cluster)
        for field in item.get("impacted_fields") or []:
            fields[field] = fields.get(field, 0) + 1
    count = len(cluster_items)
    impact = first.get("business_impact") or ""
    priority = "P0" if count >= 10 or any(word in impact for word in ["高价值", "最大", "直接", "危险"]) else "P1" if count >= 5 else "P2"
    _, theme_title = semantic_cluster_theme(first)
    all_cases = [compact_case_evidence(item) for item in cluster_items]
    correct_reference_rows, correct_reference_summary = correct_reference_rows_for_cluster(cluster_items, reference_items)
    case_table_rows = [*all_cases, *correct_reference_rows]
    commonality = cluster_commonality(cluster_items, categories, stages, fields)
    root_cause = commonality.get("root_cause") or "；".join(dict.fromkeys(item.get("likely_root_cause") or item.get("evidence") or "" for item in cluster_items if item.get("likely_root_cause") or item.get("evidence")))[:500]
    solution = commonality.get("solution") or "；".join(dict.fromkeys((item.get("fix_hint") or item.get("suggested_action") or "") for item in cluster_items if item.get("fix_hint") or item.get("suggested_action")))[:500]
    return {
        "id": cluster_id,
        "canonical_cluster_key": cluster_id,
        "source_root_cause_clusters": original_clusters,
        "legacy_reference_cluster": legacy_clusters[0] if legacy_clusters else "",
        "title": theme_title or semantic_title(first, original_clusters[0] if original_clusters else cluster_id),
        "priority": priority,
        "affected_count": count,
        "case_ids": [item.get("id") for item in cluster_items],
        "failure_categories": categories,
        "failure_stages": stages,
        "impacted_fields": [key for key, _ in sorted(fields.items(), key=lambda kv: kv[1], reverse=True)[:8]],
        "commonality": commonality,
        "root_cause": root_cause,
        "evidence_locations": [loc for item in cluster_items for loc in (item.get("suspected_locations") or [])][:5],
        "solution": solution,
        "business_impact": impact or "；".join(dict.fromkeys(item.get("business_impact") or "" for item in cluster_items if item.get("business_impact")))[:500],
        "representative_cases": all_cases[:6],
        "all_cases": all_cases,
        "case_table_rows": case_table_rows,
        "correct_reference_summary": correct_reference_summary,
    }


def semantic_cluster_entries(items, reference_items=None):
    groups = {}
    unclustered_items = []
    for item in items:
        original_cluster = item.get("root_cause_cluster")
        if invalid_cluster_label(original_cluster) or original_cluster == "通过":
            original_cluster = semantic_cluster_id(item.get("llm_analysis") or item)
        item["original_root_cause_cluster"] = original_cluster
        key = semantic_cluster_key_for_item(item)
        group = groups.get(key)
        if group is not None and not independent_cluster_merge_allowed(group, item):
            fallback_key = canonical_cluster_key(item)
            if fallback_key in groups and not independent_cluster_merge_allowed(groups[fallback_key], item):
                unclustered_items.append(item)
                continue
            key = fallback_key
        item["canonical_cluster_key"] = key
        groups.setdefault(key, []).append(item)
    cluster_entries = []
    split_candidates = []
    for cluster_id, cluster_items in groups.items():
        entry = build_cluster_entry(cluster_id, cluster_items, reference_items or items)
        if (entry.get("commonality") or {}).get("confidence") == "weak":
            split_candidates.extend(cluster_items)
        else:
            cluster_entries.append(entry)
    cluster_entries.sort(key=lambda c: ({"P0": 0, "P1": 1, "P2": 2}.get(c["priority"], 9), -c["affected_count"]))
    clustered_ids = {case_id for cluster in cluster_entries for case_id in cluster.get("case_ids") or [] if case_id}
    unclustered_source = [*unclustered_items, *split_candidates]
    unclustered = [{"id": item.get("id"), "query": item.get("query"), "failure_category": item.get("failure_category"), "failure_stage": item.get("failure_stage"), "problem": item.get("evidence") or item.get("debug_hint") or "", "expected": compact_case_evidence(item).get("expected"), "actual": compact_case_evidence(item).get("actual"), "suggested_action": item.get("suggested_action") or item.get("fix_hint") or "", "split_reason": "缺少机制级共性，作为待拆分问题样本单独展示" if item in split_candidates else "未能安全归并到正式问题簇"} for item in unclustered_source]
    return cluster_entries, unclustered, clustered_ids


def canonical_cluster_key(item):
    analysis = item.get("llm_analysis") or {}
    stage = str(item.get("failure_stage") or analysis.get("failure_stage") or "不确定").strip() or "不确定"
    category = str(item.get("failure_category") or analysis.get("failure_category") or "未分类").strip() or "未分类"
    fields = sorted({str(field).strip() for field in (item.get("impacted_fields") or analysis.get("impacted_fields") or []) if str(field).strip()})
    locations = []
    for loc in item.get("suspected_locations") or analysis.get("suspected_files") or []:
        if isinstance(loc, dict):
            label = str(loc.get("file") or loc.get("path") or loc.get("function") or "").strip()
        else:
            label = str(loc or "").strip()
        if label:
            locations.append(label)
    location_key = ",".join(sorted(set(locations))[:3])
    root_text = " ".join(str(value or "") for value in [
        item.get("likely_root_cause"),
        item.get("fix_hint") or item.get("suggested_action"),
        analysis.get("llm_diagnosis_summary"),
        analysis.get("fix_hint") or analysis.get("suggested_action"),
    ]).strip()
    root_tokens = sorted(tokens_from_texts([root_text]))[:8]
    parts = [stage, category, ",".join(fields[:6]), location_key, ",".join(root_tokens)]
    basis = "|".join(parts).strip("|") or str(item.get("root_cause_cluster") or semantic_cluster_id(analysis))
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
    return f"CCK_{digest}"


def invalid_cluster_label(value):
    text = str(value or "").strip().lower()
    return not text or any(word in text for word in ["user_upload", "match_agent", "realtime", "候选未归因", "live"])


def semantic_cluster_id(analysis):
    title = str(analysis.get("llm_diagnosis_summary") or analysis.get("llm_owner_module") or "custom_root_cause").strip()
    if invalid_cluster_label(title):
        title = "上传用例语义归因待修复问题"
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return f"USER_UPLOAD_{digest}"


def semantic_title(item, fallback):
    for key in ["root_cause_title", "likely_root_cause", "evidence"]:
        value = item.get(key)
        if value and not invalid_cluster_label(value):
            return value
    analysis = item.get("llm_analysis") or {}
    for key in ["llm_diagnosis_summary", "llm_owner_module"]:
        value = analysis.get(key)
        if value and not invalid_cluster_label(value):
            return value
    return fallback if not invalid_cluster_label(fallback) else "上传用例语义归因待修复问题"


def attribute_single_case(case_id, case, payload, base_url, parser_timeout):
    stage = "parser"
    try:
        parser_response, actual, robot_text = call_parser_api(case.get("query") or "", base_url, parser_timeout)
        stage = "judge"
        judgement = call_judge({
            "id": case_id,
            "query": case.get("query"),
            "actual": actual,
            "robot_text": robot_text,
            "parser_response": parser_response,
            "reference": {"expected_conditions": case.get("expected_conditions") or [], "source_cluster_hint": case.get("source_cluster_hint") or case.get("legacy_reference_cluster") or "", "cluster_binding": case.get("cluster_binding") or "reference_only"},
            "judge_model": payload.get("judge_model"),
            "analysis_model": payload.get("analysis_model"),
            "thinking_mode": payload.get("thinking_mode"),
        })
        judgement["case_id"] = case_id
        judgement["judge_source"] = "attribute_case_pool"
        analysis_payload = {
            "id": case_id,
            "query": case.get("query"),
            "actual": actual,
            "robot_text": robot_text,
        }
        if judgement.get("verdict") != "incorrect":
            analysis = analyze_after_judge(analysis_payload, judgement)
        else:
            stage = "attribute_analyzer"
            analysis = call_llm({
                **analysis_payload,
                "request": {"parser_base_url": base_url, "source": "canonical_case_pool"},
                "analysis_model": payload.get("analysis_model"),
                "thinking_mode": payload.get("thinking_mode"),
            }, judgement)
        stage = "build_item"
        item = attribution_item_from_analysis({**case, "id": case_id}, parser_response, actual, robot_text, analysis, judgement)
        item["case_id"] = case_id
        batch_ids = case.get("batch_ids") or []
        if batch_ids and not item.get("import_batch_id"):
            item["import_batch_id"] = batch_ids[0]
        return {
            "id": case_id,
            "ok": True,
            "stage": stage,
            "parser_response": parser_response,
            "judgement": judgement,
            "attribution_record": {
                "case_id": case_id,
                "attribution_status": "attributed",
                "parser_result": parser_response,
                "parser_error": "",
                "error_stage": "",
                "attribution_item": item,
                "updated_at": now_utc(),
            },
            "judgement_record": judgement,
            "attribution_item": item,
        }
    except Exception as exc:
        exc.attribution_stage = stage
        raise


def failed_attribution_record(case_id, stage, error):
    status_by_stage = {
        "parser": "parser_failed",
        "attribute_analyzer": "analysis_failed",
        "judge": "judge_failed",
        "build_item": "attribution_failed",
    }
    return {
        "case_id": case_id,
        "attribution_status": status_by_stage.get(stage, "attribution_failed"),
        "parser_result": None,
        "parser_error": str(error),
        "error_stage": stage,
        "attribution_item": None,
        "updated_at": now_utc(),
    }


def persist_attribution_results(results):
    with ATTRIBUTION_STORE_LOCK:
        attrs = load_case_attributions()
        attr_items = attrs.get("items") or []
        judgements = load_case_judgements()
        judgement_items = judgements.get("items") or []
        for result in results:
            record = result.get("attribution_record")
            if record:
                attr_items = upsert_by_key(attr_items, record, "case_id")
            judgement = result.get("judgement_record")
            if judgement:
                judgement_items = upsert_by_key(judgement_items, judgement, "case_id")
        attrs["items"] = attr_items
        save_case_attributions(attrs)
        judgements["items"] = judgement_items
        save_case_judgements(judgements)


def resolve_attribute_cases(payload):
    catalog = case_catalog_view()
    case_by_id = {case.get("case_id") or case.get("id"): case for case in catalog.get("cases") or []}
    selected_ids = list(dict.fromkeys(resolve_scope_case_ids(payload)))
    inline_cases = [normalize_case_input(item, idx) for idx, item in enumerate(payload.get("cases") or [])]
    with CUSTOM_POOL_LOCK:
        master = load_cases_master()
        master_cases = master.get("cases") or []
        for case in [case for case in inline_cases if case]:
            record = canonical_case_record(case, case.get("source") or "user_upload", case.get("import_batch_id") or "inline")
            if record:
                master_cases = upsert_by_key(master_cases, record, "case_id")
                case_by_id[record["case_id"]] = {**record, "id": record["case_id"], "case_id": record["case_id"]}
                if record["case_id"] not in selected_ids:
                    selected_ids.append(record["case_id"])
        master["cases"] = master_cases
        save_cases_master(master)
    return selected_ids, case_by_id


def attribute_case_pool(payload):
    selected_ids, case_by_id = resolve_attribute_cases(payload)
    base_url = payload.get("parser_base_url") or "http://localhost:8000"
    parser_timeout = float(payload.get("parser_timeout") or 8)
    results = []
    persistable = []
    for case_id in selected_ids:
        case = case_by_id.get(case_id)
        if not case:
            result = {"id": case_id, "ok": False, "error": "case id not found in canonical case pool"}
            results.append(result)
            continue
        try:
            result = attribute_single_case(case_id, case, payload, base_url, parser_timeout)
            results.append({"id": case_id, "ok": True, "attribution_item": result.get("attribution_item")})
            persistable.append(result)
        except Exception as exc:
            stage = getattr(exc, "attribution_stage", "unknown")
            error_result = {"id": case_id, "ok": False, "stage": stage, "error": str(exc), "attribution_record": failed_attribution_record(case_id, stage, exc)}
            results.append({"id": case_id, "ok": False, "stage": stage, "error": str(exc)})
            persistable.append(error_result)
    persist_attribution_results(persistable)
    attributed = sum(1 for result in results if result.get("ok") is True)
    failed = sum(1 for result in results if result.get("ok") is False)
    return {"attributed": attributed, "failed": failed, "results": results, "case_pool": combined_case_pool(), "case_catalog": case_catalog_view(), "summary_catalog": summary_catalog_view(), "custom_case_pool": combined_case_pool()}


def compact_case_evidence(item):
    judge = item.get("judge_result") or {}
    analysis = item.get("llm_analysis") or {}
    actual = item.get("actual") or ((item.get("parser_response") or {}).get("data") or {}).get("extra_output_params") or {}
    expected = item.get("expected") or judge.get("expected") or {"conditions": item.get("expected_conditions") or []}
    problem_parts = []
    for label, values in [("缺失", judge.get("missing_conditions") or item.get("missing_conditions") or []), ("错误", judge.get("wrong_conditions") or item.get("wrong_conditions") or []), ("多余", judge.get("extra_conditions") or item.get("extra_conditions") or [])]:
        if values:
            problem_parts.append(f"{label}: {json.dumps(values, ensure_ascii=False)}")
    problem = item.get("evidence") or judge.get("evidence") or item.get("debug_hint") or analysis.get("llm_diagnosis_summary") or "；".join(problem_parts) or ""
    verdict = judge.get("verdict") or item.get("verdict")
    quality = analysis.get("analysis_quality") or item.get("analysis_quality") or {}
    return {
        "id": item.get("id") or item.get("case_id"),
        "query": item.get("query"),
        "verdict": verdict,
        "review_verdict": judge.get("review_verdict") or item.get("review_verdict"),
        "quality_passed": quality.get("passed") if isinstance(quality, dict) else None,
        "expected": expected,
        "problem": problem,
        "actual": {
            "query_logic": actual.get("query_logic"),
            "conditions": actual.get("conditions") or [],
            "matched_level": actual.get("matched_level"),
            "intent_summary": actual.get("intent_summary"),
        },
        "judge": {
            "verdict": judge.get("verdict") or item.get("verdict"),
            "review_verdict": judge.get("review_verdict") or item.get("review_verdict"),
            "expected": expected,
            "missing_conditions": judge.get("missing_conditions") or item.get("missing_conditions") or [],
            "wrong_conditions": judge.get("wrong_conditions") or item.get("wrong_conditions") or [],
            "extra_conditions": judge.get("extra_conditions") or item.get("extra_conditions") or [],
            "evidence": judge.get("evidence") or item.get("evidence") or "",
            "method": judge.get("judge_method") or item.get("judge_method") or "",
        },
        "attribution": {
            "summary": analysis.get("llm_diagnosis_summary") or item.get("likely_root_cause") or "",
            "evidence_chain": analysis.get("evidence_chain") or [],
            "suspected_locations": analysis.get("suspected_files") or item.get("suspected_locations") or [],
            "fix_hint": item.get("fix_hint") or item.get("suggested_action") or "",
            "method": analysis.get("analysis_method") or item.get("analysis_method") or "",
            "quality": quality,
        },
    }


def build_summary_from_items(items, generated_by, source_total=None):
    all_incorrect = [item for item in items if item.get("verdict") == "incorrect"]
    incorrect = quality_filtered_items(items)
    excluded_reasons = noncanonical_attribution_reasons(items)
    needs_review = needs_review_case_rows(items)
    cluster_entries, unclustered, clustered_ids = semantic_cluster_entries(incorrect, items)
    return {
        "generated_at": now_utc(),
        "generated_by": generated_by,
        "llm_used": False,
        "totals": {"total_cases": len(items), "source_total_cases": source_total or len(items), "incorrect_cases": len(incorrect), "source_incorrect_cases": len(all_incorrect), "excluded_noncanonical_cases": sum(excluded_reasons.values()), "clustered_cases": len(clustered_ids), "unclustered_cases": len(unclustered), "cluster_count": len(cluster_entries)},
        "by_failure_category": {k: sum(1 for item in items if (item.get("failure_category") or "未分类") == k) for k in set(item.get("failure_category") or "未分类" for item in items)},
        "by_failure_stage": {k: sum(1 for item in items if (item.get("failure_stage") or "不确定") == k) for k in set(item.get("failure_stage") or "不确定" for item in items)},
        "top_priorities": [{"id": c["id"], "title": c["title"], "affected_count": c["affected_count"], "priority": c["priority"], "solution": c["solution"]} for c in cluster_entries[:5]],
        "clusters": cluster_entries,
        "unclustered_cases": unclustered,
        "needs_review_cases": needs_review,
        "agent_flow": "parser -> judge -> incorrect -> attribute-analyzer -> check gate -> independent semantic recluster",
        "cluster_merge_gate": "独立聚簇由当前 query、failure_stage/failure_category、impacted_fields、likely_root_cause、fix_hint、suspected_locations 的语义主题生成 canonical_cluster_key；source_cluster_hint、legacy_reference_cluster 和历史 root_cause_clusters 仅作展示/覆盖参考，不参与正式分组。",
        "quality": {"passed": not excluded_reasons, "excluded_noncanonical_reasons": excluded_reasons, "canonical_filter": "server-side judge 判定不通过 + 归因质量通过 + analysis_method 当前有效 + 非 reference-only/非 stale/非 fallback/非需重跑", "note": "按已归因基础用例和上传用例独立语义重聚簇；总不通过=judge 判定 parser 输出不正确的数量；进入正式聚簇=这些不通过里归因也通过质量门、可放进默认总结的数量；需复核=parser 已判不正确，但归因结果过期、需重跑或质量不够，暂不放进正式总结。"},
    }


def build_summary_from_custom_cases(payload):
    case_ids = resolve_scope_case_ids(payload)
    items = attributed_items_for_case_ids(case_ids)
    source_total = len(case_ids)
    summary = build_summary_from_items(items, "llm_attribution_server canonical case summarizer", source_total)
    catalog = case_catalog_view()
    case_by_id = {case.get("case_id"): case for case in catalog.get("cases") or []}
    scoped_cases = [case_by_id.get(case_id) for case_id in case_ids if case_by_id.get(case_id)]
    batch_ids = []
    for case in scoped_cases:
        for batch_id in case.get("batch_ids") or []:
            if batch_id not in batch_ids:
                batch_ids.append(batch_id)
    pool_ids = []
    for case in scoped_cases:
        for pool_id in case.get("pool_ids") or []:
            if pool_id not in pool_ids:
                pool_ids.append(pool_id)
    source = "default_selected" if scoped_cases and all(case.get("origin_type") == "default" for case in scoped_cases) else "custom"
    summary["source"] = source
    summary["case_ids"] = [item.get("id") for item in items if item.get("id")]
    summary["case_scope"] = {"case_ids": case_ids, "batch_ids": payload.get("batch_ids") or batch_ids, "pool_ids": payload.get("pool_ids") or pool_ids}
    summary["case_pool_names"] = unique_case_pool_names(items)
    summary["import_batch_ids"] = unique_import_batch_ids(items) or batch_ids
    summary["name"] = canonical_summary_name(summary, source)
    summary["display_name"] = summary["name"]
    summary["source_files"] = ["attribution_store/cases_master.json", "attribution_store/case_attributions.json", "attribution_store/case_judgements.json"]
    if payload.get("save_summary"):
        explicit_name = payload.get("summary_name") if payload.get("explicit_summary_name") else None
        summary = save_attribution_summary(summary, explicit_name, source)
    return summary


def ensure_attribution_summaries_dir():
    ATTRIBUTION_SUMMARIES_DIR.mkdir(exist_ok=True)


def load_summary_index():
    ensure_attribution_summaries_dir()
    if not ATTRIBUTION_SUMMARY_INDEX_PATH.exists():
        return {"summaries": []}
    try:
        data = json.loads(ATTRIBUTION_SUMMARY_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"summaries": []}
    return {"summaries": data.get("summaries") or []}


def write_summary_index(index):
    ensure_attribution_summaries_dir()
    ATTRIBUTION_SUMMARY_INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def summary_filename_id(name, case_ids):
    created = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    digest = hashlib.sha1(json.dumps({"name": name, "case_ids": case_ids, "created": created}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    return f"summary-{created}-{digest}"


def markdown_for_summary(summary):
    totals = summary.get("totals") or {}
    lines = [
        f"# 归因聚簇结果：{summary.get('name') or summary.get('summary_id')}",
        "",
        "## 基本信息",
        f"- Summary ID: {summary.get('summary_id')}",
        f"- 创建时间: {summary.get('created_at')}",
        f"- 数据来源: {summary.get('source') or '-'}",
        f"- 用例集: {', '.join(summary.get('case_pool_names') or []) or '-'}",
        f"- 来源文件: {', '.join(summary.get('source_files') or []) or '-'}",
        f"- 用例数量: {totals.get('total_cases', 0)}",
        f"- 不通过数量: {totals.get('incorrect_cases', 0)}",
        f"- 聚簇数量: {totals.get('cluster_count', 0)}",
        f"- 未聚簇数量: {totals.get('unclustered_cases', 0)}",
        "",
        "## 聚簇总览",
        "| 聚簇 | 影响用例数 | 根因 | 建议修复 |",
        "| --- | ---: | --- | --- |",
    ]
    for cluster in summary.get("clusters") or []:
        root = str(cluster.get("root_cause") or "-").replace("|", "\\|").replace("\n", " ")
        solution = str(cluster.get("solution") or "-").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {cluster.get('id')} {cluster.get('title') or ''} | {cluster.get('affected_count') or 0} | {root} | {solution} |")
    lines.extend(["", "## 聚簇详情"])
    for cluster in summary.get("clusters") or []:
        lines.extend([
            "",
            f"### {cluster.get('id')}：{cluster.get('title') or ''}",
            f"- 优先级: {cluster.get('priority') or '-'}",
            f"- 影响用例: {', '.join(cluster.get('case_ids') or []) or '-'}",
            f"- 影响字段: {', '.join(cluster.get('impacted_fields') or []) or '-'}",
            f"- 根因: {cluster.get('root_cause') or '-'}",
            f"- 业务影响: {cluster.get('business_impact') or '-'}",
            f"- 修复建议: {cluster.get('solution') or '-'}",
        ])
    lines.extend(["", "## 未聚簇 / 需复核"])
    unclustered = summary.get("unclustered_cases") or []
    if not unclustered:
        lines.append("无。")
    else:
        for item in unclustered:
            lines.append(f"- {item.get('id')}: {item.get('query') or ''} — {item.get('problem') or item.get('suggested_action') or ''}")
    lines.append("")
    return "\n".join(lines)


def save_attribution_summary(summary, name=None, source=None):
    ensure_attribution_summaries_dir()
    ensure_attribution_store_dir()
    case_ids = summary.get("case_ids") or [case_id for cluster in summary.get("clusters") or [] for case_id in (cluster.get("case_ids") or [])]
    totals = summary.get("totals") or {}
    default_name = canonical_summary_name(summary, source)
    raw_name = str(name or "").strip()
    name = raw_name if raw_name and not generated_summary_name(raw_name) else default_name
    summary_id = summary_filename_id(name, case_ids)
    json_path = ATTRIBUTION_SUMMARIES_DIR / f"{summary_id}.json"
    md_path = ATTRIBUTION_SUMMARIES_DIR / f"{summary_id}.md"
    store_json_path = SUMMARY_STORE_DIR / f"{summary_id}.json"
    case_scope = summary.get("case_scope") or {"case_ids": case_ids, "batch_ids": summary.get("import_batch_ids") or [], "pool_ids": []}
    saved = {
        **summary,
        "summary_id": summary_id,
        "summary_schema_version": "canonical-currentness-v1",
        "currentness": "current",
        "summary_currentness": "current",
        "name": name,
        "display_name": name,
        "created_at": now_utc(),
        "source": source or summary.get("source") or "custom",
        "case_ids": case_ids,
        "case_scope": case_scope,
        "saved": True,
        "json_path": str(json_path.relative_to(ROOT)),
        "md_path": str(md_path.relative_to(ROOT)),
    }
    json_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    store_json_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_for_summary(saved), encoding="utf-8")
    ATTRIBUTION_SUMMARY_LATEST_PATH.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    totals = saved.get("totals") or {}
    entry = {
        "summary_id": summary_id,
        "name": name,
        "display_name": name,
        "created_at": saved.get("created_at"),
        "source": saved.get("source"),
        "summary_schema_version": saved.get("summary_schema_version"),
        "currentness": saved.get("currentness"),
        "summary_currentness": saved.get("summary_currentness"),
        "quality": saved.get("quality") or {},
        "case_scope": case_scope,
        "case_pool_names": saved.get("case_pool_names") or [],
        "import_batch_ids": saved.get("import_batch_ids") or [],
        "total_cases": totals.get("total_cases"),
        "incorrect_cases": totals.get("incorrect_cases"),
        "cluster_count": totals.get("cluster_count"),
        "json_path": str(json_path.relative_to(ROOT)),
        "md_path": str(md_path.relative_to(ROOT)),
    }
    index = load_summary_index()
    index["summaries"] = [entry] + [item for item in index.get("summaries") or [] if item.get("summary_id") != summary_id]
    write_summary_index(index)
    store_index = load_summary_store_index()
    store_index["summaries"] = [entry] + [item for item in store_index.get("summaries") or [] if item.get("summary_id") != summary_id]
    save_summary_store_index(store_index)
    return saved


def summary_currentness(summary):
    if not isinstance(summary, dict):
        return "reference_only"
    if summary.get("ephemeral"):
        return "current"
    quality = summary.get("quality") or {}
    totals = summary.get("totals") or {}
    if quality.get("canonical_filter") and "source_incorrect_cases" in totals and "excluded_noncanonical_cases" in totals:
        return "current"
    scope = summary.get("case_scope") or {}
    if scope.get("case_ids") or scope.get("batch_ids") or scope.get("pool_ids") or summary.get("case_ids") or summary.get("import_batch_ids"):
        return "needs_rerun"
    return "reference_only"


def annotate_summary_currentness(summary):
    if not isinstance(summary, dict):
        return summary
    annotated = dict(summary)
    state = summary_currentness(annotated)
    annotated["currentness"] = state
    annotated["summary_currentness"] = state
    if state == "current":
        annotated.setdefault("summary_schema_version", "canonical-currentness-v1")
        return annotated
    quality = dict(annotated.get("quality") or {})
    quality["passed"] = False
    quality.setdefault("excluded_noncanonical_reasons", {state: (annotated.get("totals") or {}).get("incorrect_cases") or annotated.get("incorrect_cases") or 0})
    quality["canonical_filter"] = "历史保存报告缺少当前 canonical/currentness 元数据；需按当前质量门重建后才能作为正式聚簇。"
    quality["note"] = ("该报告为历史保存结果，当前仅作参考；请用后端统一 scope 即时构建或重新保存，生成包含 source-vs-canonical 计数和排除原因的新报告。 " + str(quality.get("note") or "")).strip()
    annotated["quality"] = quality
    return annotated


def normalize_summary_index_entry(entry):
    if not isinstance(entry, dict):
        return entry
    normalized = dict(entry)
    summary = None
    json_path = normalized.get("json_path")
    if json_path:
        path = ROOT / json_path
        if path.exists():
            try:
                summary = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                summary = None
    source = normalized.get("source") or (summary or {}).get("source")
    basis = dict(summary or normalized)
    canonical = canonical_summary_name(basis, source)
    normalized["name"] = canonical
    normalized["display_name"] = canonical
    annotated = annotate_summary_currentness(summary or normalized)
    normalized["currentness"] = annotated.get("currentness")
    normalized["summary_currentness"] = annotated.get("summary_currentness")
    if annotated.get("quality"):
        normalized["quality"] = annotated.get("quality")
    return normalized


def list_attribution_summaries():
    return [normalize_summary_index_entry(item) for item in summary_catalog_view().get("summaries") or []]


def load_attribution_summary(summary_id):
    safe_id = re.sub(r"[^0-9A-Za-z_:\-]+", "-", str(summary_id or "")).strip("-")
    if not safe_id:
        raise RuntimeError("missing summary_id")
    if str(summary_id).startswith("__ephemeral__:batch:"):
        batch_id = str(summary_id).split(":", 2)[-1]
        return build_summary_from_custom_cases({"batch_ids": [batch_id]})
    if str(summary_id).startswith("__ephemeral__:pool:"):
        pool_id = str(summary_id).split(":", 2)[-1]
        return build_summary_from_custom_cases({"pool_ids": [pool_id]})
    store_path = SUMMARY_STORE_DIR / f"{safe_id}.json"
    if store_path.exists():
        return annotate_summary_currentness(json.loads(store_path.read_text(encoding="utf-8")))
    path = ATTRIBUTION_SUMMARIES_DIR / f"{safe_id}.json"
    if not path.exists():
        raise RuntimeError(f"找不到聚簇报告：{summary_id}")
    return annotate_summary_currentness(json.loads(path.read_text(encoding="utf-8")))


def build_case_pool_prompt(summary, requested_count, user_prompt=""):
    compact_clusters = []
    for cluster in (summary.get("clusters") or [])[:10]:
        compact_clusters.append({
            "id": cluster.get("id"),
            "title": cluster.get("title"),
            "root_cause": cluster.get("root_cause"),
            "solution": cluster.get("solution"),
            "impacted_fields": cluster.get("impacted_fields"),
            "representative_cases": cluster.get("representative_cases"),
        })
    return f"""你是客户搜索 eval 的用例池构建助手。请根据已有失败归因簇，补充能验证这些问题是否修好的自然语言 query 用例。

硬性要求：
- 只输出 JSON，不要 markdown。
- 生成 {requested_count} 条以内 candidate cases。
- query 要像真实业务用户表达，覆盖短 query、多条件组合、枚举归一化、家庭成员、日期语义、字段语义等不同问题簇。
- 每条必须写 source_cluster_hint、cluster_binding、expected_intent、expected_conditions、reason。
- source_cluster_hint 只表示这条候选用例想覆盖哪个已有归因簇；cluster_binding 必须固定为 reference_only，不能把输入用例的 hint 当成正式 root_cause_cluster。
- expected_conditions 用可读文本即可，不要求完全等于 API 字段格式。
- 不要修改业务代码；这些 case 只是后续批量跑 API、judge 和归因的输入候选，正式聚簇必须由后续运行结果生成。
- 如果用户补充了构建要求，必须优先满足；但不能生成与客户搜索无关的 query。

用户补充的构建要求：
{user_prompt or "未提供，按默认覆盖面补充。"}

JSON schema:
{{
  "cases": [
    {{
      "id": "generated-C01-001",
      "query": "自然语言查询",
      "source_cluster_hint": "想覆盖的已有问题簇 ID，仅作参考",
      "cluster_binding": "reference_only",
      "expected_intent": "核心搜索意图",
      "expected_conditions": ["字段/操作符/值/逻辑关系的可读期望"],
      "reason": "为什么这条能覆盖该归因问题"
    }}
  ],
  "quality": {{"passed": true, "missing": []}}
}}

已有归因簇：
{json.dumps(compact_clusters, ensure_ascii=False, indent=2)}
"""


def load_chain_probe_results():
    if not CHAIN_PROBE_PATH.exists():
        return {"total": 0, "by_failed_stage": {}, "items": []}
    return json.loads(CHAIN_PROBE_PATH.read_text(encoding="utf-8"))


def load_saved_case_pool():
    if not CASE_POOL_PATH.exists():
        return {
            "generated_at": None,
            "generated_by": "llm_attribution_server default case pool",
            "source": "default_case_pool",
            "source_clusters": [],
            "cases": [],
            "quality": {"passed": True, "missing": []},
            "llm_used": False,
        }
    return json.loads(CASE_POOL_PATH.read_text(encoding="utf-8"))


def empty_custom_case_pool():
    return {
        "generated_at": None,
        "generated_by": "llm_attribution_server custom upload case pool",
        "source": "custom_upload_case_pool",
        "source_clusters": [],
        "cases": [],
        "quality": {"passed": True, "missing": []},
        "llm_used": False,
        "batches": [],
    }


def combined_case_pool():
    catalog = case_catalog_view()
    cases = catalog.get("cases") or []
    default_cases = [case for case in cases if case.get("origin_type") == "default"]
    custom_cases = [case for case in cases if case.get("origin_type") != "default"]
    latest_batch = None
    batches = catalog.get("batches") or []
    if batches:
        latest = sorted(batches, key=lambda item: str(item.get("created_at") or item.get("batch_id") or ""), reverse=True)[0]
        latest_cases = [case for case in cases if latest.get("batch_id") in (case.get("batch_ids") or [])]
        latest_batch = {"generated_at": latest.get("created_at"), "source": latest.get("batch_type"), "import_batch_id": latest.get("batch_id"), "pool_name": latest.get("description") or "", "cases": latest_cases, "quality": {"passed": True, "missing": []}, "llm_used": False}
    return {
        "generated_at": now_utc(),
        "generated_by": "llm_attribution_server canonical case pool",
        "source": "canonical_case_pool",
        "source_clusters": [],
        "cases": cases,
        "default_case_count": len(default_cases),
        "custom_case_count": len(custom_cases),
        "quality": {"passed": True, "missing": []},
        "llm_used": False,
        "latest_batch": latest_batch,
        "custom_batches": batches,
    }


def save_case_pool(pool):
    existing = load_saved_case_pool()
    merged = {case.get("id"): case for case in existing.get("cases") or [] if case.get("id")}
    for case in pool.get("cases") or []:
        case_id = case.get("id") or f"generated-{int(time.time())}-{len(merged) + 1}"
        case = {**case, "id": case_id}
        merged[case_id] = case
    saved = {
        "generated_at": now_utc(),
        "generated_by": "llm_attribution_server saved case pool",
        "source": "saved_case_pool",
        "source_clusters": sorted(set((existing.get("source_clusters") or []) + (pool.get("source_clusters") or []))),
        "cases": list(merged.values()),
        "quality": {"passed": True, "missing": []},
        "llm_used": bool(existing.get("llm_used") or pool.get("llm_used")),
        "latest_batch": pool,
    }
    CASE_POOL_PATH.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return saved


def load_case_pool_library():
    store = load_named_pools_store()
    catalog_cases = {case.get("case_id"): case for case in case_catalog_view().get("cases") or []}
    active_memberships = active_pool_memberships(store)
    pools = []
    for pool in store.get("pools") or []:
        if pool.get("deleted"):
            continue
        pool_id = pool.get("pool_id") or pool.get("id")
        case_ids = [member.get("case_id") for member in active_memberships if member.get("pool_id") == pool_id]
        cases = [catalog_cases.get(case_id) for case_id in case_ids if catalog_cases.get(case_id)]
        pools.append({**pool, "id": pool_id, "pool_id": pool_id, "case_count": len(cases), "cases": cases})
    return {"pools": pools}


def job_path(job_id):
    ATTRIBUTION_JOBS_DIR.mkdir(exist_ok=True)
    safe_id = re.sub(r"[^0-9A-Za-z_\-]+", "-", str(job_id or "")).strip("-")
    if not safe_id:
        raise RuntimeError("missing job_id")
    return ATTRIBUTION_JOBS_DIR / f"{safe_id}.json"


def write_job(job):
    path = job_path(job.get("job_id"))
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    write_task_state_for_job(job)
    return job


def load_job(job_id):
    path = job_path(job_id)
    if not path.exists():
        raise RuntimeError(f"找不到归因任务：{job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def empty_task_state():
    return {"active_job_id": None, "last_job_id": None, "updated_at": None, "jobs": {}}


def load_task_state():
    if not ATTRIBUTION_TASK_STATE_PATH.exists():
        return empty_task_state()
    try:
        state = json.loads(ATTRIBUTION_TASK_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return empty_task_state()
    base = empty_task_state()
    base.update(state)
    base["jobs"] = state.get("jobs") or {}
    return base


def compact_task_state_jobs(state):
    jobs = state.get("jobs") or {}
    ordered = sorted(
        jobs.values(),
        key=lambda item: str(item.get("created_at") or item.get("job_id") or ""),
        reverse=True,
    )
    state["jobs"] = {item.get("job_id"): item for item in ordered[:ATTRIBUTION_TASK_STATE_MAX_JOBS] if item.get("job_id")}
    if state.get("active_job_id") and state.get("active_job_id") not in state["jobs"]:
        state["active_job_id"] = None
    if state.get("last_job_id") and state.get("last_job_id") not in state["jobs"]:
        state["last_job_id"] = ordered[0].get("job_id") if ordered else None
    return state


def task_summary_is_active(summary):
    return bool(summary and (summary.get("status") in {"queued", "running"} or summary.get("running")))


def job_summary(job):
    case_ids = (job.get("payload") or {}).get("case_ids") or []
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "running": bool(job.get("running")),
        "total": job.get("total") or len(case_ids),
        "done": job.get("done") or 0,
        "attributed": job.get("attributed") or 0,
        "failed": job.get("failed") or 0,
        "current_id": job.get("current_id"),
        "current_index": job.get("current_index") or 0,
        "case_ids": case_ids,
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "updated_at": now_utc(),
        "finished_at": job.get("finished_at"),
        "logs": (job.get("logs") or [])[-20:],
        "concurrency": job.get("concurrency") or (job.get("payload") or {}).get("concurrency") or (job.get("payload") or {}).get("max_workers"),
    }


def write_task_state_for_job(job):
    state = load_task_state()
    summary = job_summary(job)
    job_id = summary.get("job_id")
    if not job_id:
        return state
    state["jobs"][job_id] = summary
    state["last_job_id"] = job_id
    if task_summary_is_active(summary):
        state["active_job_id"] = job_id
    elif state.get("active_job_id") == job_id:
        state["active_job_id"] = None
    state["updated_at"] = now_utc()
    state = compact_task_state_jobs(state)
    ATTRIBUTION_TASK_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def current_active_attribute_job():
    state = load_task_state()
    active_id = state.get("active_job_id")
    if active_id:
        try:
            active_job = attribute_job_status(active_id)
            if active_job.get("status") in {"queued", "running"} or active_job.get("running"):
                return active_job
            write_task_state_for_job(active_job)
        except Exception:
            pass
    latest = latest_attribute_job()
    if latest and (latest.get("status") in {"queued", "running"} or latest.get("running")):
        write_task_state_for_job(latest)
        return latest
    return None


def attribute_task_state():
    state = load_task_state()
    active_job = None
    last_job = None
    active_id = state.get("active_job_id")
    last_id = state.get("last_job_id")
    if active_id:
        try:
            active_job = attribute_job_status(active_id)
            write_task_state_for_job(active_job)
        except Exception:
            active_job = None
    if last_id:
        try:
            last_job = attribute_job_status(last_id)
            write_task_state_for_job(last_job)
        except Exception:
            last_job = None
    if not active_job and not last_job:
        latest = latest_attribute_job()
        if latest:
            write_task_state_for_job(latest)
            if latest.get("status") in {"queued", "running"} or latest.get("running"):
                active_job = latest
            last_job = latest
    state = load_task_state()
    return {
        "state": state,
        "active_job": job_summary(active_job) if active_job else None,
        "last_job": job_summary(last_job) if last_job else None,
    }


def list_attribute_jobs():
    ATTRIBUTION_JOBS_DIR.mkdir(exist_ok=True)
    jobs = []
    for path in ATTRIBUTION_JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            job["_mtime"] = path.stat().st_mtime
            jobs.append(job)
        except Exception:
            continue
    jobs.sort(key=lambda job: str(job.get("created_at") or job.get("job_id") or ""), reverse=True)
    return jobs


def latest_attribute_job():
    jobs = list_attribute_jobs()
    live_jobs = [job for job in jobs if (job.get("status") in {"queued", "running"} or job.get("running")) and not job.get("finished_at")]
    for job in live_jobs:
        fresh = attribute_job_status(job.get("job_id"))
        stale_after = max(600, int(fresh.get("total") or 1) * 180)
        if time.time() - float(fresh.get("_mtime") or 0) <= stale_after:
            return fresh
        fresh.update({"status": "failed", "running": False, "finished_at": now_utc(), "error": "后台任务长时间未更新，已标记为失败"})
        append_job_log(fresh, "后台任务长时间未更新，已标记为失败；可重新启动归因")
        write_job(fresh)
    jobs = list_attribute_jobs()
    return attribute_job_status(jobs[0].get("job_id")) if jobs else None


def append_job_log(job, line):
    logs = job.setdefault("logs", [])
    logs.append(f"{now_utc()} {line}")
    job["logs"] = logs[-200:]


def attribute_job_concurrency(payload, total):
    raw = payload.get("concurrency") or payload.get("max_workers") or 3
    try:
        value = int(raw)
    except Exception:
        value = 3
    return max(1, min(value, 6, max(1, int(total or 1))))


def compact_job_result(result):
    if result.get("ok") is True:
        return {"id": result.get("id"), "ok": True, "attribution_item": result.get("attribution_item")}
    compact = {"id": result.get("id"), "ok": False, "stage": result.get("stage"), "error": result.get("error")}
    return {key: value for key, value in compact.items() if value not in (None, "")}


def mark_job_cancelled(job, message):
    job.update({"status": "cancelled", "running": False, "finished_at": job.get("finished_at") or now_utc(), "case_pool": combined_case_pool()})
    append_job_log(job, message)
    write_job(job)


def run_attribute_job(job_id):
    try:
        job = load_job(job_id)
        payload = job.get("payload") or {}
        selected_ids, case_by_id = resolve_attribute_cases(payload)
        base_url = payload.get("parser_base_url") or "http://localhost:8000"
        parser_timeout = float(payload.get("parser_timeout") or 8)
        concurrency = attribute_job_concurrency(payload, len(selected_ids))
        job.update({"status": "running", "started_at": now_utc(), "running": True, "total": len(selected_ids), "concurrency": concurrency})
        append_job_log(job, f"任务开始，并发数 {concurrency}")
        write_job(job)
        pending = set()
        next_index = 0
        completed = 0
        persistable = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            while next_index < len(selected_ids) or pending:
                job = load_job(job_id)
                if job.get("cancel_requested") or job.get("status") == "cancelled":
                    mark_job_cancelled(job, "任务已取消；停止提交新用例，已发出的调用返回后不落库")
                    return
                while next_index < len(selected_ids) and len(pending) < concurrency:
                    case_id = selected_ids[next_index]
                    next_index += 1
                    case = case_by_id.get(case_id)
                    if not case:
                        completed += 1
                        result = {"id": case_id, "ok": False, "stage": "resolve_case", "error": "case id not found in canonical case pool", "attribution_record": failed_attribution_record(case_id, "resolve_case", "case id not found in canonical case pool")}
                        persistable.append(result)
                        job.setdefault("results", []).append(compact_job_result(result))
                        job["done"] = completed
                        job["failed"] = int(job.get("failed") or 0) + 1
                        append_job_log(job, f"失败 {completed}/{len(selected_ids)}: {case_id}，失败原因：case id not found in canonical case pool")
                        write_job(job)
                        continue
                    append_job_log(job, f"提交 {next_index}/{len(selected_ids)}: {case_id}")
                    future = executor.submit(attribute_single_case, case_id, case, payload, base_url, parser_timeout)
                    future.case_id = case_id
                    pending.add(future)
                    job["current_id"] = case_id
                    job["current_index"] = next_index
                    write_job(job)
                if not pending:
                    continue
                done, pending = concurrent.futures.wait(pending, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"id": getattr(future, "case_id", "unknown"), "ok": False, "stage": getattr(exc, "attribution_stage", "worker"), "error": str(exc)}
                    job = load_job(job_id)
                    if job.get("cancel_requested") or job.get("status") == "cancelled":
                        mark_job_cancelled(job, "任务已取消，丢弃已返回结果")
                        return
                    if result.get("ok") is False and not result.get("attribution_record") and result.get("id"):
                        result["attribution_record"] = failed_attribution_record(result.get("id"), result.get("stage") or "worker", result.get("error") or "unknown error")
                    persistable.append(result)
                    completed += 1
                    job["done"] = completed
                    if result.get("ok") is True:
                        job["attributed"] = int(job.get("attributed") or 0) + 1
                    else:
                        job["failed"] = int(job.get("failed") or 0) + 1
                    compact = compact_job_result(result)
                    job.setdefault("results", []).append(compact)
                    if result.get("ok") is True:
                        verdict = ((result.get("attribution_item") or {}).get("verdict") or "")
                        append_job_log(job, f"完成 {completed}/{len(selected_ids)}: {result.get('id')}{'，判定 ' + verdict if verdict else ''}")
                    else:
                        append_job_log(job, f"失败 {completed}/{len(selected_ids)}: {result.get('id')}，阶段 {result.get('stage') or 'unknown'}，失败原因：{result.get('error') or 'unknown error'}")
                    write_job(job)
        job = load_job(job_id)
        if job.get("cancel_requested") or job.get("status") == "cancelled":
            mark_job_cancelled(job, "任务已取消，返回结果未落库")
            return
        persist_attribution_results(persistable)
        job.update({"status": "completed", "running": False, "finished_at": now_utc(), "case_pool": combined_case_pool()})
        append_job_log(job, "任务完成，结果已集中落库")
        write_job(job)
    except Exception as exc:
        try:
            job = load_job(job_id)
            job.update({"status": "failed", "running": False, "finished_at": now_utc(), "error": str(exc), "case_pool": combined_case_pool()})
            append_job_log(job, f"任务异常结束：{exc}")
            write_job(job)
        except Exception:
            pass
    finally:
        with ACTIVE_ATTRIBUTE_JOBS_LOCK:
            ACTIVE_ATTRIBUTE_JOBS.discard(job_id)


def start_attribute_job(payload):
    case_ids = payload.get("case_ids") or []
    if not case_ids:
        raise RuntimeError("missing case_ids")
    with ACTIVE_ATTRIBUTE_JOBS_LOCK:
        active_job = current_active_attribute_job()
        if active_job:
            active_job_id = active_job.get("job_id")
            raise RuntimeError(f"已有归因任务运行中：{active_job_id}，请等待完成后再启动新任务")
        job_id = f"attr-{int(time.time() * 1000)}-{hashlib.sha1(json.dumps(case_ids, ensure_ascii=False).encode('utf-8')).hexdigest()[:8]}"
        ACTIVE_ATTRIBUTE_JOBS.add(job_id)
    job = {
        "job_id": job_id,
        "status": "queued",
        "running": False,
        "created_at": now_utc(),
        "total": len(case_ids),
        "done": 0,
        "attributed": 0,
        "failed": 0,
        "current_id": None,
        "current_index": 0,
        "payload": payload,
        "results": [],
        "logs": [f"{now_utc()} 已创建归因任务，共 {len(case_ids)} 条"],
    }
    try:
        write_job(job)
        thread = threading.Thread(target=run_attribute_job, args=(job_id,), daemon=True)
        thread.start()
        return job
    except Exception:
        with ACTIVE_ATTRIBUTE_JOBS_LOCK:
            ACTIVE_ATTRIBUTE_JOBS.discard(job_id)
        raise


def attribute_job_status(job_id):
    job = load_job(job_id)
    job["case_pool"] = combined_case_pool()
    return job


def cancel_attribute_job(job_id):
    if not job_id:
        raise RuntimeError("missing job_id")
    job = load_job(job_id)
    job["cancel_requested"] = True
    job["status"] = "cancelled"
    job["running"] = False
    job["finished_at"] = now_utc()
    append_job_log(job, "收到取消请求，已立即停止任务调度；当前已发出的单条调用返回后会被忽略")
    job["case_pool"] = combined_case_pool()
    write_job(job)
    with ACTIVE_ATTRIBUTE_JOBS_LOCK:
        ACTIVE_ATTRIBUTE_JOBS.discard(job_id)
    return job


def delete_saved_case_pool_cases(payload):
    delete_ids = set(payload.get("case_ids") or [])
    master = load_cases_master()
    deleted = 0
    for case in master.get("cases") or []:
        if case.get("case_id") in delete_ids or case.get("id") in delete_ids:
            if not case.get("deleted"):
                deleted += 1
            case["deleted"] = True
            case["updated_at"] = now_utc()
    save_cases_master(master)
    return {"deleted": deleted, "case_pool": combined_case_pool(), "case_catalog": case_catalog_view(), "summary_catalog": summary_catalog_view(), "custom_case_pool": combined_case_pool()}


def delete_case_pool_batch(payload):
    delete_ids = set(payload.get("case_ids") or [])
    batch_ids = {str(batch_id).strip() for batch_id in (payload.get("batch_ids") or []) if str(batch_id).strip()}
    batches = load_case_batches()
    deleted_case_ids = set(delete_ids)
    for member in batches.get("memberships") or []:
        if member.get("batch_id") in batch_ids:
            deleted_case_ids.add(member.get("case_id"))
    for batch in batches.get("batches") or []:
        if batch.get("batch_id") in batch_ids:
            batch["deleted"] = True
            batch["updated_at"] = now_utc()
    batches["memberships"] = [member for member in batches.get("memberships") or [] if member.get("batch_id") not in batch_ids and member.get("case_id") not in delete_ids]
    save_case_batches(batches)
    master = load_cases_master()
    deleted = 0
    active_memberships = {(member.get("case_id"), member.get("batch_id")) for member in active_batch_memberships(load_case_batches())}
    pool_memberships = {(member.get("case_id"), member.get("pool_id")) for member in active_pool_memberships(load_named_pools_store())}
    for case in master.get("cases") or []:
        case_id = case.get("case_id")
        if case_id not in deleted_case_ids or case.get("origin_type") == "default":
            continue
        still_referenced = any(item[0] == case_id for item in active_memberships) or any(item[0] == case_id for item in pool_memberships)
        if not still_referenced:
            if not case.get("deleted"):
                deleted += 1
            case["deleted"] = True
            case["updated_at"] = now_utc()
    save_cases_master(master)
    return {"deleted": deleted, "deleted_batch_ids": sorted(batch_ids), "case_pool": combined_case_pool(), "case_catalog": case_catalog_view(), "summary_catalog": summary_catalog_view(), "custom_case_pool": combined_case_pool()}


def save_named_case_pool(payload):
    name = str(payload.get("name") or "").strip() or time.strftime("用例池-%Y%m%d-%H%M%S")
    case_ids = [case_id for case_id in (payload.get("case_ids") or []) if case_id]
    pool_id = re.sub(r"[^0-9A-Za-z_\-]+", "-", name).strip("-") or str(int(time.time()))
    pool_id = f"pool-{pool_id}-{int(time.time())}"
    store = load_named_pools_store()
    entry = {"pool_id": pool_id, "id": pool_id, "name": name, "description": str(payload.get("description") or "").strip(), "created_at": now_utc(), "deleted": False}
    store["pools"] = [entry] + [pool for pool in store.get("pools") or [] if pool.get("pool_id") != pool_id]
    existing = {(member.get("pool_id"), member.get("case_id")) for member in store.get("memberships") or []}
    for case_id in case_ids:
        key = (pool_id, case_id)
        if key not in existing:
            store.setdefault("memberships", []).append({"pool_id": pool_id, "case_id": case_id})
            existing.add(key)
    save_named_pools_store(store)
    cases = [case for case in case_catalog_view().get("cases") or [] if case.get("case_id") in set(case_ids)]
    return {**entry, "case_count": len(cases), "cases": cases}


def load_named_case_pool(pool_id):
    for pool in load_case_pool_library().get("pools") or []:
        if pool.get("id") == pool_id or pool.get("pool_id") == pool_id:
            return pool
    raise RuntimeError(f"找不到用例池：{pool_id}")


def build_case_pool(payload):
    summary = build_summary_from_artifacts()
    requested_count = int(payload.get("count") or 24)
    requested_count = max(1, min(requested_count, 60))
    use_llm = payload.get("use_llm", True)
    user_prompt = str(payload.get("prompt") or "").strip()
    if use_llm:
        try:
            pool, meta = call_json_llm(
                build_case_pool_prompt(summary, requested_count, user_prompt),
                payload.get("analysis_model") or load_yaml_value("LLM_ATTRIBUTION_MODEL", MODEL_DEFAULT),
                payload.get("thinking_mode") or load_yaml_value("LLM_ATTRIBUTION_THINKING_MODE", "max"),
                3000,
                0.2,
                120,
            )
            cases = (pool.get("cases") or [])[:requested_count]
            source = "llm_generated"
            quality = pool.get("quality") or {"passed": bool(cases), "missing": [] if cases else ["LLM 未返回 cases"]}
        except Exception as exc:
            meta = {
                "llm_used": False,
                "analysis_model": payload.get("analysis_model") or load_yaml_value("LLM_ATTRIBUTION_MODEL", MODEL_DEFAULT),
                "analysis_thinking_mode": payload.get("thinking_mode") or load_yaml_value("LLM_ATTRIBUTION_THINKING_MODE", "max"),
                "analysis_elapsed_ms": 0,
                "llm_error": str(exc),
            }
            cases = local_case_pool_from_summary(summary)[:requested_count]
            source = "current_summary_skeleton_after_llm_failure"
            quality = {"passed": bool(cases), "missing": [f"LLM 生成超时或失败，已返回当前 summary 证据骨架候选：{exc}"]}
    else:
        meta = {"llm_used": False, "analysis_model": None, "analysis_thinking_mode": "default", "analysis_elapsed_ms": 0}
        cases = local_case_pool_from_summary(summary)[:requested_count]
        source = "current_summary_skeleton"
        quality = {"passed": bool(cases), "missing": [] if cases else ["没有可用归因簇生成候选用例"]}
    case_pool = {
        "generated_at": now_utc(),
        "generated_by": "llm_attribution_server case pool builder",
        "source": source,
        "user_prompt": user_prompt,
        "source_clusters": [c.get("id") for c in summary.get("clusters") or []],
        "cases": cases,
        "quality": quality,
        **meta,
    }
    saved = save_case_pool(case_pool)
    return {**saved, "latest_batch": case_pool}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.end_json(200, {"ok": True})

    def do_GET(self):
        parsed_path = urlparse(self.path).path
        if parsed_path == "/llm_attribution_health":
            self.end_json(200, attribution_health())
            return
        if parsed_path == "/llm_chain_probe_results":
            self.end_json(200, {"ok": True, "chain_probe": load_chain_probe_results()})
            return
        if parsed_path == "/llm_case_catalog":
            self.end_json(200, {"ok": True, "catalog": case_catalog_view()})
            return
        if parsed_path == "/llm_summary_scopes":
            catalog = case_catalog_view()
            self.end_json(200, {"ok": True, "catalog": catalog, "summaries": list_attribution_summaries()})
            return
        if parsed_path == "/llm_summary_catalog":
            self.end_json(200, {"ok": True, "summaries": list_attribution_summaries()})
            return
        if parsed_path == "/llm_case_pool_saved":
            self.end_json(200, {"ok": True, "case_pool": combined_case_pool()})
            return
        if parsed_path == "/llm_case_pool_library":
            self.end_json(200, {"ok": True, "library": load_case_pool_library()})
            return
        if parsed_path == "/llm_attribution_summaries":
            self.end_json(200, {"ok": True, "summaries": list_attribution_summaries()})
            return
        if parsed_path == "/llm_attribution_summary_saved":
            try:
                params = parse_qs(urlparse(self.path).query)
                summary_id = (params.get("summary_id") or [""])[0]
                self.end_json(200, {"ok": True, "summary": load_attribution_summary(summary_id)})
            except Exception as exc:
                self.end_json(404, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_attribute_state":
            try:
                self.end_json(200, {"ok": True, **attribute_task_state()})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_attribute_latest":
            try:
                self.end_json(200, {"ok": True, "job": latest_attribute_job()})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_attribute_status":
            try:
                params = parse_qs(urlparse(self.path).query)
                job_id = (params.get("job_id") or [""])[0]
                self.end_json(200, {"ok": True, "job": attribute_job_status(job_id)})
            except Exception as exc:
                self.end_json(404, {"ok": False, "error": str(exc)})
            return
        if parsed_path.startswith("/llm_case_pool_library/"):
            try:
                pool_id = parsed_path.rsplit("/", 1)[-1]
                self.end_json(200, {"ok": True, "pool": load_named_case_pool(pool_id)})
            except Exception as exc:
                self.end_json(404, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_failure_analysis":
            self.end_json(405, {
                "ok": False,
                "error": "Use POST /llm_failure_analysis from live_query.html. GET is only a health-style check."
            })
            return
        super().do_GET()

    def do_POST(self):
        parsed_path = urlparse(self.path).path
        if parsed_path == "/llm_attribution_health":
            self.end_json(200, attribution_health())
            return
        if parsed_path == "/llm_chain_probe_results":
            self.end_json(200, {"ok": True, "chain_probe": load_chain_probe_results()})
            return
        if parsed_path == "/llm_attribution_summary":
            try:
                self.end_json(200, {"ok": True, "summary": build_summary_from_artifacts()})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_build":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.end_json(200, {"ok": True, "case_pool": build_case_pool(payload)})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_import":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.end_json(200, {"ok": True, **import_case_pool(payload)})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_attribute":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.end_json(200, {"ok": True, **attribute_case_pool(payload)})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_attribute_start":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.end_json(200, {"ok": True, "job": start_attribute_job(payload)})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_attribute_cancel":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.end_json(200, {"ok": True, "job": cancel_attribute_job(payload.get("job_id"))})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_attribution_summary_from_cases":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.end_json(200, {"ok": True, "summary": build_summary_from_custom_cases(payload)})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_attribution_summary_save":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                summary = payload.get("summary") or {}
                if not summary.get("clusters") and not summary.get("totals"):
                    raise RuntimeError("missing summary")
                source = payload.get("source") or summary.get("source") or "custom"
                explicit_name = payload.get("summary_name") if payload.get("explicit_summary_name") else None
                self.end_json(200, {"ok": True, "summary": save_attribution_summary(summary, explicit_name, source)})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_delete_cases":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.end_json(200, {"ok": True, **delete_saved_case_pool_cases(payload)})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_delete_batch":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.end_json(200, {"ok": True, **delete_case_pool_batch(payload)})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path == "/llm_case_pool_save_named":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.end_json(200, {"ok": True, "pool": save_named_case_pool(payload)})
            except Exception as exc:
                self.end_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed_path != "/llm_failure_analysis":
            self.end_json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            judgement = external_general_eval_judgement(payload) or call_judge(payload)
            analysis = analyze_after_judge(payload, judgement)
            analysis["judge_result"] = judgement
            analysis["verdict"] = judgement.get("verdict")
            analysis["review_verdict"] = judgement.get("review_verdict")
            self.end_json(200, {"ok": True, "analysis": analysis, "judge_result": judgement})
        except Exception as exc:
            self.end_json(500, {"ok": False, "error": str(exc)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"search-test-case server: http://{args.host}:{args.port}/index.html")
    print("LLM attribution endpoint: POST /llm_failure_analysis")
    print("Attribution summary endpoint: POST /llm_attribution_summary")
    print("Case pool builder endpoint: POST /llm_case_pool_build")
    print("Case pool import endpoint: POST /llm_case_pool_import")
    print("Case pool attribution endpoint: POST /llm_case_pool_attribute")
    print("Attribution summaries endpoints: GET /llm_attribution_summaries, GET /llm_attribution_summary_saved")
    print("Custom attribution summary endpoint: POST /llm_attribution_summary_from_cases")
    print("Saved case pool endpoint: GET /llm_case_pool_saved")
    print("Case pool library endpoints: GET /llm_case_pool_library, POST /llm_case_pool_save_named")
    print("Case pool delete endpoints: POST /llm_case_pool_delete_cases, POST /llm_case_pool_delete_batch")
    server.serve_forever()


if __name__ == "__main__":
    main()
