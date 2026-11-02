"""一个实例只保留最新一次试验及事件。与正式评测/聚类结果分库。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from impl.core.instances import data_root


def alive(pid):
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except PermissionError: return True


def dump(value):
    return json.dumps(value, ensure_ascii=False, default=str)


class LabStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    @contextmanager
    def db(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                db.execute('PRAGMA auto_vacuum=FULL')
                db.executescript('''CREATE TABLE IF NOT EXISTS latest (
                    slot INTEGER PRIMARY KEY CHECK(slot=1), id TEXT NOT NULL, owner INTEGER NOT NULL,
                    status TEXT NOT NULL, cancel INTEGER NOT NULL DEFAULT 0,
                    started REAL NOT NULL, updated REAL NOT NULL, metadata TEXT NOT NULL,
                    result TEXT, error TEXT);
                    CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS aligned_cases (
                    slot INTEGER PRIMARY KEY CHECK(slot=1), id TEXT NOT NULL, payload TEXT NOT NULL);
                ''')
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except Exception:
                db.rollback(); raise
            finally:
                db.close()

    def _current(self, db):
        row = db.execute('SELECT * FROM latest WHERE slot=1').fetchone()
        if row and row['status'] == 'running' and not alive(row['owner']):
            db.execute("UPDATE latest SET status='failed',error='试验服务已中断；不会自动重跑',updated=? WHERE slot=1", (time.time(),))
            row = db.execute('SELECT * FROM latest WHERE slot=1').fetchone()
        return row

    def alignment(self):
        with self.db() as db:
            row = db.execute('SELECT payload FROM aligned_cases WHERE slot=1').fetchone()
            return json.loads(row['payload']) if row else None

    def save_alignment(self, snapshot):
        with self.db() as db:
            run = self._current(db)
            if run and run['status'] == 'running': raise ValueError('试验正在运行，不能中途替换对齐材料')
            db.execute('INSERT OR REPLACE INTO aligned_cases(slot,id,payload) VALUES(1,?,?)', (snapshot['id'], dump(snapshot)))

    def start(self, run_id, metadata, alignment_id=None):
        with self.db() as db:
            row = self._current(db)
            if row and row['status'] == 'running': raise ValueError('已有试验正在运行，请等待或停止；未启动重复调用')
            if alignment_id is not None:
                snapshot = db.execute('SELECT id FROM aligned_cases WHERE slot=1').fetchone()
                if not snapshot or snapshot['id'] != alignment_id:
                    raise ValueError('对齐快照已更新，请刷新试验台后再运行')
            db.execute('DELETE FROM events')
            now = time.time()
            db.execute("INSERT OR REPLACE INTO latest(slot,id,owner,status,started,updated,metadata) VALUES(1,?,?,'running',?,?,?)",
                       (run_id, os.getpid(), now, now, dump(metadata)))

    def event(self, run_id, kind, data):
        with self.db() as db:
            row = db.execute('SELECT id,status FROM latest WHERE slot=1').fetchone()
            if not row or row['id'] != run_id or row['status'] != 'running': return
            now = time.time()
            db.execute('INSERT INTO events(at,kind,data) VALUES(?,?,?)', (now, kind, dump(data)))
            db.execute('UPDATE latest SET updated=? WHERE slot=1', (now,))

    def finish(self, run_id, status, result=None, error=None):
        with self.db() as db:
            db.execute("UPDATE latest SET status=?,result=?,error=?,updated=? WHERE id=? AND status='running'",
                       (status, dump(result) if result is not None else None, error, time.time(), run_id))

    def stop(self, run_id):
        with self.db() as db:
            row = self._current(db)
            if not row or row['id'] != run_id: raise ValueError('页面运行编号已过期，请读取最新状态')
            if row['status'] == 'running': db.execute('UPDATE latest SET cancel=1 WHERE slot=1')

    def cancelled(self, run_id):
        with self.db() as db:
            row = db.execute('SELECT id,cancel FROM latest WHERE slot=1').fetchone()
            return not row or row['id'] != run_id or bool(row['cancel'])

    def state(self, after=0, run_id=None):
        with self.db() as db:
            row = self._current(db)
            if not row: return {'run': None, 'events': [], 'reset': True, 'server_time': time.time()}
            reset = row['id'] != run_id
            events = [{'seq': e['seq'], 'at': e['at'], 'kind': e['kind'], 'data': json.loads(e['data'])}
                      for e in db.execute('SELECT * FROM events WHERE seq>? ORDER BY seq', (0 if reset else after,))]
            run = {key: row[key] for key in ('id', 'status', 'started', 'updated', 'error')}
            run.update(cancel_requested=bool(row['cancel']), metadata=json.loads(row['metadata']),
                       result=json.loads(row['result']) if row['result'] is not None else None)
            return {'run': run, 'events': events, 'reset': reset, 'server_time': time.time()}


STORE = LabStore(data_root() / 'tool_loop_lab.sqlite3')
