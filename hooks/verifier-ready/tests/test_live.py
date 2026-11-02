from contextlib import nullcontext
import json
import signal
import subprocess
from unittest.mock import Mock

import pytest

import live


def config():
    return {'live': {'port': 8029, 'cases': ['case-1'], 'concurrency': 4, 'wall_clock_s': 1, 'poll_s': .1}}


def setup_mock(monkeypatch, tmp_path):
    import impl.core.instances as instances
    monkeypatch.setattr(instances, 'resolve_instance', lambda _: {'id': 'inst-0123456789abcdef', 'relay_ports': [4005, 4006, 4007]})
    monkeypatch.setattr(instances, 'instance_root', lambda _: tmp_path / 'instance')
    monkeypatch.setattr(live, '_ownership', lambda _: nullcontext())
    monkeypatch.setattr(live, '_seed', lambda _: None)
    monkeypatch.setattr(live, '_free_port', lambda _: None)
    monkeypatch.setattr(live, 'read_json', lambda _: [{'id': 'case-1', 'live_request': {'original': True}}])
    process = Mock(pid=12345)
    process.poll.return_value = None
    monkeypatch.setattr(live.subprocess, 'Popen', Mock(return_value=process))
    cleanup = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(live.subprocess, 'run', cleanup)
    stop = Mock()
    monkeypatch.setattr(live, '_stop', stop)
    return process, cleanup, stop


def test_timeout_always_cleans_up_own_service_and_relays(monkeypatch, tmp_path):
    process, cleanup, stop = setup_mock(monkeypatch, tmp_path)
    monkeypatch.setattr(live, '_health', lambda _: None)
    clock = iter([0, 0, 2])
    monkeypatch.setattr(live.time, 'monotonic', lambda: next(clock, 2))
    monkeypatch.setattr(live.time, 'sleep', lambda _: None)
    with pytest.raises(TimeoutError):
        live.run(tmp_path, config())
    stop.assert_called_once_with(process)
    assert cleanup.call_args.args[0] == ['bash', 'run.sh', 'tracing', 'down', '--port', '8029']
    assert json.loads((tmp_path / 'raw/live-error.json').read_text())['reason'] == 'TimeoutError'


def test_success_collects_before_cleanup_and_preserves_request_id(monkeypatch, tmp_path):
    process, cleanup, stop = setup_mock(monkeypatch, tmp_path)
    health = iter([None, {'instance_id': 'inst-0123456789abcdef'}])
    monkeypatch.setattr(live, '_health', lambda _: next(health))
    monkeypatch.setattr(live.time, 'monotonic', lambda: 0)
    request = Mock(side_effect=[{'job_id': 'job', 'requests': [{'execution_id': 'opaque-id', 'request_case_id': 'case-1'}]},
                                {'status': 'completed', 'events': []}])
    monkeypatch.setattr(live, '_request', request)

    def export(out, execution_ids, instance_id):
        assert not stop.called and not cleanup.called
        assert execution_ids == ['opaque-id']
        assert instance_id == 'inst-0123456789abcdef'

    monkeypatch.setattr(live, 'collect', export)
    result = live.run(tmp_path, config())
    assert result['execution_ids'] == ['opaque-id']
    assert request.call_args_list[0].args[2]['cases'][0]['live_request'] == {'original': True}
    stop.assert_called_once_with(process)
    cleanup.assert_called_once()


def test_existing_healthy_server_is_never_touched(monkeypatch, tmp_path):
    monkeypatch.setattr(live, '_health', lambda _: {'status': 'ok'})
    launcher = Mock()
    cleanup = Mock()
    monkeypatch.setattr(live.subprocess, 'Popen', launcher)
    monkeypatch.setattr(live.subprocess, 'run', cleanup)
    with pytest.raises(RuntimeError, match='healthy server'):
        live.run(tmp_path, config())
    launcher.assert_not_called()
    cleanup.assert_not_called()


def test_stop_escalates_only_own_process_group(monkeypatch):
    process = Mock(pid=12345)
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired('server', 10), 0]
    kill = Mock()
    monkeypatch.setattr(live.os, 'killpg', kill)
    live._stop(process)
    assert kill.call_args_list[0].args == (12345, signal.SIGTERM)
    assert kill.call_args_list[1].args == (12345, signal.SIGKILL)


def test_seed_uses_repository_materials_and_preserves_existing_instance(monkeypatch, tmp_path):
    source = tmp_path / 'repository/impl/data/llm_probe'
    (source / 'materials').mkdir(parents=True)
    (source / 'materials/rule.md').write_text('tracked rule')
    (source / 'capability_map.json').write_text('{}')
    (source / 'mock_cases.json').write_text('[]')
    monkeypatch.setattr(live, 'ROOT', tmp_path / 'repository')
    runtime = tmp_path / 'instance'
    live._seed(runtime)
    destination = runtime / 'data/llm_probe'
    assert (destination / 'materials/rule.md').read_text() == 'tracked rule'
    (destination / 'materials/rule.md').write_text('existing instance rule')
    live._seed(runtime)
    assert (destination / 'materials/rule.md').read_text() == 'existing instance rule'
