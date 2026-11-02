"""E 组：trace 路线 4 条（agno / langfuse × 客户号、伏云平）。已存 trace 不含 project_fields，按原请求重新向 provider 取业务 trace。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from impl.server.service import normalize_run_trace
from impl.projects.llm_probe.capability import capability_business_trace
from impl.projects.llm_probe.business_trace import collect
from impl.projects.llm_probe.live import _ASSOCIATION_KEY

NAMES = ('agno-bizno', 'agno-fuyunping-policies', 'langfuse-bizno', 'langfuse-fuyunping-policies')


def load(name):
    t = json.loads((common.MAIN / f'report/integrate-verify-20261018/insurance-chain/{name}.json').read_text())['response']['trace']
    req = t['normalized_request']
    raw = t['raw_response']
    response = raw[0] if isinstance(raw, list) and raw else raw
    config = capability_business_trace(req['capability_ref'])
    t.setdefault('project_fields', {})
    t['project_fields'].update({'capability_ref': req['capability_ref'], 'capability': req.get('capability') or '', 'show_schema': req.get('show_schema'),
                                'business_trace': collect(config, request=req, response=response, association=req.get(_ASSOCIATION_KEY))})
    # 多轮路线按轮读 turn_records[i].project_fields.business_trace（dossier._snapshots）；本组都是单轮。
    for turn in t.get('turn_records') or []:
        turn.setdefault('project_fields', {})['business_trace'] = t['project_fields']['business_trace']
    t['case_id'] = name
    return normalize_run_trace(t)


if __name__ == '__main__':
    for name in NAMES:
        tr = load(name)
        bt = (tr.project_fields or {}).get('business_trace') or {}
        print(name, bt.get('status'), bt.get('provider'), str(bt.get('errors'))[:200], len(json.dumps(bt, ensure_ascii=False)))
