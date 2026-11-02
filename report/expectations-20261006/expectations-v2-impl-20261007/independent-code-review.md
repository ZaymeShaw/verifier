# expectations-v2 独立实现评审

日期：2026-10-07。范围：当前工作区实现及相关测试；只读评审，唯一写入为本报告。

## 结论

**不宜把当前实现标为 expectations-v2 已完整验收。** 初审快照上 407 项定向离线测试通过，额外最小反例证实了 **4 个 P1、3 个 P2 问题**。收尾发现并发源码更新：**R2 的扁平化路径分支已机械修复，删字段分支仍存在**；最新同组回归为 **406 passed / 1 failed**（错误文案断言不同，详见下文）。本报告保留初审证据并明确标注收尾变化，不把已修部分继续声称为当前失败。关键缺口不在于需要新架构，而在于现有接口之间丢了判准结论、来源身份或原文块。

- **P1**：影响需求隔离、判定归属或原文证据契约，应在宣称 v2 完整正确前修复。
- **P2**：特定合法输入、复用入口或配置保存路径上的正确性/集成缺口。
- 所有反例均为离线人工构造，另对旧冻结样本做了原文块枚举。**未发起真实模型或业务调用，未验证当前正在运行的 live，更不声称 live 通过。**
- 以下是当前实现与本任务的差距，不声称全部都是本轮新增回归。对照 `before/llm_probe/`，R1 的部分聚合约束及 R4/R5 的来源假设沿用了旧实现；R7 是既有存储接口没有接住新增消费语义。这些逻辑问题与用户指出的 14 项旧测试失败不是同一回事。

## 评审依据与验证边界

已读取：`AGENTS.md`，`.agents/skills/{aihacking,elegance_review,generalization}/SKILL.md`，实施任务，`demand/expectations.md`，`spec/alg/expectations.md` 全文、过程六轴协议及实施记录、`process-axes-output-abstraction-20261007.md`。

重点核查：`process_output.py`、`expectation_projection.py`、`process_common.py`、`process_protocol.py`、`design_rules.py` / materials、两个 ToolLoop 入口及 llmtracing provider、`expectation_material.py`、`expectations.py`、`need_judge.py`、主判接入和相关测试。复用了现有 Pydantic/structured-output、案卷与取证接口，没有建议兼容层、迁移或共享核心大重构。

初审快照上独立执行的测试：

| 测试组 | 文件 | 结果 |
|---|---|---|
| 单位、原文规则、入口、需求主判 | `test_process_v2_rules.py`、`test_process_unit_output.py`、`test_design_rule_blocks.py`、`test_process_v2_entrypoints.py`、`test_expectations_v2_need_judge.py`、`test_process_criterion_checks.py` | **302 passed，0.50s** |
| 需求、prompt、材料、主判、协议 | `test_expectations.py`、`test_process_prompt_contract.py`、`test_axis_materials.py`、`test_process_main_judge.py`、`test_process_axes_protocol.py` | **105 passed，0.38s** |

**收尾并发更新后的复跑**：上述 11 个文件合并运行，**1 failed / 406 passed，0.64s**。失败为 `tests/test_expectations.py:185–195::test_candidate_methods_quote_original_tool_description_not_requirement_ids`：测试期望错误含“原文位置”，新 `validate_join()` 对未知 block 的错误改为“候选办法 block='Q' 不在工具块编号 …”。无效 block 仍被正确拒绝，属于错误文案与测试断言未同步，不是接受非法引用。没有修改该测试，也没有把本项混入用户所述旧 14 项失败。

收尾另外重跑的纯函数探针确认：R2 正确 `/parameters/value/...` 路径能回到源 record，旧扁平路径已被拒；R2 的 `strict/x-condition` 字段丢失仍在；R1 的混合上游、R3 的配对 span 漏块、R6 的错误 E 投影仍可复现。其他相关源码哈希未变。全部仍是离线检查，不是 live 验证。

解释器为 `/Users/xiaozijian/miniconda3/envs/agno/bin/python`，Python 3.11.14 / Pydantic 2.10.3，与 `requirements.txt:1,7` 的运行版本一致。使用 `-B`、禁用 pytest cache/logging/plugin autoload 和断言改写，并装 Python audit hook，拒绝文件写入、文件系统修改、子进程和网络连接。最初 pytest logging 试图以写方式打开 `/dev/null`，被守护在测试执行前拦截；禁用 logging 插件后完成上述两组，**没有放宽文件写权限**。

未重跑全仓。既有 `tests-after-first.log:723–737` 记录 14 failed / 2241 passed / 5 skipped；只作为他人已有证据引用，不冒充独立回归，也不为这些旧失败修改代码。

下文 Python 片段在仓库根目录运行，调用的是实际校验/投影函数或现有纯测试 fixture，不调用模型。建议使用文末相同只读守护。

---

## R1 — P1：按单位总结果校验，丢失逐判准上游依赖，并把未定位问题升级为本轴问题

**位置**

- `impl/projects/llm_probe/eval_axes/adapters/process_output.py:238–246,282–301`
- `impl/projects/llm_probe/eval_axes/adapters/process_protocol.py:63–98,105–111,148–152`
- `impl/projects/llm_probe/process_loop/expectation_projection.py:241–257`（收尾版本；初审为 230–246）
- 下游放大点：`impl/projects/llm_probe/judge.py:20–41`

**依据**：六轴协议 §3.2–§3.3、§5；expectations v2 §6.5。逐条判准的结论与依赖不能在汇总时改变。`sound` 可以与部分输入无效并存，但输入无效的组成及具体上游问题必须保留。

### 反例 A：同单位 `pass + input_invalid`

```python
from tests.test_process_v2_rules import case, item, submit, upstream_issue

c = case(source='agno', refs=['obligation:rule'])
item(c)['rules'][0]['outcome'] = 'input_invalid'
r, = submit(c)
print(r['outcome'], [x['outcome'] for x in r['criterion_checks']],
      r['upstream_issue_ids'])
# pass ['pass', 'input_invalid'] []

p = upstream_issue()  # 由真实 validator 生成的人工上游问题
c['recorded_issues'] = [p]
item(c)['upstream'] = [p['problem_id']]
submit(c)
# ValueError: 只有 input_invalid 可以引用上游问题
```

程序先把该单位聚合成 `pass`，随后只校验单位的 `outcome`：省略上游反而通过，填写合法上游反而失败。`criterion_checks` 虽保存了 `input_invalid` 字样，但已经没有它必需的上游关联。

同一实际行使合并多个结果时还有第二层损失：`coalesce()` 保留内部 `checks`，却把非 `input_invalid` 总结果的顶层 `upstream_issue_ids` 清空；`composition()` 只看顶层结果。实测一个 `pass` 和一个带 `context_memory:p1` 的 `input_invalid` 合并后：

```text
内部 checks: [('pass', []), ('input_invalid', ['context_memory:p1'])]
composition: pass=1, input_invalid=0, input_invalid列表=[]
主判 slim results: [{'obligation_id': 'rule', 'link_id': 'step', 'outcome': 'pass'}]
```

这里不能说原始内部检查全部丢失；准确的问题是**组成、上游引用与主判消费视图把未检验部分藏掉了**。

### 反例 B：同单位存在本轴失败和另一个未定位缺证问题

使用两个不同原文判准，不依赖重复规则：

```python
from tests.test_process_v2_rules import case, block, item, rule, problem, submit
from impl.projects.llm_probe.eval_axes.adapters.process_protocol import issues_for

text = 'All monetary values must be current.'
c = case(raw_blocks=[block(), block(text, path='/messages/1/content')])
item(c)['rules'] = [
    rule('fail'),
    rule('insufficient_evidence',
         quotes=[dict(block='B2', quote=text)], missing=['input state unknown']),
]
c['payload']['problems'] = [
    problem(('U1/D1',)),
    problem(('U1/D2',), unresolved=True),
]
submit(c)
# ValueError: 归因未定位不能判 fail

c['payload']['problems'][1]['axes'] = ['model_capability']
r, = submit(c)
print([p['attribution'] for p in issues_for('model_capability', [r])])
# ['local', 'local']
```

第二条判准仍是 `insufficient_evidence`，但因为第一条令单位总结果为 `fail`，其问题被程序标成 `local`。正确的未定位提交被拒，错误地归为本轴反而获准。这是**计算生成的错误归属**，不是“模型语义可能判断不准”。

**测试缺口**：`tests/test_process_criterion_checks.py:55–77` 的混合值测试主要调用 `expand`，没有穿过后续问题/上游校验；`tests/test_process_v2_rules.py:605–624` 覆盖的是两个不同子能力，不是同单位多判准或同一实际行使合并。

**最小修复方向**：在现有共享校验内按原子判准核对输入无效依赖；问题归属使用其 `breaks` 对应判准而不是整单位总结果。汇总保留部分无效检查及上游关系。不需要改 verdict 优先序，更不能通过删上游、改结论为缺证来绕过错误。

## R2 — P1（初审，收尾部分修复）：工具原文块的真实路径与完整性

**收尾状态**：并发更新已将 `design_rules.py:261–265` 改为保留实际 fields wrappers。用最新代码复核，`/parameters/value/properties/id/description` 能同时通过 `quote_text()` 与源 record 解析，旧 `/parameters/properties/...` 路径被拒。**下面关于扁平化的代码及输出是初审 SHA `3e89bdc7…` 的历史复现，不再描述最新代码。** `declarations():103–106` 的工具定义字段剪裁未改，收尾仍复现删除 `strict` 和 `x-condition`，因此完整性部分尚未关闭。

**初审位置**

- `impl/projects/llm_probe/business_trace/design_rules.py:40–46,97–107,261–264`
- `impl/projects/llm_probe/eval_axes/adapters/process_output.py:198–214`

**依据**：expectations v2 §6.3–§6.5：位置 + 原样摘录必须对应同一份原文；块覆盖不能以删字段后的合成对象代替原始结构。

`dossier_blocks()` 对 `definition_type=tool` 把各 `fields[name].value` 提升成 `{name: value}`，却仍把块位置标为 `/fields`。真实 `/fields` 下是 `{name: {status, value, ...}}`。`quote_text()` 只查合成块，`expand()` 直接把两个路径拼起来，未核验拼接后能否回到原文。

```python
from tests.test_design_rule_blocks import row
from impl.projects.llm_probe.business_trace.design_rules import (
    COLLECTION, dossier_blocks, quote_text,
)
from impl.projects.llm_probe.business_trace.dossier import resolve_node_path

source = row('def', 'definitions', description='Lookup by identifier.',
    parameters={'properties': {'id': {'description': 'Identifier must be nonempty.'}}})
source.update(name='lookup', definition_type='tool', scope=COLLECTION)
links = [dict(link_id='step', link_type='planning_routing', turn='turn1',
              input=[dict(ref='def', field='definition')], output=[])]
b, = dossier_blocks({'records': [source]}, links, 'planning_routing')
p = '/parameters/properties/id/description'
print(quote_text(b, p))
# Identifier must be nonempty.
resolve_node_path(source, b['path'] + p)
# ValueError: 路径不存在 ... 当前可用的键：['status', 'value']
```

进一步把该块作为 `B1`，用 `path=p`、原样 quote、`insufficient_evidence` 和版本 missing 提交到 `validate_submission()`，**完整提交仍被接受**，保存的错误路径为：

```text
/fields/parameters/properties/id/description
```

正确原文位置实际包含 `/parameters/value/`。这不只是展示不方便，而是“逐字核验声明位置”的机械承诺没有成立。

同文件还有原文完整性问题：`declarations():103–106` 遇到 `name + parameters` 时仅保留 `name/description/parameters/returns` 后立即返回。输入一个含 `strict=True`、`x-condition='Only after confirmation.'` 的完整工具定义，`project_design()` 输出块删掉了这两个字段，块位置仍指向原对象。`strict` 是现成工具 schema 字段；扩展条件也不应由原文块枚举器先行删去。

**边界**：可逆地解开 JSON 请求封装、展开 `content_ref` 本身没有问题。本发现不是要求保留序列化空白，而是要求**结构/路径与被声明的源一致，且完整块不删字段**。

**测试缺口**：现有块测试主要在块自己的 `text` 上调用 `quote_text`；`tests/test_process_v2_rules.py:287–316` 覆盖真实请求子树，没有对工具 `fields` 合成分支做“最终 quote 路径回查原 record”测试。

**剩余修复方向**：保留已经修正的真实 fields 子树及其路径，不退回 flatten；把完整工具定义字段保留下来。增加最终保存路径对原 record 的反向解析测试，并覆盖 `strict` 及独立条件字段。路径修复只经本次机械探针核对，不能据此宣布所有原文块完整性已验收。

## R3 — P1：已交付的当次工具说明未进入候选块，版本可用的判准被排除在规则选择之外

**位置**

- `impl/projects/llm_probe/business_trace/design_rules.py:215–241`
- 对照已有正确材料交付：`impl/projects/llm_probe/business_trace/materials.py:84–92`
- 实际行使去重：`impl/projects/llm_probe/business_trace/links.py:134–145`

**依据**：expectations v2 §6.3–§6.4：候选原文块应完整交付；当次执行规则应能使用，不能只剩未经核实的采集版定义。

工具行使使用 persisted call 作为端点，并通过 `span_ref` 关联同一次执行的 span。`material_view()` 已正确补上该 span 的 `tool_description`；但 `dossier_blocks()` 只查端点 row 自己的 `tool_description`，不跟随已确认的 `span_ref`。该说明既没有 B 编号，也不在任何单位待标注清单中。模型即使从材料看到了它，也不能按共享输出协议引用成规则。

```python
import json
from tests.test_axis_materials import data, row
from impl.projects.llm_probe.eval_axes.adapters.process_common import _axis_links
from impl.projects.llm_probe.business_trace.materials import material_view
from impl.projects.llm_probe.business_trace.design_rules import dossier_blocks

d = data()
d['records'] = [
    row('t', 'tool_calls', arguments={'q': 'x'}, result='reply'),
    row('span', 'tool_calls', tool_description='Current call rule.'),
]
d['records'][0].update(name='lookup', span_ref='span')
d['records'][1].update(name='lookup', persisted_ref='t')
links = _axis_links('tool_execution', d, {})
print('Current call rule.' in json.dumps(material_view(d, links, [])))
print(dossier_blocks(d, links, 'tool_execution'))
# True
# []
```

**旧冻结样本也具有此形状，不是仅凭人工猜测**：在 `report/expectations-20261006/unit-format-full-live-20261007/result.json` 的 `axes.results[type_id=trace_analysis].output.dossier`：

- persisted call：`turn1/records/run/step_executor_runs/0/tools/0`；
- 对应 span：`turn1/records/traces/0/tree/0/spans/3/spans/2`；
- 后者 `scope=current`，`fields.tool_description.status=available`，正文 **389 字**；
- 枚举工具轴原文块得到 14 个 tools 块，全部来自 definitions，全部为 `observed_at_collection_not_verified_run_version`，没有上述当次说明。

这里只证明旧冻结材料上的确定性漏块，**没有重跑或推断本轮 live 的工具结论**。

**测试缺口**：`tests/test_axis_materials.py:145–161` 已验证 span 说明进入材料；`tests/test_design_rule_blocks.py:110–120` 只验证说明直接位于端点 row 的简化形状。两项各自通过，却没有覆盖这两个模块的接缝。

**最小修复方向**：枚举器复用既有配对关系，把同一次调用的 span 说明登记为有正确 owner/scope/ref/path 的候选块。不是扩大任意 readable 集，也不是把采集版升级为当次版本。

## R4 — P1：把首个模型请求中的最后一条 user 消息当作用户原话，可把预处理结果送入需求轴和 preparer

**位置**：`impl/projects/llm_probe/business_trace/expectation_material.py:39–64`。

**依据**：expectations v2 §2.1、§3：用户原话与本轮运行产出必须由程序投影隔离。首个**模型调用**不等于业务运行尚未发生；确定性步骤、Direct 查询或编排可能先执行再组织该调用。

只要首个模型请求有 user 消息，函数就优先采用它，完全不比较已经存在的外层 `normalized_request.body.message` / 当前轮请求。user 角色是模型输入角色，不能自动证明该字符串是终端用户原话。

```python
from types import SimpleNamespace
from impl.projects.llm_probe.business_trace.expectation_material import project_requirements

t = SimpleNamespace(
    normalized_request={'body': {'message': 'Tell me current status.'}},
    project_fields={'business_trace': {'records': {'calls': [
        {'pre': {'messages': [
            {'role': 'user',
             'content': 'PREPROCESSOR_RESULT=ACTIVE; tell the user ACTIVE.'}
        ]}}
    ]}}},
)
y = project_requirements(t)
print(y['sources'][0]['value'], y['missing'])
# PREPROCESSOR_RESULT=ACTIVE; tell the user ACTIVE. []
```

这份内容被标为 `want/user` 和 `scope=request`；真正原话不在 y_need 中，也没有来源冲突缺口。需求轴会据此提取 E，后续 `expectation_projection.prepare():72–78` 又把这些 sources 交给前置投影。由此不仅可能把路径指令写成需求，也可能让需求成为“交付已知答案 ACTIVE”。

**准确边界**：未发现 `project_design()` 或 llmtracing preparer 无条件读取第二次及之后调用的工具定义；那些隔离测试确实通过。本反例是更早的业务输出通过**第一次模型请求的 user 正文**进入需求材料，不是声称当前 live 已经发生泄漏。

**测试缺口**：`tests/test_expectations_v2_need_judge.py:56–74`、`tests/test_expectations.py:71–107` 检查系统消息、tools、post 和 later-call sentinel，但没覆盖“外层用户原话仍存在、首个模型 user 已被编排改写”。

**最小修复方向**：以现有外层用户请求为需求原话来源；模型请求消息用于建立经过核对的对应关系/历史上下文。两者不一致时不能静默把内部消息升级为原话；不可确认就明确缺料。无需新模型分类或启发式删除 sentinel。

## R5 — P2：需求 trace_ref 与 transcript 的消息编号算法不同，可把未送达需求判为已进入另一调用

**位置**

- `impl/projects/llm_probe/business_trace/expectation_material.py:42–52`
- `impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py:109–110,152–163`
- `impl/projects/llm_probe/business_trace/providers/llmtracing_evidence.py:237–249`

需求投影按原 messages 下标产生 `t1.c1.m{current+1}`；transcript 先把所有 system 消息分出去，再以 `len(system)+body_index+1` 编号。system 消息不全在列表开头时，二者会错位。

最小合法消息序列：

```text
c1: user("Earlier request."), system("Rule 1."),
    user("Tell me current status."), system("Rule 2.")
c2: system("Rule 1."), system("Rule 2."), user("Earlier request.")
```

实测：

```text
E 当前需求 trace_refs = ['t1.c1.m3']
transcript['t1.c1.m3'].text = 'Earlier request.'
c2 actual input 不含 'Tell me current status.'
```

provider 先检查 `source.trace_refs ∩ call.input_refs`，只要编号相交便不再检查内容。于是错误的旧 user 编号为当前需求提供了虚假的“已送达”证明。

完整入口复现（不是只调用宽松 helper）：

```python
import hashlib, json
from types import SimpleNamespace
from dataclasses import replace
from impl.core.tool_loop import History
from impl.projects.llm_probe.business_trace.expectation_material import project_requirements
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import build_transcript
from impl.projects.llm_probe.process_loop.llmtracing import TranscriptEvaluation
from tests.test_llmtracing_tool_loop import payload, common

def call(messages):
    return {'pre': {'messages': messages}, 'outcome': {'event': 'success',
        'response': {'choices': [{'message': {'content': 'answer'}}]}}}
def msg(role, content):
    return {'role': role, 'content': content}
q = 'Tell me current status.'
snapshot = {'status': 'complete', 'records': {'calls': [
    call([msg('user', 'Earlier request.'), msg('system', 'Rule 1.'),
          msg('user', q), msg('system', 'Rule 2.')]),
    call([msg('system', 'Rule 1.'), msg('system', 'Rule 2.'),
          msg('user', 'Earlier request.')]),
]}}
t = SimpleNamespace(normalized_request={'body': {'message': q}},
                    project_fields={'business_trace': snapshot})
y = project_requirements(t)
es = [dict(expectation_id='E1', source_refs=['t1.user'], about='status',
           statement=q, condition='always', ambiguity_group='')]
e = dict(sources=y['sources'], expectations=es,
    sha256=hashlib.sha256(json.dumps(es, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
p = dict(expectations_sha256=e['sha256'], data_needs=[dict(
    expectation_id='E1', need='none', reason='test', methods=[], missing=[])])
spec = common.PROCESS_SPECS['model_capability']
spec = replace(spec, obligations=tuple(o for o in spec.obligations
                                      if o.obligation_id == 'output_faithful'))
ev = TranscriptEvaluation(build_transcript(t, snapshot), {'model_capability': spec},
    None, None, expectations=e, projection=p, trace_id='readonly-review')
answer = payload('model_capability', instance=ev)
for u in answer['units']:
    if 'candidates' in ev.units['model_capability'][u['unit']]:
        u['matched'] = 't1.c2.response'
        for c in u['checks']:
            c.update(outcome='pass', fact='synthetic fulfilled requirement', missing=[])
ev.evidence.read(list(ev.evidence.records))
ev.post_batch_hook.post_batch(History(calls=[]), [])
print(ev._submitter('model_capability')(**answer))
# {'accepted': True, 'issues': []}
```

模型当次输入成员门禁被错误身份绕过，违背 v2 §6.3 的所有者/实际输入要求。普通 system-first fixture 和 `tests/test_process_v2_entrypoints.py:338–355` 的“需求内容不存在”测试不能覆盖这种**编号指向另一条真实消息**的情况。

**最小修复方向**：需求原文到 transcript 消息的映射使用同一套已建立的位置身份；不要两个模块各自猜编号。命中编号也须保证该编号确实承载声明原文。这是局部来源映射修复，不要求共享核心重构。

## R6 — P2：六轴消费端不校验 projection 属于同一份 E，ToolLoop 结果也缺少 E 指纹回执

**位置**

- `impl/projects/llm_probe/process_loop/expectation_projection.py:89–92,109–126`（收尾版本）
- `impl/projects/llm_probe/eval_axes/adapters/process_common.py:306–322,461–465`（收尾版本）
- `impl/projects/llm_probe/process_loop/evaluation.py:232–241,325–351`
- `impl/projects/llm_probe/process_loop/llmtracing.py:125–145,184–203`

**依据**：expectations v2 §3、§4、§8：消费者按同一 E 的 ID 与内容指纹引用，不能遗漏应检查需求。

`prepare()` 生成并保存 `expectations_sha256`，但 `required_units()`、两个接受外部 projection 的 evaluator 和案卷 runtime cache 都不核验它。最小失败：

```python
from tests.test_expectations_v2_need_judge import frozen
from impl.projects.llm_probe.process_loop.expectation_projection import required_units

e = frozen()  # 含 E1，且有真实计算的 sha256
print(required_units('intent_understanding', e,
    {'expectations_sha256': 'WRONG', 'data_needs': []}))
# []，没有拒绝；E1 的五项需求表达单位全部消失
```

`validate_submission()` 的覆盖清单来自同一次 `required_units()`，因此不能在后面补发现这个遗漏。同 ID、内容已更新但仍用旧投影也不会被拒。

案卷输出 `view.expectations_sha256` 直接复制当前 E 的 hash，而非证明缓存投影与 E 匹配；Agno ToolLoop 的各轴输出、llmtracing `_finish()` 的 view 则没有 E hash。正常冷启动的生产路径确实会把同一个 E 传下去，**本次没有观察到真实 run 混用了 E**；缺口在重放/直接构造/错误复用场景的机器约束与结果审计。

**已有成功**：主判 `need_judge.py:70–75` 真正重算并校验 E hash，`44–51` 验证响应 hash 与 ID 覆盖。因此不是主判仍在自推需求。

**测试缺口**：`tests/test_expectations.py:377–384` 只检查缓存共享；不少六轴 fixture 使用占位 hash / 空 projection，未测试非空 E 与错误投影指纹的拒绝。

**最小修复方向**：在消费已有投影的边界核验 E 内容、投影 hash 和 data_needs 的精确覆盖；结果由程序附上实际消费的 E 指纹。不要让模型重复计算 hash，不需要版本配置层或兼容格式。

## R7 — P2：需求轴支持的场景 criterion / description 在正常配置保存路径被静默丢弃

**位置**

- 新消费：`impl/projects/llm_probe/business_trace/expectation_material.py:66–74`
- 保存规范化：`impl/core/capability_store.py:48–129,231–235`

**依据**：expectations v2 §2.1：已配置场景判准必收，业务描述已配置则收。

投影读取顶层 `scenario.criterion` 和 `scenario.description`；实际保存入口调用 `validate_entry()`，它从 `{'capability': ...}` 重建 clean，只复制原先几个字段，没有保留这两个新消费字段。

```python
from impl.core.capability_store import validate_entry
print(validate_entry('reviewcase', {
    'capability': 'Unsplit legacy background',
    'criterion': 'Deliver A',
    'description': 'User-facing service',
}))
# {'capability': 'Unsplit legacy background'}
```

所以直接手工构造 scenario 的需求测试可以通过，使用既有资料管理保存接口却会丢掉判准/描述；若文件中已人工登记这些字段，后续普通保存同样会清除它们。`partial: capability 未拆分` 不能替代保存这些显式登记的需求材料。

**边界**：不要求本轮完成 capability 拆分 UI 或 downstream 消费；任务允许 downstream 只占位甚至暂不修改形状校验，本报告不把它暂未实现列为失败。问题仅是**已经实现并宣称可消费的 criterion / description 缺少持久化接缝**。

**最小修复方向**：现有配置规范化接口保留并校验这两个字段，补一项“validate_entry → project_requirements”测试。无需新配置抽象或迁移。

---

## 已做对的部分，以及不能夸大的结论

1. **移除全局承诺重写链路**：当前运行源码没有 `ContractBinding` / `Join.contracts` / `tool_expectation_ids` / `attach_criteria` 的旧消费实现。设计原文不再由需求轴拆为 160+ 承诺。不能据此推算本轮耗时收益，须等真实测量。
2. **需求侧大部分白名单正确**：系统声明、tools、输出格式、后续调用输出不作为常规 y_need 成分；背景/历史不能独立产需求；存在 capability 时即使有用户原话仍 partial。证据见 `tests/test_expectations_v2_need_judge.py:56–105`。R4 是尚未堵住的来源身份接缝。
3. **前置工具材料没有直接借后续调用**：`project_design():151–177` 限定每轮首个调用的 typed declarations；llmtracing `run_evaluation()` 也选每轮首个 call。`tests/test_design_rule_blocks.py:32–57`、`tests/test_process_v2_entrypoints.py:314–329` 已锁定这点。不能把“未直接读取后续调用”扩大成“所有前置材料都已证明无本轮产出”。
4. **三入口的模型输出 schema 已统一**：案卷批次、Agno ToolLoop、llmtracing ToolLoop 共享 `AxisJudgment` / `validate_submission`；旧 `ProcessAssessment` 路径已删除。provider 特有的原始工具返回、HTTP 实收、call input membership 门禁仍保留，未把任意 `design:` 前缀当证据放行。
5. **默认值修复不是兼容 fallback**：`process_output.py:150–151` 先严格 enforce，再由同一 dataclass 的 Pydantic adapter 实例化合法默认值；`Necessity` 禁止额外字段。省略可选字段可用，非法额外字段、null、类型、缺 blocks 仍拒绝。见 `tests/test_process_unit_output.py:116–160` 及本次通过的 v2 反例测试。没有理由要求启用用户已排除的 response_format。
6. **显式设计引文能保留条件**：多位置引文和 E 的 condition 在正常分支中保留到单位、问题及 summary，见 `tests/test_process_v2_rules.py:139–150`。R2 指的是某些登记路径不是真实原文子树，不是否定所有引文验证。
7. **运行版本/所有者门禁有实质约束**：逐条设计规则 pass/fail 要求 `actual_input/execution` 且当前 target 属于 block.link_ids；模型轴进一步限制 actual_input；采集版定义不能直接证明违约。`tests/test_process_v2_rules.py:157–203`、`tests/test_design_rule_blocks.py:123–138` 通过。未确认 owner 的规则降为参考是正确的，但不等于所有 link 的旧 owner 假设已经修复。
8. **四问不再由有工具直接推出必须调用**：`external/none/unknown` 与 `satisfied/required/unknown` 分阶段；satisfied 要证据且从实际行使汇总移出、unknown 留缺证、required 不可 not_applicable。未发生 required 的未定位问题与先取得上游 accepted 回执的顺序都有测试。接受人工给定的必要性结论，不代表真实模型已能准确判断缓存/刷新。
9. **主判的项目局部实现合理**：`need_judge.py:70–110` 在看实际前单独投影 blocking，交付判断逐条使用相同 E，公共 `BusinessExpectation` 由程序原样投影，不是模型自推的新需求。主判通常新增一次 blocking 调用，应计入 live 成本。用户已批准其他项目及未接 E 的路径可暂缓，不把 `judge.py:137–141` 的明确项目分流当作违规兼容层。
10. **共享存储 ID 隔离修复正确**：`materials.py:14–20,140–142` 使用 `shared#N`，不会与原 `content#N` 混淆；测试 `test_design_rule_blocks.py:250–261` 通过。没有为此扩大可引用证据集合。
11. **评测器失败没有被自动补为业务 pass**：案卷批次的二次非法输出记 evaluator failure，清空能力 verdict，保留已过批次仅作诊断（收尾版 `process_common.py:468–474`）；ToolLoop 失败不采用最后一段自然语言当结论。这与 R1 的错误问题归属是两件事。

### 机械保证与语义限度

- 可以机械保证：schema、精确单位/C 覆盖、B 清单标注、逐字摘录、已登记来源/owner/scope、已读回执、上游引用存在、E 身份匹配。上述 R1–R3/R5/R6 正是这些可执行保证的缺口，不能推给独立语义审阅。
- 无法仅凭这些保证：规则是否被完整理解、截取是否遗漏另一句条件、数据/示例是否被误当规则、缓存是否真的有效、问题影响是否正确。`tests/test_process_v2_rules.py:270–284` 和 `tests/test_process_prompt_contract.py:201–214` 有意保存错误的块处理理由供审阅，这是正确承认语义限度，不能据“每块有标注”宣称规则全部核实。
- `verbatim_arrival()` 的程序 pass 是既有“原文完整包含”的机器事实检查，不是新增的全业务语义认证；本报告没有把它等同于模型已理解所有规则，也没有把单纯聚合优先序本身称为造假。R1 的证据是实际丢失/错误升级的依赖与归属。

### 小项与审计注意，不扩大为架构任务

- `impl/projects/llm_probe/process_contract.py:79–97` 仍保留未被运行代码引用的旧 `SUBMISSION_GUIDE`，包含旧提交字段与 expectation-only 说法。可直接删除死文本；当前未发现它被注入新 prompt，不将其计为运行阻塞问题。
- `impl/projects/llm_probe/process_loop/llmtracing_report.py:18–35` 的实现指纹文件表尚未纳入新依赖 `process_output.py`、`design_rules.py`，也未纳入本入口导入的 `evaluation.py` 端点校验。后续只修改这些文件，该报告指纹无法反映校验语义变化。应补现有依赖表，不另建版本系统；本次没有通过改源文件实测指纹变化。
- `links.py:219` 仍有未知 owner 时取同轮首 run 的旧行为。新 design block 对不匹配 owner 降为参考是改进，但不要据此宣称旧 link 的所有者问题全部消失。本次没有将未证实的业务误归属追加成独立 finding。

## 只读复现守护

本次 pytest 采用以下形式；把文件名替换为上表所列两组即可。各 R 的纯 Python 片段也可放在 audit hook 后运行，不需要生成脚本或 fixture 文件。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/Users/xiaozijian/miniconda3/envs/agno/bin/python -B - <<'PY'
import os, sys

def guard(event, args):
    if event == 'open':
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+'))
        writing |= (isinstance(flags, int) and bool(flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        if writing:
            raise RuntimeError('read-only review: write blocked: ' + str(path))
    if event in {
        'os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.link', 'os.symlink',
        'os.truncate', 'os.chmod', 'os.utime', 'subprocess.Popen', 'os.system',
        'socket.connect', 'socket.bind', 'socket.sendto', 'socket.getaddrinfo',
    }:
        raise RuntimeError('read-only offline review: blocked ' + event)

sys.addaudithook(guard)
import pytest
raise SystemExit(pytest.main([
    '-q', '-s', '-p', 'no:cacheprovider', '-p', 'no:logging', '--assert=plain',
    'tests/test_process_v2_rules.py', 'tests/test_process_unit_output.py',
    'tests/test_design_rule_blocks.py', 'tests/test_process_v2_entrypoints.py',
    'tests/test_expectations_v2_need_judge.py', 'tests/test_process_criterion_checks.py',
]))
PY
```

## 审阅版本定位

工作区包含大量其他人的未提交变更，不能把整份 git diff 当作本任务改动。初查、反例执行及写报告前一次复核时下列 SHA 一致；**写入报告后的收尾复核发现其中三个文件被并发更新**，已重新读取、运行上文复核并记录第二组 SHA。正文涉及变动位置处已注明收尾行号；R2 的扁平化反例特意保留为初审历史证据。

| 文件（相对 `impl/projects/llm_probe/`） | 初审 SHA-256 |
|---|---|
| `eval_axes/adapters/process_output.py` | `bd70cef8150c706b519457a08b0c504ae7afa37905cc197b646cacb70a24d19e` |
| `process_loop/expectation_projection.py` | `68f7ee735c9286fc36dd44724d9a8b689082ce2a6c398eb4aaa40f15734e2fe4` |
| `eval_axes/adapters/process_common.py` | `e1a590f6c6eb9920b0e9b6cdcab2ed68774108653f593536e29838449149ea12` |
| `business_trace/design_rules.py` | `3e89bdc7936fefdf41de132e2f0e07d99279f67cffd1bfa8a0e3db319ead3d61` |

| 文件 | 收尾 SHA-256 / 变化 |
|---|---|
| `process_loop/expectation_projection.py` | `45a5868fdd1cd640ad11e723c88cd46c70887f1057c347f8a1c83d980470fc64`；preparer 使用 B 短编号并回填原文位置，未补 R6 的消费身份校验 |
| `eval_axes/adapters/process_common.py` | `f7686305f8997f639d66b04ef02927519c286b4277a93508186b3da4dbe0a446`；缓存前置准备失败，避免各轴重复调用同一失败准备；仍保留 evaluator error，不补业务结论 |
| `business_trace/design_rules.py` | `1d8f760deca676bb5103ca503d33ca0a1d87f7efffef81443061b9ed46ae5a1a`；R2 fields 子树路径修复 |

`process_output.py`、两个 ToolLoop 入口、`llmtracing_evidence.py`、`expectation_material.py`、`need_judge.py` 收尾哈希未变。本报告的结论截止这些快照；不追认之后的并发修改或 live 结果。

## 修复优先级

1. **P1：先保住原子结论与需求来源边界**——修 R1 的上游/未定位归属，修 R4 的内部消息冒充原话；不能靠改结论过校验。
2. **P1：补原文机械闭环**——保留 R2 已修的真实路径，关闭剩余字段剪裁问题；修 R3 的当次配对 span 漏块。
3. **P2：固定身份**——修 R5 的消息映射、R6 的 E/投影指纹和覆盖核验，补已有实现指纹依赖表。
4. **P2：接通场景保存**——修 R7 的 criterion / description 保留，补接缝测试并处理最新 1 项文案断言失败；之后按事实核对当前 live，不用初审 407 passed 或收尾 406 passed 替代真实验收。
