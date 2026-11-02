"""直接修改这里的 Python 构造函数，再点运行；无需改页面或 ToolLoop。

服务只加载此可信文件，不接受网页上传的代码/模块路径。每次加载和运行独立构造实例。
"""
from __future__ import annotations

import json
import runpy
from pathlib import Path
from dataclasses import dataclass

from impl.core.structured_output import StructuredOutputSpec, enforce_output
from impl.core.tool_loop import (
    BudgetStop, DependsOn, Hook, RequireDone, Step, ToolLoop, cites_read, take_accepted,
)
from impl.tools.protocol import VerifiableTool

MATERIALS = {'note': '演示设备的维护窗口是周三 14:00–16:00，变更前需要通知值班人员。'}


@dataclass
class Submission:
    answer: str
    evidence_ids: list[str]


OUTPUT = StructuredOutputSpec.from_dataclass(Submission, required_nonempty=['answer', 'evidence_ids'])
SUBMIT_PARAMETERS = OUTPUT.json_schema()
SUBMIT_PARAMETERS['properties']['answer']['description'] = '基于材料的回答正文'
SUBMIT_PARAMETERS['properties']['evidence_ids']['description'] = '支持回答的材料编号，必须非空且已经读取'


def read_tool():
    material = dict(MATERIALS)
    def read_material(id: str):
        if id not in material:
            raise ValueError('材料编号不存在；可用编号：' + ', '.join(material))
        return {'id': id, 'text': material[id]}
    return VerifiableTool('read_material', '读取本次试验提供的演示材料。不会访问业务服务或文件系统。',
                          parameters={'type': 'object', 'properties': {'id': {'type': 'string', 'description': '材料编号：note'}},
                                      'required': ['id']}, execute_fn=read_material)


def build_basic(client):
    return ToolLoop('lab_basic',
        '你是一个材料问答助手。根据用户任务决定是否使用 read_material。材料编号为 note。回答用户问题。',
        [read_tool()], client,
        completion_hook=Hook(),  # 明确接受模型自行结束，不强制提交 JSON。
        budget=BudgetStop(tool_calls=8, seconds=1200))


def build_checked(client):
    material_ids = set(MATERIALS)
    def submit(**payload):
        try:
            enforce_output(payload, OUTPUT, caller='lab.submit')
            if not set(payload['evidence_ids']) <= material_ids:
                raise ValueError('引用了不存在的材料编号')
        except (ValueError, TypeError, KeyError) as error:
            return {'accepted': False, 'error': str(error)}
        return {'accepted': True}
    submit_tool = VerifiableTool('submit', '提交最终回答。返回 accepted=true 才表示被接受；否则根据 error 修正后重新提交。',
                                 parameters=SUBMIT_PARAMETERS, execute_fn=submit)
    return ToolLoop('lab_checked',
        '根据演示材料回答用户。可读材料编号 note。用 submit 提交 answer 和 evidence_ids；'
        '引用的材料必须在前一批工具调用中读过。提交被拒时依据具体原因修正，接受后结束。',
        [read_tool(), submit_tool], client,
        completion_hook=RequireDone(['submit']),
        hooks={'pre_tool': [DependsOn({'submit': cites_read('evidence_ids', 'read_material', 'id')})]},
        end=take_accepted('submit'),
        max_blocked=3, budget=BudgetStop(tool_calls=12, seconds=1200))


EXAMPLES = {
    'basic': {'title': '普通工具循环', 'description': '模型读取材料并回答；核心 hook 接受模型自行结束。',
              'input': '请读取 note，告诉我设备何时维护，需要先通知谁？', 'build': build_basic, 'script_client': lambda: ScriptClient('basic')},
    'checked': {'title': '提交与结束检查', 'description': '体验提前结束被拦回、未读引用被拒、无效提交及最终接受。',
                'input': '请基于 note 回答设备何时维护，并提交回答和引用编号。', 'build': build_checked, 'script_client': lambda: ScriptClient('checked')},
}


class ScriptClient:
    """固定回复的模型替身：不理解用户输入、不调用真实模型，用于体验控制流程。"""
    def __init__(self, example_id):
        def tool(name, args):
            return {'role': 'assistant', 'tool_calls': [{'id': name, 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]}
        answer = '周三 14:00–16:00 维护，变更前通知值班人员。'
        read = tool('read_material', {'id': 'note'})
        final = {'role': 'assistant', 'content': answer}
        self.steps = iter([read, final] if example_id == 'basic' else [
            {'role': 'assistant', 'content': '我想结束了。'},
            tool('submit', {'answer': answer, 'evidence_ids': ['note']}),  # 未读引用，被前置 hook 拒绝。
            read,
            tool('submit', {'answer': answer, 'evidence_ids': []}),  # 有效读取后仍提交坏结构，工具拒绝。
            tool('submit', {'answer': answer, 'evidence_ids': ['note']}),
            {'role': 'assistant', 'content': '提交已接受，任务完成。'},
        ])
        self.index = 0

    def complete_step(self, messages, functions, **kwargs):
        self.index += 1
        message = next(self.steps)
        for call in message.get('tool_calls', []):
            call['id'] = 'demo-' + str(self.index)
        return Step(message)


# 固定可信示例文件，每次运行都重新加载；请求不能指定任意模块路径。
EXAMPLES['clustering'] = runpy.run_path(str(Path(__file__).with_name('clustering_example.py')))['EXAMPLE']
