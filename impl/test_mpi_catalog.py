#!/usr/bin/env python3
"""
测试 MPI attribute 的 source_file_catalog 是否包含 intent_prompt.py
"""
import sys
from pathlib import Path

# Add impl to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from impl.core.project_loader import load_adapter, load_project
from impl.tools.source_retrieval import ProjectSourceFileProvider

# Load MPI project
spec = load_project('marketting-planning-intent')
print(f"Project: {spec.project_id}")
source = ((spec.project.get("resources") or {}).get("source") or {})
print(f"External repo: {source.get('repository')}")
print()

# Simulate build_attribute_context
adapter = load_adapter(spec)

# Mock trace with intent_api_call failure
class MockTrace:
    execution_trace = [
        {'stage': 'request_normalization', 'status': 'ok'},
        {'stage': 'intent_api_call', 'status': 'ok'},
        {'stage': 'label_mapping', 'status': 'failed', 'evidence': 'intent=other'}
    ]
    project_fields = {'reference': {'intent': 'nbev_planning'}}
    reference_contract = {}

trace = MockTrace()

# Build attribute context
from impl.core.judge import JudgeResult
judge_result = JudgeResult(
    trace_id='test',
    project_id='marketting-planning-intent',
    verdict='incorrect',
    score=0,
    confidence=1,
    judge_method='test'
)

project_attribute_context = adapter.build_attribute_context(trace, judge_result)
print(f"source_config_paths count: {len(project_attribute_context.get('source_config_paths', {}))}")
print()

# Build source file catalog
provider = ProjectSourceFileProvider(spec, project_attribute_context)
catalog = provider.list_files()

print(f"=== Source File Catalog ({len(catalog)} files) ===")
for i, entry in enumerate(catalog, 1):
    key = entry['key']
    path = Path(entry['path'])
    size = entry['size_chars']
    desc = entry.get('description', '')
    print(f"{i}. {key}")
    print(f"   Path: {path.name}")
    print(f"   Size: {size:,} chars")
    if 'intent' in path.name.lower() or 'prompt' in path.name.lower():
        print(f"   ⭐ INTENT/PROMPT FILE!")
    print()

# Check if intent_prompt.py is in the catalog
intent_prompt_found = any('intent_prompt' in entry['key'] for entry in catalog)
print(f"✅ intent_prompt.py in catalog: {intent_prompt_found}")
print()

# Test reading a file
if catalog:
    first_key = catalog[0]['key']
    print(f"=== Test reading: {first_key} ===")
    content = provider.read_file(first_key)
    if content:
        print(f"Content length: {len(content)} chars")
        print(f"First 200 chars: {content[:200]}")
    else:
        print("❌ Failed to read file")
