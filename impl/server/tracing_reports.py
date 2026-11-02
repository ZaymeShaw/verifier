"""Render the workspace's captured model traffic using the existing tracing CLI."""
from pathlib import Path
import subprocess
import sys
import tempfile
from ..core.instances import tracing_root

ROOT = Path(__file__).resolve().parents[2]


def render_report(project: str) -> str:
    # Each HTTP request gets a separate export directory: concurrent clicks and
    # projects cannot overwrite a report while another response is reading it.
    parent = tracing_root() / 'reports'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='web-', dir=parent) as directory:
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/tracing.py'), 'report',
             '--project', project, '--out', directory],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 1:
            raise FileNotFoundError(result.stderr.strip() or '当前用例池没有可用的模型请求记录；请通过 tracing 启动服务后运行评测。')
        if result.returncode:
            raise RuntimeError('LLM Trace 报告生成失败，请检查 tracing 配置和采集日志。')
        return (Path(directory) / 'llm_trace.html').read_text(encoding='utf-8')
