"""process_loop 两个实例共用的小件：取证工具的 VerifiableTool 形态、基于现有 prompt 的受检改写。"""
from __future__ import annotations

from typing import Mapping

from impl.projects.llm_probe.business_trace.tools import EvidenceIndex, build_dossier_tools
from impl.tools.protocol import VerifiableTool


def dossier_tools(index: EvidenceIndex) -> list[VerifiableTool]:
    """build_dossier_tools 的同一组取证工具（名字、说明、参数、回执都不变），还原成 ToolLoop 要的 VerifiableTool。"""
    return [VerifiableTool(tool_id=fn.entrypoint.logical_tool_id, description=fn.description,
                           parameters=fn.parameters, execute_fn=fn.entrypoint)
            for fn in build_dossier_tools(index)]


def derive_prompt(base: str, replacements: Mapping[str, str]) -> str:
    """在现有 prompt 上替换与 loop 协议冲突的句子。原句必须恰好出现一次：原 prompt 改了就在导入时报错，不静默漂移。"""
    text = base
    for old, new in replacements.items():
        count = text.count(old)
        if count != 1:
            raise ValueError(f"derive_prompt：原句应恰好出现一次，实际 {count} 次：{old[:40]}")
        text = text.replace(old, new)
    return text
