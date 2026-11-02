"""Model-facing process vocabulary. IDs, schema enums and descriptions share one source."""
import json
from typing import Literal, get_args

AxisId = Literal['intent_understanding', 'planning_routing', 'tool_execution',
                 'knowledge_data', 'model_capability', 'context_memory']
AXIS_DESCRIPTIONS = {
    'intent_understanding': '意图表达：用户原文到系统内部任务表达，核对对象、目标、条件和全部子问题。',
    'planning_routing': '规划编排：任务与当时状态到路径、调用顺序、重试和结束决定。',
    'tool_execution': '工具执行：实际调用参数到工具、后端或子任务的返回，核对执行及适用契约。',
    'knowledge_data': '知识数据：本次查询所需的外部事实是否给出，对象、版本和时点是否匹配。',
    'model_capability': '模型行为：每次模型实际收到的输入到该次完整输出，只使用该次已收到的规则。',
    'context_memory': '上下文传递：一处产出到下一处实际输入，核对组装、历史、状态和最终交付。',
}
assert set(get_args(AxisId)) == set(AXIS_DESCRIPTIONS)
AXIS_GUIDE = '\n'.join(f'{key}：{value}' for key, value in AXIS_DESCRIPTIONS.items())


def source_in_inputs(source: dict, inputs: list) -> bool:
    """Compare declared content with this call only, without treating config wrappers as wire keys."""
    def contains(body, value):
        if body == value:
            return True
        if isinstance(body, str) and isinstance(value, str):
            return bool(value) and value in body
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError:
                return False
        if isinstance(body, dict):
            if isinstance(value, dict) and value and all(k in body and contains(body[k], v) for k, v in value.items()):
                return True
            return any(contains(v, value) for v in body.values())
        if isinstance(body, list):
            return any(contains(v, value) for v in body)
        return False

    value = source['value']
    if source.get('component') == 'system':
        if isinstance(value, dict):
            if not value or not set(value) <= {'instructions', 'system_message'}:
                return False
            texts = []
            for part in value.values():
                if isinstance(part, str):
                    texts.append(part)
                elif isinstance(part, list) and all(isinstance(x, str) for x in part):
                    texts.extend(part)
                else:
                    return False
        elif isinstance(value, str):
            texts = [value]
        else:
            return False

        def system_bodies(body):
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except ValueError:
                    return []
            if isinstance(body, list):
                return [content for item in body for content in system_bodies(item)]
            if not isinstance(body, dict):
                return []
            if body.get('kind') == 'system' and body.get('origin') == 'model_request':
                return [body.get('text', '')]
            if body.get('role') == 'system':
                return [body.get('content', '')]
            return [content for key in ('messages', 'exact_request') if key in body
                    for content in system_bodies(body[key])]

        delivered = [text for body in inputs for text in system_bodies(body)]
        return bool(texts) and all(text and any(contains(body, text) for body in delivered) for text in texts)
    return any(contains(body, value) for body in inputs)
