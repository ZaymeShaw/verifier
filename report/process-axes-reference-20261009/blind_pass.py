"""B pass: an independent model writes "本应产出" from the component's INPUT only, then aligns it to the actual run.

Stage 1 (blind): per component the model sees only what that component actually received
  (never its output). Model axis: one request per model call, so a later call's input cannot
  leak an earlier call's output. Output: a list of verifiable statements typed 推出/守恒/外部真值.
Stage 2 (align): the frozen list + the complete case file -> per-statement verdict and problems.
Everything is persisted under B_runs/<provider>_rep<k>/<case>/<axis>/.

usage: python blind_pass.py <provider> <rep> [workers]
  provider: gemini (primary) | qwen (fallback1) | deepseek (fallback2); rep = independent repetition number.
temperature 0. 2026-10-09: the primary Gemini route was region-blocked ("User location is not supported"),
so the recorded runs use deepseek-flash; the method does not depend on the model.
"""
import concurrent.futures as cf, json, re, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from impl.core.llm_client import extract_json

P = 'turn1/records/'
PROVIDERS = {'gemini': '.env.verifier_primary', 'qwen': '.env.verifier_fallback1', 'deepseek': '.env.verifier_fallback2'}
MODEL = BASE = KEY = ''
MAX_TOKENS = 24000  # raised for the redo of truncated stage-2 outputs


def use_provider(name):
    global MODEL, BASE, KEY
    env = dict(l.rstrip('\n').split('=', 1) for l in open(ROOT / '.runtime/instances/inst-16fa340ac786414f/tracing' / PROVIDERS[name])
               if '=' in l and not l.startswith('#'))
    env = {k: v.strip('"') for k, v in env.items()}
    MODEL, BASE, KEY = env['UPSTREAM_MODEL'], env['UPSTREAM_API_BASE'], env['UPSTREAM_API_KEY']

AXES = {
    'intent_understanding': ('意图理解', '表达', '用户原文、被指代的历史 → 系统内部表达（实际写进工具参数、改写后的任务描述里的东西）',
                             '原文里有五样东西必须被表达保住：对象与字段、子问题、约束、指代、不确定性（歧义）'),
    'planning_routing': ('规划路由', '编排', '任务、当时状态、规则 → 路径、调用序列、重试、收尾',
                         '每种决策都要与输入一致：选路径、给每个子问题安排工作、分支、失败后的动作、重复调用、工具返回后的整合、收尾、系统自身策略'),
    'tool_execution': ('工具执行', '执行', '已发出的调用参数 → 返回',
                       '返回必须：执行完成、就是请求的对象且完整、在时限内'),
    'knowledge_data': ('知识数据', '数据源', '已正确执行的查询 → 数据是否存在、是否匹配',
                       '数据必须：存在、匹配（只有查询被正确执行时，数据源才对结果负责）'),
    'model_capability': ('模型能力', '模型', '一次调用的实际输入 → 该次输出',
                         '输出必须：忠实于输入、不添加输入没有的东西、决策与输入一致、遵循输入里写明的契约'),
    'context_memory': ('上下文管理', '传递', '一处产出 → 下一处输入（含组装、缓存、历史、交付）',
                       '传递必须：原义到达、组装正确、历史与缓存来源正确、交付完整'),
}

STAGE1 = """你是过程评测者。下面是业务系统的一个部件在一次运行里**实际拿到的输入**。你看不到它的输出——这是故意的：要先写出“做对的部件在这个输入下本应产出什么”，写完才会拿它去对照实际产出。

部件：{name}（{part}）。输入 → 输出：{io}
这类部件必须保住或产出的方面（写条目时当提纲用，不是要逐项凑数）：{aspects}

“本应产出”不是参考答案，而是一组**可对着运行记录核对的陈述**，描述“正确的输出必须满足什么”。允许只写一部分，写不全的地方在 not_covered 里说明。每条标一个类型：
- 推出：能由这个部件的输入、冻结的期望 E、业务系统自己写明的规则推出来的“本应如此”；
- 守恒：参考就是上游产出本身——下游不得丢失、改写，也不得凭空多出；
- 外部真值：必须靠独立查证才知道对不对（例如数据库里到底有没有这条数据），仅凭运行记录给不出。这类也要写，但要如实标出。

写法要求：
1. 每条一句话，具体到能核对；写清依据（期望编号、规则原文里的几个字、或输入里的位置）。
2. 只写你有依据的。没有依据、靠常识猜的，不要写。
3. “本应”相对于**实际拿到的输入**：输入本身已有问题时，也按这个输入来写。
4. 同一部件有多个实例（多次调用等）时按实例分别写，模式相同的可以合并，写明适用于哪些实例。
5. 不要写评价，也不要猜实际会怎样——你看不到。

只输出一个 JSON 对象，不要任何其他文字：
{{"instance": "<这次写的是哪个对象>",
  "items": [{{"id": "R1", "type": "推出|守恒|外部真值", "statement": "…", "basis": "依据"}}],
  "not_covered": ["…"]}}

===== 输入材料 =====
{material}"""

STAGE2 = """你是过程评测者。下面有两样东西：
(1) 一份**已经冻结**的“本应产出”清单——不得修改、增删或重新表述；
(2) 这次运行的完整案卷（输入和实际产出都在里面）。

任务：只评“{name}”这个部件（{part}）。逐条核对清单，再写出问题。
核对口径：
- met 达到；not_met 没达到；cannot_check 仅凭案卷无法判断（例如外部真值、没有配置的时限）。
- 判断要有案卷里的依据：引用记录 id 或原文片段。不确定就写 cannot_check，不要猜。
- “本应”相对于该部件**实际拿到的输入**：如果没达到是因为它拿到的输入已经坏了，不算它的问题，在 attribution 里写 上游:<轴名>。
问题（problems）：每个独立问题一条，写清哪一步、现象、预期（对应清单哪几条）、实际。attribution 写：本轴 | 上游:<轴名> | 未定位:<候选轴>。同一事件可以被多个轴各自记录。
清单之外你发现的值得注意的事，写进 extra_observations，不要混进 results。

只输出一个 JSON 对象，不要任何其他文字：
{{"results": [{{"id": "…", "verdict": "met|not_met|cannot_check", "observation": "…", "refs": ["记录 id 或片段"]}}],
  "problems": [{{"phenomenon": "…", "violates": ["清单 id"], "attribution": "…", "impact": "yes|no|unknown", "refs": ["…"]}}],
  "extra_observations": ["…"]}}

===== 冻结清单 =====
{items}

===== 案卷 =====
{casefile}"""


def text(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def render_messages(msgs):
    out = []
    for m in msgs:
        body = m.get('content')
        if m.get('tool_calls'):
            body = (text(body) if body else '') + ' [发起工具调用] ' + text(m['tool_calls'])
        out.append(f"[{m['role']}] {text(body)}")
    return '\n\n'.join(out)


def parts(case):
    R = case['records']
    mcs = sorted([(i, r) for i, r in R.items() if r.get('kind') == 'model_calls' and i.startswith(P + 'traces/0/tree/0/spans/3/spans/')],
                 key=lambda kv: int(kv[0].rsplit('/', 1)[1]))
    tool_desc = {}
    for i, r in R.items():
        if r.get('kind') == 'tool_calls' and 'tool_description' in r:
            tool_desc.setdefault(r['name'], r['tool_description'])
    tools = sorted([(i, r) for i, r in R.items() if r.get('kind') == 'tool_calls' and i.startswith(P + 'run/step_executor_runs/0/tools/') and i.count('/') == 6],
                   key=lambda kv: int(kv[0].rsplit('/', 1)[1]))
    return R, mcs, tool_desc, tools


def head(case):
    users = '\n'.join(f"- ({s['id']}) {s['value']}" for s in case['expectation_sources'])
    es = '\n'.join(f"- {e['expectation_id']}：{e['statement']}（条件：{e['condition']}；歧义组：{e['ambiguity_group'] or '无'}）" for e in case['expectations'])
    return f"【用户原话】（首轮，无历史）\n{users}\n\n【冻结的期望 E】\n{es}\n"


def stage1_tasks(axis, case):
    R, mcs, tool_desc, tools = parts(case)
    sys_prompt = mcs[0][1]['exact_request']['messages'][0]['content']
    budget = mcs[0][1]['exact_request']['messages'][1]['content']
    td = '\n\n'.join(f"工具 {n} 的说明：\n{text(d)}" for n, d in tool_desc.items())
    wf = text(R[P + 'definitions/0/data']['steps'])
    h = head(case)
    if axis == 'intent_understanding':
        return [('整轮', h + f"\n【业务系统写给模型的规则（系统提示词）】\n{sys_prompt}\n\n【内部表达可以落到的工具（说明）】\n{td}")]
    if axis == 'planning_routing':
        return [('整轮', h + f"\n【工作流定义（步骤与条件分支）】\n{wf}\n\n【业务系统写给模型的规则（系统提示词）】\n{sys_prompt}\n\n【本轮开始时程序给出的预算与任务块】\n{budget}\n\n【可用工具（说明）】\n{td}")]
    if axis in ('tool_execution', 'knowledge_data'):
        calls = '\n'.join(f"- 第{n}次调用 tools/{n}：{r['name']}，参数 {text(r['arguments'])}" for n, (i, r) in enumerate(tools))
        return [('整轮', h + f"\n【各工具的说明】\n{td}\n\n【已发出的调用（按时间顺序，只有参数，没有返回）】\n{calls}")]
    if axis == 'model_capability':
        return [(f'模型调用{n + 1}', h + f"\n【这一次模型调用实际收到的全部输入消息（第{n + 1}次，共{len(mcs)}次）】\n{render_messages(r['exact_request']['messages'])}")
                for n, (i, r) in enumerate(mcs)]
    if axis == 'context_memory':
        ups = []
        for n, (i, r) in enumerate(mcs):
            ups.append(f"- 模型调用{n + 1}的输出：{text(r['output']['messages'])}")
        for n, (i, r) in enumerate(tools):
            ups.append(f"- 工具 tools/{n}（{r['name']}）的返回：{text(r.get('result'))}")
        steps = '组装(assemble) → 路由(gate) → 条件分支(to_agent: agent_input → agent → [agent_bridge]) → 收尾(finalize) → 交付给调用方(delivered_output)'
        return [('整轮', h + f"\n【这次运行的传递链（程序步骤）】\n{steps}\n\n【各处产出（上游）。下游实际收到的是什么，你看不到】\n" + '\n'.join(ups))]
    raise KeyError(axis)


def call_model(prompt):
    body = {'model': MODEL, 'temperature': 0, 'stream': True, 'stream_options': {'include_usage': True}, 'max_tokens': MAX_TOKENS,
            'messages': [{'role': 'user', 'content': prompt}]}
    req = urllib.request.Request(BASE.rstrip('/') + '/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    t = time.time(); chunks = []; usage = {}
    with urllib.request.urlopen(req, timeout=1500) as r:
        for raw in r:
            line = raw.decode('utf-8', 'ignore').strip()
            if not line.startswith('data:') or line == 'data: [DONE]':
                continue
            try:
                j = json.loads(line[5:])
            except ValueError:
                continue
            if j.get('usage'):
                usage = j['usage']
            for ch in j.get('choices') or []:
                if (ch.get('delta') or {}).get('content'):
                    chunks.append(ch['delta']['content'])
    return ''.join(chunks), dict(elapsed=round(time.time() - t), prompt_tokens=usage.get('prompt_tokens'), completion_tokens=usage.get('completion_tokens'),
                                 reasoning_tokens=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens'))


def ask(prompt, out_path, must):
    """One model call, parsed. Rate limits / 5xx back off and retry; a non-JSON reply is retried once."""
    import urllib.error
    last, parse_failures = '', 0
    for attempt in range(1, 10):
        try:
            raw, meta = call_model(prompt)
            obj = extract_json(raw)
            if isinstance(obj, dict) and must in obj:
                out_path.write_text(json.dumps(dict(meta=meta, attempt=attempt, result=obj), ensure_ascii=False, indent=1))
                return obj
            last = f'missing {must}: {raw[:200]}'
            parse_failures += 1
        except urllib.error.HTTPError as exc:
            last = f'HTTPError {exc.code}'
            if exc.code in (429, 500, 502, 503, 504):
                time.sleep(min(15 * attempt, 90))
                continue
            break
        except Exception as exc:  # noqa: BLE001 - recorded
            last = f'{type(exc).__name__}: {str(exc)[:200]}'
            parse_failures += 1
        if parse_failures >= 2:
            break
    out_path.write_text(json.dumps(dict(error=last), ensure_ascii=False, indent=1))
    return None


def run(provider, rep, workers):
    use_provider(provider)
    cases = {'renyanlin': json.load(open(HERE / 'case_files/case_renyanlin.json')), 'D01': json.load(open(HERE / 'case_files/case_D01.json'))}
    base = HERE / 'B_runs' / f'{provider}_rep{rep}'
    jobs = []
    for cname, case in cases.items():
        for axis, (name, part, io, aspects) in AXES.items():
            d = base / cname / axis; d.mkdir(parents=True, exist_ok=True)
            for k, (inst, material) in enumerate(stage1_tasks(axis, case)):
                jobs.append((cname, axis, k, inst, STAGE1.format(name=name, part=part, io=io, aspects=aspects, material=material), d / f'stage1_{k}.json'))
    print(f'{provider} rep{rep} ({MODEL}): stage1 tasks {len(jobs)}', flush=True)
    with cf.ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda j: ask(j[4], j[5], 'items'), jobs))
    merged = {}
    for (cname, axis, k, inst, _, _), obj in zip(jobs, res):
        if obj is None:
            continue
        for it in obj['items']:
            merged.setdefault((cname, axis), []).append(dict(id=f"{inst}.{it['id']}", type=it.get('type'), statement=it.get('statement'), basis=it.get('basis')))
        merged.setdefault((cname, axis, 'nc'), []).extend(obj.get('not_covered') or [])
    for (cname, axis), items in [(k, v) for k, v in merged.items() if len(k) == 2]:
        (base / cname / axis / 'frozen_items.json').write_text(json.dumps(dict(items=items, not_covered=merged.get((cname, axis, 'nc'), [])), ensure_ascii=False, indent=1))
    print(f'{provider} rep{rep}: stage1 done, ok {sum(o is not None for o in res)}/{len(res)}', flush=True)
    jobs2 = []
    for (cname, axis), items in [(k, v) for k, v in merged.items() if len(k) == 2]:
        name, part = AXES[axis][0], AXES[axis][1]
        prompt = STAGE2.format(name=name, part=part, items=json.dumps(items, ensure_ascii=False, indent=1), casefile=json.dumps(cases[cname], ensure_ascii=False))
        jobs2.append((cname, axis, prompt, base / cname / axis / 'stage2.json'))
    with cf.ThreadPoolExecutor(workers) as ex:
        res2 = list(ex.map(lambda j: ask(j[2], j[3], 'results'), jobs2))
    print(f'{provider} rep{rep}: stage2 done, ok {sum(o is not None for o in res2)}/{len(res2)}', flush=True)


if __name__ == '__main__':
    run(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 12)
