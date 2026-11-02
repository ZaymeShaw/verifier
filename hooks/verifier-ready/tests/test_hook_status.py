import json
import os

import pytest

from common import load_profile, write_json
import gate
from test_verdict import captured, problem


def contents(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_hook_state_without_report_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'CURRENT', tmp_path / 'report/current/progress.json')
    before = contents(tmp_path)
    result = gate.hook_state(load_profile(), root=tmp_path)
    assert result['status'] == 'no_report' and not result['release_allowed']
    assert len(result['code']) == 64 and result['max_blocks'] == 6
    assert before == contents(tmp_path)


def test_hook_bridge_recomputes_real_verdict_and_detects_stale(captured, monkeypatch):
    root, out, profile = captured
    monkeypatch.setattr(gate, 'CURRENT', root / 'report/current/progress.json')
    write_json(gate.CURRENT, {'report': str(out), 'phase': 'completed', 'pid': os.getpid()})
    before = contents(root)
    result = gate.hook_state(profile, root=root)
    assert result['status'] == 'pass' and result['release_allowed']
    assert before == contents(root)
    (root / 'impl/file.py').write_text('changed')
    before = contents(root)
    stale = gate.hook_state(profile, root=root)
    assert stale['status'] == 'stale' and not stale['release_allowed']
    assert stale['code'] != result['code']
    assert before == contents(root)


def test_hook_bridge_reports_running_without_reviewing(captured, monkeypatch):
    root, out, profile = captured
    monkeypatch.setattr(gate, 'CURRENT', root / 'report/current/progress.json')
    write_json(gate.CURRENT, {'report': str(out), 'phase': 'reviewing', 'pid': os.getpid()})
    result = gate.hook_state(profile, root=root)
    assert result['status'] == 'running' and not result['release_allowed']


def test_hook_bridge_keeps_human_exception_visible(captured, monkeypatch):
    root, out, profile = captured
    monkeypatch.setattr(gate, 'CURRENT', root / 'report/current/progress.json')
    write_json(gate.CURRENT, {'report': str(out), 'phase': 'completed', 'pid': os.getpid()})
    key = problem(out)
    write_json(out / 'adjudication.json', {'entries': [{'finding': key, 'rule': 'waived-by-human', 'note': 'accepted'}]})
    result = gate.hook_state(profile, root=root)
    assert result['status'] == 'pass_with_exception' and result['release_allowed']
    assert not result['consistency']['pass']


@pytest.mark.parametrize('limit', [0, -1, True, '6'])
def test_hook_limit_must_be_positive_integer(limit):
    profile = load_profile()
    profile['hook']['max_blocks'] = limit
    with pytest.raises(ValueError, match='positive integer'):
        gate.hook_state(profile)


def test_hook_command_cannot_launch_live_or_review(tmp_path, monkeypatch, capsys):
    import live
    import review
    def forbidden(*args, **kwargs):
        raise AssertionError('hook must never start a business or model run')
    monkeypatch.setattr(live, 'run', forbidden)
    monkeypatch.setattr(review, 'run', forbidden)
    monkeypatch.setattr(gate, 'CURRENT', tmp_path / 'absent/progress.json')
    assert gate.main(['--hook-status']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'no_report'
    assert not list(tmp_path.iterdir())


def test_losing_report_lock_does_not_change_owner_report_or_progress(captured, monkeypatch, capsys):
    root, out, profile = captured
    monkeypatch.setattr(gate, 'CURRENT', root / 'report/current/progress.json')
    write_json(gate.CURRENT, {'report': str(out), 'phase': 'reviewing', 'pid': os.getpid()})
    with gate.report_lock(out):
        before = contents(root)
        assert gate.main(['--review', '--out', str(out)]) == 2
        assert 'already writing' in capsys.readouterr().err
        assert contents(root) == before


def test_failure_is_recorded_before_report_lock_is_released(captured, monkeypatch):
    import fcntl
    root, out, profile = captured
    monkeypatch.setattr(gate, 'CURRENT', root / 'report/current/progress.json')
    original = gate.save_run
    checked = []
    def save_under_lock(*args, **fields):
        if fields.get('phase') == 'failed':
            with (out / '.gate.lock').open('a') as competitor:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            checked.append(True)
        return original(*args, **fields)
    monkeypatch.setattr(gate, 'save_run', save_under_lock)
    with pytest.raises(RuntimeError, match='synthetic review error'):
        with gate.report_operation(out):
            raise RuntimeError('synthetic review error')
    assert checked == [True]
    assert json.loads((out / 'run.json').read_text())['phase'] == 'failed'
