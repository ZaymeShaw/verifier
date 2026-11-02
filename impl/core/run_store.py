"""当前候选区的运行结果，不是历史库。

每项目一份候选区、每行一个最新结果、一个最新批次头。重跑覆盖选中行，
换候选区/清空会物理删除旧数据；SQLite FULL auto-vacuum 在提交时回收空页。
用候选区位置区分重复 case_id，request_key 防止过期结果写回新一轮。
"""
from __future__ import annotations

from .instances import data_root

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class WorkspaceBusy(ValueError):
    pass


class WorkspaceConflict(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class LatestRunStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    @contextmanager
    def _db(self):
        # 同一进程串行打开/使用本库，避免 macOS sqlite connect stampede。
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA auto_vacuum = FULL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS current_cases (
                        project TEXT NOT NULL, position INTEGER NOT NULL, case_json TEXT NOT NULL,
                        source TEXT NOT NULL, request_key TEXT, status TEXT NOT NULL DEFAULT 'pending',
                        error TEXT, run_json TEXT, PRIMARY KEY (project, position)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS current_request ON current_cases(project, request_key);
                    CREATE TABLE IF NOT EXISTS current_batches (
                        project TEXT PRIMARY KEY, job_id TEXT NOT NULL, owner_pid INTEGER NOT NULL,
                        status TEXT NOT NULL, identities_json TEXT NOT NULL,
                        summary_json TEXT, error TEXT
                    );
                    CREATE TABLE IF NOT EXISTS axis_clustering (
                        project TEXT PRIMARY KEY, criteria TEXT NOT NULL, criteria_version INTEGER NOT NULL,
                        data_revision TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'idle',
                        job_id TEXT, owner_pid INTEGER, job_version INTEGER, job_revision TEXT,
                        selections_json TEXT, result_json TEXT, error TEXT
                    );
                    CREATE TABLE IF NOT EXISTS task_progress (
                        project TEXT NOT NULL, kind TEXT NOT NULL, job_id TEXT NOT NULL,
                        started_at REAL NOT NULL, last_event_at REAL NOT NULL, finished_at REAL,
                        stage TEXT NOT NULL, detail TEXT NOT NULL, completed INTEGER, total INTEGER,
                        request_timeout_seconds REAL, PRIMARY KEY(project, kind)
                    );
                """)
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def _start_progress(self, db, project, kind, job_id, stage, detail, completed=None, total=None):
        now = time.time()
        db.execute("""INSERT OR REPLACE INTO task_progress
                   (project,kind,job_id,started_at,last_event_at,stage,detail,completed,total)
                   VALUES(?,?,?,?,?,?,?,?,?)""", (project, kind, job_id, now, now, stage, detail, completed, total))

    def _mark_progress(self, db, project, kind, job_id, stage, detail, completed=None, timeout=None):
        now = time.time()
        terminal = stage in ('completed', 'failed', 'stale')
        db.execute("""UPDATE task_progress SET stage=?,detail=?,last_event_at=?,
                   finished_at=CASE WHEN ? THEN ? ELSE finished_at END,
                   completed=COALESCE(?,completed),request_timeout_seconds=COALESCE(?,request_timeout_seconds)
                   WHERE project=? AND kind=? AND job_id=?""",
                   (stage, detail, now, terminal, now, completed, timeout, project, kind, job_id))

    def _progress(self, db, project, kind, job_id):
        row = db.execute("SELECT * FROM task_progress WHERE project=? AND kind=? AND job_id=?",
                         (project, kind, job_id)).fetchone()
        if not row:
            return None  # 没记录过的起始时间不能用现在伪造。
        result = dict(row)
        now = time.time()
        elapsed = max(0, (row['finished_at'] or now) - row['started_at'])
        result.update(elapsed_seconds=elapsed, no_event_seconds=max(0, now - row['last_event_at']), server_time=now)
        done, total = row['completed'], row['total']
        result['eta_seconds'] = (elapsed * (total - done) / done
                                 if kind == 'batch' and row['stage'] == 'executing_cases'
                                 and done and total and 0 < done < total else None)
        return result

    def _batch(self, db, project):
        batch = db.execute("SELECT * FROM current_batches WHERE project=?", (project,)).fetchone()
        if batch and batch["status"] in ("pending", "running") and not _alive(batch["owner_pid"]):
            error = "运行服务已中断；已完成结果保留，未完成用例需手动重跑。"
            db.execute("UPDATE current_batches SET status='failed',error=? WHERE project=?", (error, project))
            db.execute("UPDATE current_cases SET status='error',error=? WHERE project=? AND status='running' AND run_json IS NULL", (error, project))
            self._mark_progress(db, project, 'batch', batch['job_id'], 'failed', error)
            batch = db.execute("SELECT * FROM current_batches WHERE project=?", (project,)).fetchone()
        return batch

    def _require_idle(self, db, project):
        batch = self._batch(db, project)
        if batch and batch["status"] in ("pending", "running"):
            raise WorkspaceBusy("该项目有批次正在运行，请等完成后再清空、替换候选区或重跑。")

    def _invalidate_clustering(self, db, project):
        db.execute("""UPDATE axis_clustering SET data_revision=?,result_json=NULL,
                   status=CASE WHEN status='running' THEN status ELSE 'stale' END
                   WHERE project=?""", (uuid.uuid4().hex, project))

    def _replace(self, db, project, cases, source):
        self._invalidate_clustering(db, project)
        db.execute("DELETE FROM task_progress WHERE project=? AND kind='batch'", (project,))
        db.execute("DELETE FROM current_cases WHERE project=?", (project,))
        db.execute("DELETE FROM current_batches WHERE project=?", (project,))
        db.executemany("INSERT INTO current_cases(project,position,case_json,source) VALUES(?,?,?,?)",
                       [(project, i, _json(case), source) for i, case in enumerate(cases)])

    def replace(self, project, cases, source):
        with self._db() as db:
            self._require_idle(db, project)
            self._replace(db, project, cases, source)

    def clear(self, project, *, keep_cases):
        with self._db() as db:
            self._require_idle(db, project)
            self._invalidate_clustering(db, project)
            db.execute("DELETE FROM task_progress WHERE project=? AND kind='batch'", (project,))
            db.execute("DELETE FROM current_batches WHERE project=?", (project,))
            if keep_cases:
                db.execute("UPDATE current_cases SET request_key=NULL,status='pending',error=NULL,run_json=NULL WHERE project=?", (project,))
            else:
                db.execute("DELETE FROM current_cases WHERE project=?", (project,))

    def start(self, project, job_id, cases, pool_indexes=None):
        """独立调用替换候选区；提供 pool_indexes 时仅重跑现有候选区中指定行。"""
        with self._db() as db:
            self._require_idle(db, project)
            if pool_indexes is None:
                self._replace(db, project, cases, "batch")
                pool_indexes = list(range(len(cases)))
            if len(pool_indexes) != len(cases) or len(set(pool_indexes)) != len(pool_indexes):
                raise ValueError("pool_indexes 必须与提交用例一一对应，且不能重复")
            for position, case in zip(pool_indexes, cases):
                row = db.execute("SELECT case_json FROM current_cases WHERE project=? AND position=?", (project, position)).fetchone()
                if not row or row["case_json"] != _json(case):
                    raise ValueError("候选区已发生变化，请刷新后重新选择用例")
            identities = [{"job_id": job_id, "request_index": i, "request_key": f"{job_id}:{i}",
                           "request_case_id": str(case.get("id") or ""), "pool_index": position}
                          for i, (position, case) in enumerate(zip(pool_indexes, cases))]
            from .llm_tracing import _wire
            for identity in identities:
                identity['execution_id'] = _wire(identity['request_key'])
            self._invalidate_clustering(db, project)
            for identity in identities:
                db.execute("UPDATE current_cases SET request_key=?,status='running',error=NULL,run_json=NULL WHERE project=? AND position=?",
                           (identity["request_key"], project, identity["pool_index"]))
            db.execute("INSERT OR REPLACE INTO current_batches(project,job_id,owner_pid,status,identities_json) VALUES(?,?,?,'running',?)",
                       (project, job_id, os.getpid(), _json(identities)))
            self._start_progress(db, project, 'batch', job_id, 'executing_cases', '正在执行用例', completed=0, total=len(cases))
            return identities

    def save_run(self, project, job_id, identity, run):
        with self._db() as db:
            batch = self._batch(db, project)
            if not batch or batch["job_id"] != job_id or batch["status"] != "running":
                raise ValueError("批次已结束或被替换，拒绝写入过期结果")
            result = {**run, **identity}
            cursor = db.execute("UPDATE current_cases SET run_json=?,status=?,error=? WHERE project=? AND position=? AND request_key=?",
                                (_json(result), result.get("status") or "done", result.get("error"), project,
                                 identity["pool_index"], identity["request_key"]))
            if cursor.rowcount != 1:
                raise ValueError("运行结果不属于当前候选区")
            done = db.execute("SELECT COUNT(*) FROM current_cases WHERE project=? AND request_key LIKE ? AND run_json IS NOT NULL",
                              (project, job_id + ':%')).fetchone()[0]
            total = len(json.loads(batch['identities_json']))
            self._mark_progress(db, project, 'batch', job_id,
                                'finalizing' if done == total else 'executing_cases',
                                '用例已全部返回，正在汇总批次' if done == total else f'已保存 {done}/{total} 条用例结果', completed=done)
            self._invalidate_clustering(db, project)

    def finish(self, project, job_id, summary=None, error=None):
        with self._db() as db:
            if error:
                db.execute("UPDATE current_cases SET status='error',error=? WHERE project=? AND status='running' AND run_json IS NULL AND request_key LIKE ?",
                           (error, project, job_id + ":%"))
            db.execute("UPDATE current_batches SET status=?,summary_json=?,error=? WHERE project=? AND job_id=?",
                       ("failed" if error else "completed", _json(summary) if summary is not None else None, error, project, job_id))
            self._mark_progress(db, project, 'batch', job_id, 'failed' if error else 'completed', error or '批次已完成')

    def batch_progress(self, project):
        """只读轻量批次状态，不在轮询中加载整批 Trace/输出。"""
        with self._db() as db:
            batch = self._batch(db, project)
            if not batch:
                return None
            ids = json.loads(batch['identities_json'])
            done = db.execute("SELECT COUNT(*) FROM current_cases WHERE project=? AND request_key LIKE ? AND run_json IS NOT NULL",
                              (project, batch['job_id'] + ':%')).fetchone()[0]
            return {'job_id': batch['job_id'], 'status': batch['status'], 'total': len(ids), 'done': done,
                    'error': batch['error'], 'progress': self._progress(db, project, 'batch', batch['job_id'])}

    def load(self, project):
        with self._db() as db:
            batch = self._batch(db, project)
            rows = db.execute("SELECT * FROM current_cases WHERE project=? ORDER BY position", (project,)).fetchall()
            cases, runs = [], []
            for row in rows:
                cases.append({"case": json.loads(row["case_json"]), "selected": True, "source": row["source"],
                              "request_key": row["request_key"], "status": row["status"], "error": row["error"]})
                if row["run_json"] is not None:
                    runs.append(json.loads(row["run_json"]))
            header = None
            if batch:
                identities = json.loads(batch["identities_json"])
                keys = {i["request_key"] for i in identities}
                header = {"project_id": project, "job_id": batch["job_id"], "status": batch["status"],
                          "total": len(identities), "done": sum(r["request_key"] in keys for r in runs),
                          "bindings": identities, "error": batch["error"],
                          "progress": self._progress(db, project, 'batch', batch['job_id']),
                          "summary": json.loads(batch["summary_json"]) if batch["summary_json"] else None}
            return {"project_id": project, "cases": cases, "runs": runs, "batch": header}

    def get_run(self, project, request_key):
        with self._db() as db:
            self._require_idle(db, project)
            row = db.execute("SELECT run_json FROM current_cases WHERE project=? AND request_key=?", (project, request_key)).fetchone()
            if not row or row["run_json"] is None:
                raise KeyError("当前结果已被清空或重跑，请刷新页面")
            return json.loads(row["run_json"])

    def update_run(self, project, request_key, run):
        with self._db() as db:
            self._require_idle(db, project)
            cursor = db.execute("UPDATE current_cases SET run_json=? WHERE project=? AND request_key=? AND run_json IS NOT NULL",
                                (_json(run), project, request_key))
            if cursor.rowcount != 1:
                raise ValueError("当前结果已被清空或重跑，拒绝写回旧结果")
            self._invalidate_clustering(db, project)

    def _clustering(self, db, project, default_criteria):
        db.execute("""INSERT OR IGNORE INTO axis_clustering
                   (project,criteria,criteria_version,data_revision) VALUES(?,?,1,?)""",
                   (project, default_criteria, uuid.uuid4().hex))
        row = db.execute("SELECT * FROM axis_clustering WHERE project=?", (project,)).fetchone()
        if row["status"] == "running" and not _alive(row["owner_pid"]):
            db.execute("UPDATE axis_clustering SET status='failed',error=? WHERE project=?",
                       ("聚类服务已中断，请手动重新聚类。", project))
            self._mark_progress(db, project, 'clustering', row['job_id'], 'failed', '聚类服务已中断')
            row = db.execute("SELECT * FROM axis_clustering WHERE project=?", (project,)).fetchone()
        return row

    def clustering_state(self, project, default_criteria):
        with self._db() as db:
            row = dict(self._clustering(db, project, default_criteria))
            result_json = row.pop("result_json")
            row["result"] = json.loads(result_json) if result_json else None
            row["selections"] = json.loads(row.pop("selections_json") or "[]")
            row.pop("owner_pid", None)
            row['progress'] = self._progress(db, project, 'clustering', row['job_id'])
            return row

    def _save_clustering_criteria(self, db, row, criteria, expected_version):
        if row["criteria_version"] != expected_version:
            raise WorkspaceConflict("聚类标准已在其他页面更新，请先读取最新标准")
        criteria = criteria.strip()
        if not criteria:
            raise ValueError("聚类标准不能为空")
        if criteria != row["criteria"]:
            db.execute("""UPDATE axis_clustering SET criteria=?,criteria_version=criteria_version+1,
                       result_json=NULL,status=CASE WHEN status='running' THEN status ELSE 'stale' END
                       WHERE project=?""", (criteria, row["project"]))
        return db.execute("SELECT * FROM axis_clustering WHERE project=?", (row["project"],)).fetchone()

    def save_clustering_criteria(self, project, criteria, expected_version, default_criteria):
        with self._db() as db:
            row = self._clustering(db, project, default_criteria)
            self._save_clustering_criteria(db, row, criteria, expected_version)

    def clustering_inputs(self, project, selections, default_criteria):
        # 状态读取在业务批次运行中也应可用。启动模型的闲置检查仍在 begin_clustering 中。
        with self._db() as db:
            state = self._clustering(db, project, default_criteria)
            positions = [s["pool_index"] for s in selections]
            if not selections or len(positions) != len(set(positions)):
                raise ValueError("请选择非空且不重复的候选区记录")
            rows = []
            for selection in sorted(selections, key=lambda s: s["pool_index"]):
                row = db.execute("""SELECT request_key,json_extract(run_json,'$.table_row.eval_axes_summary') AS axes
                                 FROM current_cases WHERE project=? AND position=?""",
                                 (project, selection["pool_index"])).fetchone()
                if not row or row["request_key"] != selection.get("request_key"):
                    raise WorkspaceConflict("候选区结果已更新，请回主页刷新后重新打开试验页")
                rows.append({**selection, "axes": json.loads(row["axes"] or "[]")})
            return {"data_revision": state["data_revision"], "rows": rows}

    def begin_clustering(self, project, criteria, expected_version, data_revision, selections, job_id, default_criteria):
        with self._db() as db:
            self._require_idle(db, project)
            row = self._clustering(db, project, default_criteria)
            if row["status"] == "running":
                raise WorkspaceBusy("此项目正在聚类，请等待当前任务完成，避免重复调用模型")
            if row["data_revision"] != data_revision:
                raise WorkspaceConflict("准备期间运行结果已改变，请重新读取")
            row = self._save_clustering_criteria(db, row, criteria, expected_version)
            db.execute("""UPDATE axis_clustering SET job_id=?,owner_pid=?,status='running',job_version=?,
                       job_revision=?,selections_json=?,result_json=NULL,error=NULL WHERE project=?""",
                       (job_id, os.getpid(), row["criteria_version"], data_revision, _json(selections), project))
            self._start_progress(db, project, 'clustering', job_id, 'submitted', '聚类任务已提交，准备调用模型')
            return {"criteria": row["criteria"], "criteria_version": row["criteria_version"]}

    def clustering_progress(self, project, job_id, stage, detail, request_timeout_seconds=None):
        with self._db() as db:
            row = db.execute("SELECT job_id,status FROM axis_clustering WHERE project=?", (project,)).fetchone()
            if row and row['job_id'] == job_id and row['status'] == 'running':
                self._mark_progress(db, project, 'clustering', job_id, stage, detail, timeout=request_timeout_seconds)

    def finish_clustering(self, project, job_id, result=None, error=None):
        with self._db() as db:
            row = db.execute("SELECT * FROM axis_clustering WHERE project=?", (project,)).fetchone()
            if not row or row["job_id"] != job_id or row["status"] != "running":
                return False
            stale = row["job_version"] != row["criteria_version"] or row["job_revision"] != row["data_revision"]
            status = "stale" if stale else "failed" if error else "completed"
            message = "标准或运行结果已改变，未采用过期聚类，请重新聚类。" if stale else error
            db.execute("UPDATE axis_clustering SET status=?,result_json=?,error=? WHERE project=?",
                       (status, _json(result) if status == "completed" else None, message, project))
            self._mark_progress(db, project, 'clustering', job_id, status, message or '聚类已完成并保存')
            return status == "completed"


STORE = LatestRunStore(data_root() / "latest_runs.sqlite3")
