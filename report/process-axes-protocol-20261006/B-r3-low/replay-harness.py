from dataclasses import replace
from pathlib import Path
import runpy,sys
from impl.core import config
from impl.core.config_schema import LlmRolePolicyOverride
resolved=config.get_runtime_config()
policies=dict(resolved.llm.role_policies)
policies['judge']=replace(policies.get('judge',LlmRolePolicyOverride()),reasoning_effort='low')
config._RUNTIME_CONFIG=replace(resolved,llm=replace(resolved.llm,role_policies=policies))
sys.argv=['scripts/replay_process_protocol.py','--trace','report/llmtracing-calibration-draft/frozen-inputs/B.trace.json','--old','report/llmtracing-calibration-draft/process-baseline-v0/B/result.json','--out','report/process-axes-protocol-20261006/B-r3-low']
runpy.run_path('scripts/replay_process_protocol.py',run_name='__main__')
