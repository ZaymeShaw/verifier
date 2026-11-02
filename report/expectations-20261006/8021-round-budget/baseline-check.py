from pathlib import Path
import json,hashlib,sys
r=Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier');s=Path('/private/tmp/verifier-analysis-round-budget');sys.path.insert(0,str(r))
base=json.loads((s/'baseline.json').read_text())
old=Path('/private/tmp/expectations-implementation/impl/core/tool_loop/runtime.py').read_text()
assert hashlib.sha256(old.encode()).hexdigest()==base['impl/core/tool_loop/runtime.py']
from impl.core.tool_loop import runtime
ns={'__name__':runtime.__name__,'__package__':runtime.__package__};exec(compile(old,'original-runtime.py','exec'),ns)
original=ns['ToolLoop']
runtime.ToolLoop.run=original.run
runtime.ToolLoop._failed=staticmethod(original._failed)
from impl.tool_loop_lab import observation
text=(r/'impl/tool_loop_lab/observation.py').read_text()
for line in ["        def ready_to_finish(self, history): return self.invoke('ready_to_finish', history)\n","        # budget 也由同一观察器包装；请求前预算与反馈必须原样透传。\n","        def before_step(self, history): return self.invoke('before_step', history)\n","        def step_note(self, history): return self.inner.step_note(history)\n"]:
 assert text.count(line)==1; text=text.replace(line,'')
assert hashlib.sha256(text.encode()).hexdigest()==base['impl/tool_loop_lab/observation.py']
exec(compile(text,'original-observation.py','exec'),observation.__dict__)
print('Original runtime and observation hashes verified; isolated baseline, repository unchanged',flush=True)
import pytest
sys.exit(pytest.main(['-q','tests/test_tool_loop_lab.py::test_clustering_loop_delivers_a_complete_visual_artifact']))
