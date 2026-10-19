"""Local store on the database server for sessions and SQL text.

The collection server does not keep these rows. Each agent writes them here
and deletes them on its own retention schedule.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from collector.store import now_text

KINDS = {
    "active_session": {
        "label": "Active Session",
        "table": "active_session",
        "time_column": "agent_collect_tm",
        "default_days": 2,
    },
    "session_history": {
        "label": "Active Session History",
        "table": "session_history",
        "time_column": "agent_collect_tm",
        "default_days": 7,
    },
    "sql_text": {
        "label": "SQL Text",
        "table": "sql_text",
        "time_column": "last_seen",
        "default_days": 30,
    },
    "sql_stat": {
        "label": "SQL 수행 통계",
        "table": "sql_stat",
        "time_column": "agent_collect_tm",
        "default_days": 14,
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_setting (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retention_policy (
    data_kind TEXT PRIMARY KEY,
    keep_days INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_purge_at TEXT,
    last_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS purge_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at TEXT NOT NULL,
    data_kind TEXT NOT NULL,
    keep_days INTEGER,
    deleted_rows INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS active_session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_alias TEXT NOT NULL,
    agent_collect_tm TEXT NOT NULL,
    sid INTEGER,
    serial_number INTEGER,
    status TEXT,
    db_user TEXT,
    os_user TEXT,
    program TEXT,
    module TEXT,
    machine TEXT,
    sql_id TEXT,
    sql_text TEXT,
    wait_event TEXT,
    wait_class TEXT,
    elapsed_ms INTEGER,
    blocking_sid INTEGER,
    cpu_used REAL,
    logical_reads INTEGER,
    physical_reads INTEGER,
    command TEXT
);

CREATE TABLE IF NOT EXISTS session_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_alias TEXT NOT NULL,
    agent_collect_tm TEXT NOT NULL,
    sid INTEGER,
    serial_number INTEGER,
    status TEXT,
    db_user TEXT,
    os_user TEXT,
    program TEXT,
    module TEXT,
    machine TEXT,
    sql_id TEXT,
    sql_text TEXT,
    wait_event TEXT,
    wait_class TEXT,
    elapsed_ms INTEGER,
    blocking_sid INTEGER,
    cpu_used REAL,
    logical_reads INTEGER,
    physical_reads INTEGER,
    command TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS sql_text (
    agent_alias TEXT NOT NULL,
    sql_id TEXT NOT NULL,
    sql_text TEXT NOT NULL,
    command_type TEXT,
    db_user TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (agent_alias, sql_id)
);

CREATE TABLE IF NOT EXISTS sql_stat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_alias TEXT NOT NULL,
    agent_collect_tm TEXT NOT NULL,
    sql_id TEXT NOT NULL,
    executions INTEGER,
    elapsed_ms REAL,
    cpu_ms REAL,
    buffer_gets INTEGER,
    disk_reads INTEGER,
    rows_processed INTEGER,
    db_user TEXT,
    program TEXT
);
"""


class AgentStore:
    def __init__(self, path: Path, alias: str, save_interval_sec: int = 5, purge_interval_sec: int = 60):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.alias = alias
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)
        self._seed(save_interval_sec, purge_interval_sec)

    def close(self) -> None:
        self.conn.close()

    def _seed(self, save_interval_sec: int, purge_interval_sec: int) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO agent_setting (setting_key, setting_value) VALUES ('save_interval_sec', ?) ON CONFLICT(setting_key) DO NOTHING",
                (str(max(2, int(save_interval_sec))),),
            )
            self.conn.execute(
                "INSERT INTO agent_setting (setting_key, setting_value) VALUES ('purge_interval_sec', ?) ON CONFLICT(setting_key) DO NOTHING",
                (str(max(15, int(purge_interval_sec))),),
            )
            for kind, meta in KINDS.items():
                self.conn.execute(
                    "INSERT INTO retention_policy (data_kind, keep_days, enabled) VALUES (?, ?, 1) ON CONFLICT(data_kind) DO NOTHING",
                    (kind, meta["default_days"]),
                )
            self.conn.commit()

    def setting_int(self, key: str, default: int) -> int:
        row = self.conn.execute("SELECT setting_value FROM agent_setting WHERE setting_key=?", (key,)).fetchone()
        if row is None:
            return default
        return int(row["setting_value"])

    def save_interval(self) -> int:
        return max(2, self.setting_int("save_interval_sec", 5))

    def purge_interval(self) -> int:
        return max(15, self.setting_int("purge_interval_sec", 60))

    def update_schedule(self, save_interval_sec: int, purge_interval_sec: int) -> None:
        save_interval_sec = max(2, int(save_interval_sec))
        purge_interval_sec = max(15, int(purge_interval_sec))
        with self._lock:
            self.conn.execute(
                "INSERT INTO agent_setting (setting_key, setting_value) VALUES ('save_interval_sec', ?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                (str(save_interval_sec),),
            )
            self.conn.execute(
                "INSERT INTO agent_setting (setting_key, setting_value) VALUES ('purge_interval_sec', ?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                (str(purge_interval_sec),),
            )
            self.conn.commit()

    def save_sample(self, payload: dict) -> None:
        """Write one collect cycle. Replaces the active-session snapshot for that timestamp."""
        alias = payload.get("agent_alias") or self.alias
        collect_tm = payload["collect_tm"]
        sessions = payload.get("active_sessions") or []
        history = payload.get("session_history") or []
        sql_texts = payload.get("sql_texts") or []
        sql_stats = payload.get("sql_stats") or []
        with self._lock:
            self.conn.execute(
                "DELETE FROM active_session WHERE agent_alias=? AND agent_collect_tm=?",
                (alias, collect_tm),
            )
            for row in sessions:
                self._insert_session("active_session", alias, collect_tm, row, with_source=False)
            for row in history:
                self._insert_session("session_history", alias, collect_tm, row, with_source=True)
            for row in sql_texts:
                sql_id = row.get("sql_id")
                text = row.get("sql_text") or ""
                if not sql_id or not text:
                    continue
                self.conn.execute(
                    """
                    INSERT INTO sql_text (
                        agent_alias, sql_id, sql_text, command_type, db_user, first_seen, last_seen
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_alias, sql_id) DO UPDATE SET
                        sql_text=excluded.sql_text,
                        command_type=excluded.command_type,
                        db_user=excluded.db_user,
                        last_seen=excluded.last_seen
                    """,
                    (alias, sql_id, text, row.get("command_type") or "", row.get("db_user") or "", collect_tm, collect_tm),
                )
            for row in sql_stats:
                if not row.get("sql_id"):
                    continue
                self.conn.execute(
                    """
                    INSERT INTO sql_stat (
                        agent_alias, agent_collect_tm, sql_id, executions, elapsed_ms, cpu_ms,
                        buffer_gets, disk_reads, rows_processed, db_user, program
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alias,
                        collect_tm,
                        row["sql_id"],
                        _int(row.get("executions")),
                        _num(row.get("elapsed_ms")),
                        _num(row.get("cpu_ms")),
                        _int(row.get("buffer_gets")),
                        _int(row.get("disk_reads")),
                        _int(row.get("rows_processed")),
                        row.get("db_user") or "",
                        row.get("program") or "",
                    ),
                )
            self.conn.commit()

    def current_sessions(self) -> list[dict]:
        latest = self.conn.execute(
            "SELECT MAX(agent_collect_tm) AS tm FROM active_session WHERE agent_alias=?",
            (self.alias,),
        ).fetchone()
        if latest is None or latest["tm"] is None:
            return []
        rows = self.conn.execute(
            """
            SELECT * FROM active_session
            WHERE agent_alias=? AND agent_collect_tm=?
            ORDER BY CASE status WHEN 'ACTIVE' THEN 0 ELSE 1 END, elapsed_ms DESC
            """,
            (self.alias, latest["tm"]),
        ).fetchall()
        return [dict(row) for row in rows]

    def session_history(self, start: str, end: str, sql_id: str = "", limit: int = 200) -> list[dict]:
        sql = """
            SELECT * FROM session_history
            WHERE agent_alias=? AND agent_collect_tm>=? AND agent_collect_tm<=?
        """
        args: list = [self.alias, start, end]
        if sql_id:
            sql += " AND sql_id=?"
            args.append(sql_id)
        sql += " ORDER BY agent_collect_tm DESC, elapsed_ms DESC LIMIT ?"
        args.append(limit)
        return [dict(row) for row in self.conn.execute(sql, args).fetchall()]

    def sql_catalog(self, query: str = "", limit: int = 80) -> list[dict]:
        like = f"%{query.strip()}%"
        rows = self.conn.execute(
            """
            SELECT t.agent_alias, t.sql_id, t.sql_text, t.command_type, t.db_user,
                   t.first_seen, t.last_seen,
                   COALESCE(SUM(s.executions), 0) AS executions,
                   COALESCE(SUM(s.elapsed_ms), 0) AS elapsed_ms,
                   COALESCE(SUM(s.cpu_ms), 0) AS cpu_ms,
                   COALESCE(SUM(s.buffer_gets), 0) AS buffer_gets,
                   COALESCE(SUM(s.disk_reads), 0) AS disk_reads,
                   COALESCE(SUM(s.rows_processed), 0) AS rows_processed
            FROM sql_text t
            LEFT JOIN sql_stat s ON s.agent_alias=t.agent_alias AND s.sql_id=t.sql_id
            WHERE t.agent_alias=? AND (? = '' OR t.sql_text LIKE ? OR t.sql_id LIKE ?)
            GROUP BY t.agent_alias, t.sql_id
            ORDER BY elapsed_ms DESC
            LIMIT ?
            """,
            (self.alias, query.strip(), like, like, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def retention_status(self) -> dict:
        policies = []
        for row in self.conn.execute("SELECT * FROM retention_policy ORDER BY data_kind").fetchall():
            meta = KINDS.get(row["data_kind"])
            if meta is None:
                continue
            count = self.conn.execute(f"SELECT COUNT(*) AS c FROM {meta['table']}").fetchone()["c"]
            policies.append(
                {
                    "data_kind": row["data_kind"],
                    "label": meta["label"],
                    "table": meta["table"],
                    "keep_days": row["keep_days"],
                    "enabled": bool(row["enabled"]),
                    "last_purge_at": row["last_purge_at"],
                    "last_deleted": row["last_deleted"],
                    "row_count": count,
                }
            )
        log = [dict(row) for row in self.conn.execute("SELECT * FROM purge_log ORDER BY id DESC LIMIT 30").fetchall()]
        return {
            "agent_alias": self.alias,
            "store_path": str(self.path),
            "save_interval_sec": self.save_interval(),
            "purge_interval_sec": self.purge_interval(),
            "policies": policies,
            "log": log,
        }

    def update_retention(self, updates: list[dict]) -> None:
        with self._lock:
            for item in updates:
                kind = item.get("data_kind")
                if kind not in KINDS:
                    continue
                self.conn.execute(
                    "UPDATE retention_policy SET keep_days=?, enabled=? WHERE data_kind=?",
                    (max(0, int(item.get("keep_days") or 0)), 1 if item.get("enabled", True) else 0, kind),
                )
            self.conn.commit()

    def purge(self, moment: datetime | None = None) -> list[dict]:
        moment = moment or datetime.now()
        stamp = now_text(moment)
        summary = []
        with self._lock:
            policies = self.conn.execute("SELECT * FROM retention_policy").fetchall()
            for policy in policies:
                kind = policy["data_kind"]
                meta = KINDS.get(kind)
                if meta is None:
                    continue
                if not policy["enabled"]:
                    summary.append({"data_kind": kind, "deleted_rows": 0, "skipped": True, "keep_days": policy["keep_days"]})
                    continue
                cutoff = now_text(moment - timedelta(days=int(policy["keep_days"])))
                cursor = self.conn.execute(
                    f"DELETE FROM {meta['table']} WHERE {meta['time_column']} < ?",
                    (cutoff,),
                )
                deleted = cursor.rowcount
                self.conn.execute(
                    "UPDATE retention_policy SET last_purge_at=?, last_deleted=? WHERE data_kind=?",
                    (stamp, deleted, kind),
                )
                self.conn.execute(
                    "INSERT INTO purge_log (ran_at, data_kind, keep_days, deleted_rows) VALUES (?, ?, ?, ?)",
                    (stamp, kind, policy["keep_days"], deleted),
                )
                summary.append(
                    {
                        "data_kind": kind,
                        "label": meta["label"],
                        "keep_days": policy["keep_days"],
                        "cutoff": cutoff,
                        "deleted_rows": deleted,
                        "skipped": False,
                    }
                )
            self.conn.commit()
        return summary

    def _insert_session(self, table: str, alias: str, collect_tm: str, row: dict, with_source: bool) -> None:
        columns = [
            "agent_alias", "agent_collect_tm", "sid", "serial_number", "status", "db_user", "os_user",
            "program", "module", "machine", "sql_id", "sql_text", "wait_event", "wait_class",
            "elapsed_ms", "blocking_sid", "cpu_used", "logical_reads", "physical_reads", "command",
        ]
        values = [
            alias, collect_tm, _int(row.get("sid")), _int(row.get("serial_number")), row.get("status") or "",
            row.get("db_user") or "", row.get("os_user") or "", row.get("program") or "", row.get("module") or "",
            row.get("machine") or "", row.get("sql_id") or "", row.get("sql_text") or "", row.get("wait_event") or "",
            row.get("wait_class") or "", _int(row.get("elapsed_ms")), _int(row.get("blocking_sid")),
            _num(row.get("cpu_used")), _int(row.get("logical_reads")), _int(row.get("physical_reads")),
            row.get("command") or "",
        ]
        if with_source:
            columns.append("source")
            values.append(row.get("source") or "sample")
        placeholders = ",".join("?" for _ in columns)
        self.conn.execute(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )


def _num(value):
    if value is None or value == "":
        return None
    return float(value)


def _int(value):
    if value is None or value == "":
        return None
    return int(float(value))
