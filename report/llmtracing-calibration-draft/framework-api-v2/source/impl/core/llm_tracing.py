"""Request-local identity for verifier's own LLM traffic (not business traces)."""
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from datetime import datetime, timezone
from functools import wraps
import hashlib
import inspect
import logging
import re
import uuid

_identity = ContextVar('verifier_llm_identity', default=None)
_log = logging.getLogger(__name__)


def _wire(value):
    raw = str(value or '')
    clean = re.sub(r'[^A-Za-z0-9._:-]', '_', raw)[:100]
    if clean != raw:
        clean += '-' + hashlib.sha256(raw.encode()).hexdigest()[:12]
    return clean


def current_identity():
    return dict(_identity.get() or {})


@contextmanager
def trace_scope(*, run_id=None, case_id=None, project_id='', new_attempt=False, independent=False):
    parent = {} if independent else current_identity()
    identity = dict(parent)
    identity['run_id'] = _wire(run_id or parent.get('run_id') or 'verifier-' + uuid.uuid4().hex)
    identity['case_id'] = _wire(case_id if case_id is not None else parent.get('case_id') or '__batch__')
    identity['project_id'] = _wire(project_id or parent.get('project_id', ''))
    if new_attempt or not parent or identity['case_id'] != parent.get('case_id') or identity['run_id'] != parent.get('run_id'):
        identity['execution_id'] = uuid.uuid4().hex
        identity['started_at'] = datetime.now(timezone.utc).isoformat()
    token = _identity.set(identity)
    try:
        yield dict(identity)
    finally:
        _identity.reset(token)


def trace_headers(*, role='', stage='', trace_id=''):
    identity = current_identity()
    if not identity:
        raise RuntimeError('LLM trace identity missing: establish a request scope first')
    values = {'Run-Id': identity['run_id'], 'Case-Id': identity['case_id'],
              'Execution-Id': identity['execution_id'], 'Harness': 'verifier',
              'Started-At': identity['started_at'], 'Project-Id': identity.get('project_id'),
              'Role': _wire(role), 'Stage': _wire(stage), 'Verifier-Trace-Id': _wire(trace_id)}
    return {'X-Eval-' + key: value for key, value in values.items() if value}


def submit_with_context(executor, function, *args, **kwargs):
    # One copy per submission: a Context cannot be entered by two threads at once.
    return executor.submit(copy_context().run, function, *args, **kwargs)


def traced_entry(*, batch=False):
    """Root CLI/API entry; nested operations retain the current case attempt."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def wrapped(*args, **kwargs):
            if current_identity():
                return function(*args, **kwargs)
            bound = signature.bind(*args, **kwargs).arguments
            case = bound.get('case') or bound.get('trace')
            cid = (case.get('id') or case.get('case_id')) if isinstance(case, dict) else (getattr(case, 'case_id', None) or getattr(case, 'id', None))
            with trace_scope(project_id=bound.get('project_id', ''), case_id='__batch__' if batch else cid,
                             run_id=bound.get('tracing_run_id')) as identity:
                _log.info('llmtracing run_id=%s case_id=%s', identity['run_id'], identity['case_id'])
                result = function(*args, **kwargs)
                if isinstance(result, dict):
                    result['llmtracing'] = identity
                # Preserve the query handle in serialized CLI/API trace results.
                traces = [bound.get('trace'), result.get('trace') if isinstance(result, dict) else result]
                for trace in traces:
                    if hasattr(trace, 'trace_id') and isinstance(getattr(trace, 'metadata', None), dict):
                        trace.metadata['verifier_llmtracing'] = identity
                return result
        return wrapped
    return decorate


def traced_model_call(function):
    """Also covers direct client users outside pipeline (analysis and tools)."""
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        if current_identity():
            return function(self, *args, **kwargs)
        bound = signature.bind(self, *args, **kwargs).arguments
        with trace_scope(case_id=bound.get('trace_id') or '__standalone__',
                         project_id=getattr(self, '_project_id', '')):
            return function(self, *args, **kwargs)
    return wrapped
