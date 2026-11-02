"""Insurance 验证实例 18066：Langfuse + Agno 同时上报，供 llm_probe_loop 的 verify-insurance-agno / -langfuse 场景。

原样恢复自 10-18 端到端实测用的 /private/tmp/langfuse-handoff/start_validation_app.py（该目录已被系统清掉）。
代码取评测工作树；配置复制到状态目录后改两处：模型走本机网关 4202、tracing_enabled=true；Langfuse 配置取
langfuse-deploy/.insurance-content-test.json。状态目录与 knowledge_sources.json 里 agno-insurance 的 sqlite_path 一致。

依赖：模型网关 4202（llm_gateway/start_insurance_litellm.sh --profile insurance_verifier_4202）、Langfuse 3300（langfuse-deploy/manage.sh start）。
启动（在评测工作树目录、用其主仓库 venv、-I）：
  cd <AGENT_DIR> && NO_PROXY=127.0.0.1,localhost,::1 no_proxy=127.0.0.1,localhost,::1 \
    <insurance-qa-agent>/.feval_venv/bin/python -I <本文件>
"""
import os, sys, json, shutil
from pathlib import Path
root = Path('/Users/xiaozijian/WorkSpace/package/insurance_qa_agent/insurance-qa-agent-eval')
state = Path('/private/tmp/langfuse-handoff/real-validation'); state.mkdir(mode=0o700, parents=True, exist_ok=True)
sys.meta_path[:] = [f for f in sys.meta_path if '__editable__' not in getattr(f, '__module__', '')]
sys.path.insert(0, str(root)); os.chdir(root); os.environ['ENV_TYPE'] = 'dev'
os.environ['IQA_EVAL_HEADER_PASSTHROUGH'] = '1'
import yaml
conf = state / 'conf'
if not conf.exists():
    shutil.copytree(root / 'app/conf', conf, ignore=shutil.ignore_patterns('__pycache__', '*.py'))
(conf / 'langfuse').mkdir(exist_ok=True)
lcfg = json.loads(Path('/Users/xiaozijian/WorkSpace/package/langfuse-deploy/.insurance-content-test.json').read_text())
(conf / 'langfuse/langfuse_dev_args.yaml').write_text(yaml.safe_dump(lcfg))
for rel, updates in [('models/models_dev_args.yaml', {'base_url': 'http://127.0.0.1:4202/v1'}), ('harness/harness_dev_args.yaml', {'tracing_enabled': True})]:
    p = conf / rel; j = yaml.safe_load(p.read_text()); j.update(updates); p.write_text(yaml.safe_dump(j, allow_unicode=True))
for p in conf.rglob('*'):
    if p.is_file(): p.chmod(0o600)
import app.conf as config
config.CONF_DIR = conf; config.TOOL_CONFIG_DIR = conf / 'tool'
# Local validation client only: direct loopback transport, no system proxy edits.
from urllib.parse import urlsplit
from openai import DefaultAsyncHttpxClient
import app.runtime.model_transport as transport
OriginalClient = transport.ManagedAsyncOpenAI
class LoopbackValidationClient(OriginalClient):
    def __init__(self, *args, **kwargs):
        assert urlsplit(str(kwargs["base_url"])).hostname in {"127.0.0.1", "localhost", "::1"}
        kwargs["http_client"] = DefaultAsyncHttpxClient(trust_env=False)
        super().__init__(*args, **kwargs)
transport.ManagedAsyncOpenAI = LoopbackValidationClient
from app.main import create_app
from app.runtime.database import runtime_db
import uvicorn
app = create_app(tool_config_path=str(conf / 'tool/tool_config_dev_args.yaml'), trusted_body_identity=True, db=runtime_db(str(state / 'runtime.db')))
assert app.state.langfuse_runtime is not None
print('VALIDATION_READY port=18066 Langfuse+Agno enabled', flush=True)
uvicorn.run(app, host='127.0.0.1', port=18066, log_config=None)
