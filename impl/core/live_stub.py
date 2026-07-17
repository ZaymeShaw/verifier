"""系统扮演模块：按 live_schema.EXTRACT_OUTPUT_SCHEMA dataclass 构造合法 output。

用于 ready 含 output 但没有真实 live 可调的场景——让 LLM 扮演被测系统，
根据用户意图产出"合理但不一定严谨"的回答（弱模型，不开深度思考）。

输入信息量：固定的一句话系统简介 + 10% 随机系统信息（按句子边界采样，模拟 output 侧
对系统了解程度是一个分布——可能一无所知，也可能较为了解）。
"""
from __future__ import annotations

import json
import random
import dataclasses
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .mock_agent import load_live_schema
from .structured_output import StructuredOutputSpec

if TYPE_CHECKING:
    from .llm_client import LlmClient


def _split_sentences(text: str) -> List[str]:
    """按中文句号/分号/换行切分句子，过滤空串。"""
    if not text:
        return []
    import re
    parts = re.split(r"[。；\n]", text)
    return [p.strip() for p in parts if p.strip()]


def _system_brief(project_id: str) -> str:
    """一句话系统简介（固定，来自 mock_agent 的 _BUSINESS_CONTEXT 首句）。"""
    from .mock_agent import MockAgent
    ctx = MockAgent._BUSINESS_CONTEXT.get(project_id, "")
    if not ctx:
        return f"项目业务：{project_id}"
    # 取首句作为简介
    sentences = _split_sentences(ctx)
    return sentences[0] if sentences else ctx


def _system_full_info(project_id: str, spec: Any) -> str:
    """系统完整信息（用于 10% 随机采样）：_BUSINESS_CONTEXT 全文 + evaluation 文档摘要。"""
    parts: List[str] = []
    from .mock_agent import MockAgent
    ctx = MockAgent._BUSINESS_CONTEXT.get(project_id, "")
    if ctx:
        parts.extend(_split_sentences(ctx))
    # 追加 evaluation 文档的句子（如果 spec 可用）
    if spec is not None:
        try:
            from .project_loader import load_project_document
            evaluation = load_project_document(spec, "evaluation")
            if evaluation:
                parts.extend(_split_sentences(evaluation))
        except Exception:
            pass
    return "\n".join(parts)


def _sample_random_info(full_info: str, ratio: float = 0.1) -> str:
    """从完整系统信息里按 ratio 比例随机采样句子（按句子边界，不碎片化）。"""
    sentences = _split_sentences(full_info)
    if not sentences:
        return ""
    k = max(1, round(len(sentences) * ratio)) if sentences else 0
    k = min(k, len(sentences))
    sampled = random.sample(sentences, k)
    return "\n".join(sampled)


class LiveStubGenerationError(RuntimeError):
    pass


class LiveStubSchemaError(RuntimeError):
    pass


def _schema_errors(project_id: str, output: Dict[str, Any]) -> List[str]:
    ls = load_live_schema(project_id)
    if ls is None or not hasattr(ls, "check"):
        return []
    checker = ls.check
    if hasattr(checker, "_output_validator"):
        return checker._output_validator.errors(output, strict=True, allow_extra=False)
    return [] if checker.output(output) else ["output 不符合 EXTRACT_OUTPUT_SCHEMA"]


def generate_live_output(
    spec: Any,
    intent: Dict[str, Any],
    project_id: str,
    llm: Optional[LlmClient] = None,
) -> Optional[Dict[str, Any]]:
    """LLM 扮演被测系统，按 EXTRACT_OUTPUT_SCHEMA 产出合理回答（可能不严谨）。
    弱模型：model=deepseek-chat, reasoning_effort=low。
    输入信息量：固定一句话简介 + 10% 随机系统信息。
    """
    live_schema = load_live_schema(project_id)
    dataclass_cls = getattr(live_schema, "EXTRACT_OUTPUT_SCHEMA", None) if live_schema is not None else None
    if dataclass_cls is None:
        raise LiveStubGenerationError(f"{project_id} 缺少 EXTRACT_OUTPUT_SCHEMA")

    brief = _system_brief(project_id)
    full_info = _system_full_info(project_id, spec)
    random_info = _sample_random_info(full_info, ratio=0.1)

    system = (
        "你扮演被测业务系统，根据用户意图产出系统侧响应（actual output）。\n"
        "你的回答应当合理但不必严谨——受限于系统能力，可能正确也可能有偏差。\n"
        f"系统简介：{brief}\n"
    )
    if random_info:
        system += f"你对系统的部分了解：{random_info}\n"
    system += "输出 JSON，只含格式模板定义的字段。"

    user = json.dumps({
        "user_intent": intent.get("input", {}),
        "user_intent_summary": intent.get("user_intent"),
        "scenario": intent.get("scenario", ""),
    }, ensure_ascii=False)

    # spec/struct_output.md：构造 output_spec，传入 complete_json 做强制约束
    output_spec = StructuredOutputSpec.from_dataclass(
        dataclass_cls,
        description="live_stub 系统扮演 output",
    )

    if llm is None:
        from .llm_client import LlmClient
        client = LlmClient()
    else:
        client = llm
    client._project_id = project_id
    client._caller = "live_stub"
    trace_id = f"live-stub-{project_id}-{random.randint(0, 999999)}"
    data = client.complete_json(
        system, user, trace_id=trace_id,
        model="deepseek-chat",
        reasoning_effort="low",
        output_spec=output_spec,
    )
    if data.get("error"):
        raise LiveStubGenerationError(str(data.get("error")))
    output = data.get("output")
    if not isinstance(output, dict) or not output:
        # 兼容：LLM 可能直接把字段铺在顶层。用 dataclass 字段名兜底
        field_names = [f.name for f in dataclasses.fields(dataclass_cls)]
        output = {k: data.get(k) for k in field_names if data.get(k) is not None}
    if not output:
        raise LiveStubGenerationError("live_stub 未生成 output")
    return output


def generate_live_output_with_check(
    spec: Any,
    intent: Dict[str, Any],
    project_id: str,
    llm: Optional[LlmClient] = None,
) -> Optional[Dict[str, Any]]:
    """生成 output 并通过 live_schema.check.output() 强校验。"""
    output = generate_live_output(spec, intent, project_id, llm=llm)
    schema_errors = _schema_errors(project_id, output)
    if schema_errors:
        raise LiveStubSchemaError(f"{project_id} live_stub output 不符合 EXTRACT_OUTPUT_SCHEMA: {schema_errors}")
    return output
