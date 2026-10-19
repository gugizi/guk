"""Repository for environment settings and collected performance data."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from collector.version import LEGACY_TITLES, PRODUCT, VERSION, display_name, require_version

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROPERTIES = ROOT / "config" / "default.properties"
DEFAULT_REPOSITORY = "data/okedbmon.sqlite"
LEGACY_REPOSITORIES = ("data/okemon.sqlite", "data/spacemon.sqlite")
DEFAULT_AGENT_TOKEN = "okedbmon-agent"
LEGACY_AGENT_TOKENS = {"spacemon-agent"}

RETENTION_KINDS = {
    "performance": {
        "label": "DB 성능 정보",
        "table": "o_performance",
        "time_column": "agent_collect_tm",
        "property": "retention.performance.days",
        "default_days": 14,
    },
    "event": {
        "label": "이벤트",
        "table": "event_log",
        "time_column": "occurred_at",
        "property": "retention.event.days",
        "default_days": 30,
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
    user_id TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_token (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS env_setting (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retention_policy (
    data_kind TEXT PRIMARY KEY,
    keep_days INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_purge_at TEXT,
    last_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mon_instance (
    agent_alias TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    host_nm TEXT NOT NULL,
    port INTEGER NOT NULL,
    db_name TEXT,
    username TEXT,
    group_nm TEXT,
    collect_interval_sec INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_heartbeat (
    agent_alias TEXT PRIMARY KEY,
    product TEXT,
    last_seen TEXT,
    status TEXT,
    message TEXT,
    version TEXT,
    agent_url TEXT
);

CREATE TABLE IF NOT EXISTS o_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_alias TEXT NOT NULL,
    agent_collect_tm TEXT NOT NULL,
    instance_nm TEXT,
    cpu_usage REAL,
    mem_usage REAL,
    active_sessions INTEGER,
    connected_sessions INTEGER,
    lock_wait INTEGER,
    buffer_cache_ratio REAL,
    execute_cnt INTEGER,
    user_commits INTEGER,
    user_rollbacks INTEGER,
    physical_reads INTEGER,
    logical_reads INTEGER,
    tps REAL,
    qps REAL,
    redo_size INTEGER,
    parse_hard INTEGER,
    wait_user_io REAL,
    wait_lock REAL,
    wait_cpu REAL,
    wait_network REAL,
    tablespace_used_pct REAL,
    extra_json TEXT,
    UNIQUE (agent_alias, agent_collect_tm)
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

CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_alias TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    event_cd TEXT NOT NULL,
    event_nm TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purge_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at TEXT NOT NULL,
    data_kind TEXT NOT NULL,
    keep_days INTEGER,
    deleted_rows INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_perf_alias_tm ON o_performance (agent_alias, agent_collect_tm);
CREATE INDEX IF NOT EXISTS idx_active_alias_tm ON active_session (agent_alias, agent_collect_tm);
CREATE INDEX IF NOT EXISTS idx_hist_alias_tm ON session_history (agent_alias, agent_collect_tm);
CREATE INDEX IF NOT EXISTS idx_sqlstat_alias_tm ON sql_stat (agent_alias, agent_collect_tm);
CREATE INDEX IF NOT EXISTS idx_sqltext_seen ON sql_text (last_seen);
CREATE INDEX IF NOT EXISTS idx_event_tm ON event_log (occurred_at);
"""


def now_text(moment: datetime | None = None) -> str:
    moment = moment or datetime.now()
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 20000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, _, _digest = stored.partition("$")
    if not salt:
        return False
    candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, stored)


def repository_path(properties: dict[str, str] | None = None) -> Path:
    """SQLite file for both environment settings and collected performance data."""
    props = properties if properties is not None else load_properties()
    configured = ROOT / props.get("db.repository.path", DEFAULT_REPOSITORY)
    if configured.exists():
        return configured
    for legacy_name in LEGACY_REPOSITORIES:
        legacy = ROOT / legacy_name
        if legacy.exists():
            configured.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(configured)
            for suffix in ("-wal", "-shm"):
                extra = Path(str(legacy) + suffix)
                if extra.exists():
                    extra.rename(Path(str(configured) + suffix))
            break
    return configured


def load_properties(path: Path | None = None) -> dict[str, str]:
    source = path or DEFAULT_PROPERTIES
    values: dict[str, str] = {}
    if not source.exists():
        return values
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


SETTING_HELP = {
    "support.lang": "화면 언어 (ko, en)",
    "support.title": "제품 표시 이름",
    "support.ver": "수집서버 버전 (#.#.#.#)",
    "support.products": "모니터링 대상 DBMS",
    "collector.host": "수집서버 바인드 주소",
    "collector.port": "웹 조회 포트",
    "agent.token": "에이전트 인증 토큰",
    "collect.interval.sec": "기본 수집 주기(초)",
    "threshold.cpu": "CPU 경고 임계치(%)",
    "threshold.active_sessions": "Active Session 경고 임계치",
    "threshold.lock_wait": "Lock Wait 경고 임계치",
    "threshold.buffer_hit": "Buffer Hit 하한(%)",
    "retention.purge.interval.sec": "보관주기 삭제 작업 간격(초)",
    "db.repository.path": "저장소 파일 경로",
}


class Store:
    def __init__(self, path: Path, properties: dict[str, str] | None = None, seed: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        columns = [row[1] for row in self.conn.execute("PRAGMA table_info(agent_heartbeat)")]
        if "agent_url" not in columns:
            self.conn.execute("ALTER TABLE agent_heartbeat ADD COLUMN agent_url TEXT")
        self.properties = properties if properties is not None else load_properties()
        if seed:
            self._seed()

    def close(self) -> None:
        self.conn.close()

    def _seed(self) -> None:
        with self._lock:
            stamp = now_text()
            for key, value in self.properties.items():
                self.conn.execute(
                    """
                    INSERT INTO env_setting (setting_key, setting_value, description, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(setting_key) DO NOTHING
                    """,
                    (key, value, SETTING_HELP.get(key, ""), stamp),
                )
            for kind, meta in RETENTION_KINDS.items():
                days = int(self.properties.get(meta["property"], meta["default_days"]))
                self.conn.execute(
                    """
                    INSERT INTO retention_policy (data_kind, keep_days, enabled)
                    VALUES (?, ?, 1)
                    ON CONFLICT(data_kind) DO NOTHING
                    """,
                    (kind, days),
                )
            user = self.conn.execute("SELECT 1 FROM app_user WHERE user_id='admin'").fetchone()
            if user is None:
                self.conn.execute(
                    "INSERT INTO app_user (user_id, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
                    ("admin", hash_password("okedbmon"), "관리자", "ADMIN"),
                )
            if self.conn.execute("SELECT COUNT(*) AS c FROM mon_instance").fetchone()["c"] == 0:
                interval = int(self.properties.get("collect.interval.sec", "5"))
                instances = [
                    ("ORA_PROD", "ORACLE", "db-ora-01", 1521, "ORCL", "monitor", "운영", "주문/정산 Oracle"),
                    ("TIB_ERP", "TIBERO", "db-tib-01", 8629, "TIBERO", "monitor", "기간계", "ERP Tibero"),
                    ("MARIA_WEB", "MARIADB", "127.0.0.1", 3306, "okedbmon", "okedbmon", "서비스", "웹 MariaDB"),
                    ("PG_ANALYTICS", "POSTGRESQL", "127.0.0.1", 5432, "okedbmon", "okedbmon", "분석", "분석 PostgreSQL"),
                ]
                for alias, product, host, port, db_name, user_name, group, desc in instances:
                    self.conn.execute(
                        """
                        INSERT INTO mon_instance (
                            agent_alias, product, host_nm, port, db_name, username,
                            group_nm, collect_interval_sec, enabled, description, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (alias, product, host, port, db_name, user_name, group, interval, desc, stamp),
                    )
            self._migrate_identity(stamp)
            self.conn.commit()

    def _migrate_identity(self, stamp: str) -> None:
        title = self.setting("support.title", "")
        if title in LEGACY_TITLES:
            self.conn.execute(
                "UPDATE env_setting SET setting_value=?, description=?, updated_at=? WHERE setting_key='support.title'",
                (PRODUCT, SETTING_HELP["support.title"], stamp),
            )
        version = self.setting("support.ver", "")
        try:
            require_version(version)
        except ValueError:
            self.conn.execute(
                "UPDATE env_setting SET setting_value=?, description=?, updated_at=? WHERE setting_key='support.ver'",
                (VERSION, SETTING_HELP["support.ver"], stamp),
            )
        stored_path = self.setting("db.repository.path", "")
        if stored_path in LEGACY_REPOSITORIES:
            self.conn.execute(
                "UPDATE env_setting SET setting_value=?, updated_at=? WHERE setting_key='db.repository.path'",
                (self.properties.get("db.repository.path", DEFAULT_REPOSITORY), stamp),
            )
        moved = ("active_session", "session_history", "sql_stat", "sql_text")
        self.conn.execute(
            f"DELETE FROM retention_policy WHERE data_kind IN ({','.join('?' for _ in moved)})",
            moved,
        )
        for table in moved:
            self.conn.execute(f"DELETE FROM {table}")
        for key in (
            "retention.active_session.days",
            "retention.session_history.days",
            "retention.sql_stat.days",
            "retention.sql_text.days",
        ):
            self.conn.execute("DELETE FROM env_setting WHERE setting_key=?", (key,))
        if self.setting("agent.token", "") in LEGACY_AGENT_TOKENS:
            self.conn.execute(
                "UPDATE env_setting SET setting_value=?, updated_at=? WHERE setting_key='agent.token'",
                (self.properties.get("agent.token", DEFAULT_AGENT_TOKEN), stamp),
            )

    def setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT setting_value FROM env_setting WHERE setting_key=?", (key,)
        ).fetchone()
        if row:
            return row["setting_value"]
        return self.properties.get(key, default)

    def settings_public(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT setting_key, setting_value, description, updated_at FROM env_setting ORDER BY setting_key"
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            if item["setting_key"] in {"agent.token"}:
                item["setting_value"] = "********"
                item["secret"] = True
            else:
                item["secret"] = False
            result.append(item)
        return result

    def update_settings(self, updates: dict[str, str]) -> None:
        stamp = now_text()
        with self._lock:
            for key, value in updates.items():
                if key.startswith("retention.") and key.endswith(".days"):
                    continue
                existing = self.conn.execute(
                    "SELECT 1 FROM env_setting WHERE setting_key=?", (key,)
                ).fetchone()
                if existing is None:
                    continue
                if key == "agent.token" and (not value or value == "********"):
                    continue
                stored = str(value)
                if key == "support.ver":
                    stored = require_version(stored)
                self.conn.execute(
                    "UPDATE env_setting SET setting_value=?, updated_at=? WHERE setting_key=?",
                    (stored, stamp, key),
                )
            self.conn.commit()

    def login(self, user_id: str, password: str) -> str | None:
        row = self.conn.execute(
            "SELECT password_hash FROM app_user WHERE user_id=?", (user_id,)
        ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        expires = now_text(datetime.now() + timedelta(hours=12))
        with self._lock:
            self.conn.execute(
                "INSERT INTO auth_token (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, expires),
            )
            self.conn.commit()
        return token

    def user_for_token(self, token: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT u.user_id, u.display_name, u.role, t.expires_at
            FROM auth_token t
            JOIN app_user u ON u.user_id = t.user_id
            WHERE t.token=?
            """,
            (token,),
        ).fetchone()
        if row is None or row["expires_at"] < now_text():
            return None
        return {"user_id": row["user_id"], "display_name": row["display_name"], "role": row["role"]}

    def agent_authorized(self, token: str) -> bool:
        expected = self.setting("agent.token", DEFAULT_AGENT_TOKEN)
        return hmac.compare_digest(token or "", expected)

    def list_instances(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM mon_instance ORDER BY product, agent_alias"
        ).fetchall()
        return [dict(row) for row in rows]

    def save_instance(self, payload: dict, create: bool) -> None:
        alias = payload["agent_alias"].strip()
        if not alias:
            raise ValueError("에이전트 별칭이 필요합니다.")
        stamp = now_text()
        with self._lock:
            exists = self.conn.execute(
                "SELECT 1 FROM mon_instance WHERE agent_alias=?", (alias,)
            ).fetchone()
            if create and exists:
                raise ValueError("이미 등록된 인스턴스입니다.")
            if not create and not exists:
                raise ValueError("인스턴스를 찾을 수 없습니다.")
            if exists:
                self.conn.execute(
                    """
                    UPDATE mon_instance
                    SET product=?, host_nm=?, port=?, db_name=?, username=?, group_nm=?,
                        collect_interval_sec=?, enabled=?, description=?
                    WHERE agent_alias=?
                    """,
                    (
                        payload["product"],
                        payload["host_nm"],
                        int(payload["port"]),
                        payload.get("db_name") or "",
                        payload.get("username") or "",
                        payload.get("group_nm") or "",
                        int(payload.get("collect_interval_sec") or 5),
                        1 if payload.get("enabled", True) else 0,
                        payload.get("description") or "",
                        alias,
                    ),
                )
            else:
                self.conn.execute(
                    """
                    INSERT INTO mon_instance (
                        agent_alias, product, host_nm, port, db_name, username,
                        group_nm, collect_interval_sec, enabled, description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alias,
                        payload["product"],
                        payload["host_nm"],
                        int(payload["port"]),
                        payload.get("db_name") or "",
                        payload.get("username") or "",
                        payload.get("group_nm") or "",
                        int(payload.get("collect_interval_sec") or 5),
                        1 if payload.get("enabled", True) else 0,
                        payload.get("description") or "",
                        stamp,
                    ),
                )
            self.conn.commit()

    def delete_instance(self, alias: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM mon_instance WHERE agent_alias=?", (alias,))
            self.conn.commit()

    def ingest(self, payload: dict) -> dict:
        alias = payload["agent_alias"]
        collect_tm = payload["collect_tm"]
        product = payload.get("product") or ""
        perf = payload.get("performance") or {}
        status = payload.get("status") or "ONLINE"
        message = payload.get("message") or ""
        agent_url = (payload.get("agent_url") or "").strip() or None
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO agent_heartbeat (agent_alias, product, last_seen, status, message, version, agent_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_alias) DO UPDATE SET
                    product=excluded.product,
                    last_seen=excluded.last_seen,
                    status=excluded.status,
                    message=excluded.message,
                    version=excluded.version,
                    agent_url=COALESCE(excluded.agent_url, agent_heartbeat.agent_url)
                """,
                (alias, product, collect_tm, status, message, payload.get("version") or VERSION, agent_url),
            )
            if perf:
                self.conn.execute(
                    "DELETE FROM o_performance WHERE agent_alias=? AND agent_collect_tm=?",
                    (alias, collect_tm),
                )
                self.conn.execute(
                    """
                    INSERT INTO o_performance (
                        agent_alias, agent_collect_tm, instance_nm, cpu_usage, mem_usage,
                        active_sessions, connected_sessions, lock_wait, buffer_cache_ratio,
                        execute_cnt, user_commits, user_rollbacks, physical_reads, logical_reads,
                        tps, qps, redo_size, parse_hard, wait_user_io, wait_lock, wait_cpu,
                        wait_network, tablespace_used_pct, extra_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alias,
                        collect_tm,
                        perf.get("instance_nm") or alias,
                        _num(perf.get("cpu_usage")),
                        _num(perf.get("mem_usage")),
                        _int(perf.get("active_sessions")),
                        _int(perf.get("connected_sessions")),
                        _int(perf.get("lock_wait")),
                        _num(perf.get("buffer_cache_ratio")),
                        _int(perf.get("execute_cnt")),
                        _int(perf.get("user_commits")),
                        _int(perf.get("user_rollbacks")),
                        _int(perf.get("physical_reads")),
                        _int(perf.get("logical_reads")),
                        _num(perf.get("tps")),
                        _num(perf.get("qps")),
                        _int(perf.get("redo_size")),
                        _int(perf.get("parse_hard")),
                        _num(perf.get("wait_user_io")),
                        _num(perf.get("wait_lock")),
                        _num(perf.get("wait_cpu")),
                        _num(perf.get("wait_network")),
                        _num(perf.get("tablespace_used_pct")),
                        json.dumps(perf.get("extra") or {}, ensure_ascii=False),
                    ),
                )
                self._raise_threshold_events(alias, collect_tm, perf)
            self.conn.commit()
        return {"accepted": True, "agent_alias": alias, "collect_tm": collect_tm}

    def _insert_session(self, table: str, alias: str, collect_tm: str, row: dict, with_source: bool) -> None:
        columns = [
            "agent_alias",
            "agent_collect_tm",
            "sid",
            "serial_number",
            "status",
            "db_user",
            "os_user",
            "program",
            "module",
            "machine",
            "sql_id",
            "sql_text",
            "wait_event",
            "wait_class",
            "elapsed_ms",
            "blocking_sid",
            "cpu_used",
            "logical_reads",
            "physical_reads",
            "command",
        ]
        values = [
            alias,
            collect_tm,
            _int(row.get("sid")),
            _int(row.get("serial_number")),
            row.get("status") or "",
            row.get("db_user") or "",
            row.get("os_user") or "",
            row.get("program") or "",
            row.get("module") or "",
            row.get("machine") or "",
            row.get("sql_id") or "",
            row.get("sql_text") or "",
            row.get("wait_event") or "",
            row.get("wait_class") or "",
            _int(row.get("elapsed_ms")),
            _int(row.get("blocking_sid")),
            _num(row.get("cpu_used")),
            _int(row.get("logical_reads")),
            _int(row.get("physical_reads")),
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

    def _raise_threshold_events(self, alias: str, collect_tm: str, perf: dict) -> None:
        checks = [
            (
                "CPU",
                "CPU_HIGH",
                _num(perf.get("cpu_usage")),
                float(self.setting("threshold.cpu", "80")),
                "above",
                "CPU 사용률",
            ),
            (
                "SESSION",
                "ACTIVE_SESSION",
                _num(perf.get("active_sessions")),
                float(self.setting("threshold.active_sessions", "40")),
                "above",
                "Active Session",
            ),
            (
                "LOCK",
                "LOCK_WAIT",
                _num(perf.get("lock_wait")),
                float(self.setting("threshold.lock_wait", "1")),
                "above",
                "Lock Wait",
            ),
            (
                "CACHE",
                "BUFFER_HIT",
                _num(perf.get("buffer_cache_ratio")),
                float(self.setting("threshold.buffer_hit", "90")),
                "below",
                "Buffer Cache Hit",
            ),
        ]
        for severity_name, code, value, limit, direction, label in checks:
            if value is None:
                continue
            breached = value >= limit if direction == "above" else value < limit
            if not breached:
                continue
            self.conn.execute(
                """
                INSERT INTO event_log (agent_alias, occurred_at, event_cd, event_nm, severity, message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    alias,
                    collect_tm,
                    code,
                    label,
                    "WARN",
                    f"{label} {value:g} (기준 {limit:g})",
                ),
            )

    def latest_performance(self, alias: str | None = None) -> list[dict]:
        if alias:
            rows = self.conn.execute(
                """
                SELECT * FROM o_performance
                WHERE agent_alias=?
                ORDER BY agent_collect_tm DESC LIMIT 1
                """,
                (alias,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT p.* FROM o_performance p
                JOIN (
                    SELECT agent_alias, MAX(agent_collect_tm) AS tm
                    FROM o_performance GROUP BY agent_alias
                ) t ON t.agent_alias = p.agent_alias AND t.tm = p.agent_collect_tm
                """
            ).fetchall()
        return [_perf_dict(row) for row in rows]

    def performance_series(self, alias: str, start: str, end: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM o_performance
            WHERE agent_alias=? AND agent_collect_tm>=? AND agent_collect_tm<=?
            ORDER BY agent_collect_tm
            """,
            (alias, start, end),
        ).fetchall()
        return [_perf_dict(row) for row in rows]

    def current_sessions(self, alias: str) -> list[dict]:
        latest = self.conn.execute(
            "SELECT MAX(agent_collect_tm) AS tm FROM active_session WHERE agent_alias=?",
            (alias,),
        ).fetchone()
        if latest is None or latest["tm"] is None:
            return []
        rows = self.conn.execute(
            """
            SELECT * FROM active_session
            WHERE agent_alias=? AND agent_collect_tm=?
            ORDER BY CASE status WHEN 'ACTIVE' THEN 0 ELSE 1 END, elapsed_ms DESC
            """,
            (alias, latest["tm"]),
        ).fetchall()
        return [dict(row) for row in rows]

    def session_history(
        self, alias: str, start: str, end: str, sql_id: str = "", limit: int = 200
    ) -> list[dict]:
        sql = """
            SELECT * FROM session_history
            WHERE agent_alias=? AND agent_collect_tm>=? AND agent_collect_tm<=?
        """
        args: list = [alias, start, end]
        if sql_id:
            sql += " AND sql_id=?"
            args.append(sql_id)
        sql += " ORDER BY agent_collect_tm DESC, elapsed_ms DESC LIMIT ?"
        args.append(limit)
        rows = self.conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]

    def sql_catalog(self, alias: str, query: str = "", limit: int = 80) -> list[dict]:
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
            (alias, query.strip(), like, like, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def events(self, alias: str = "", limit: int = 40) -> list[dict]:
        if alias:
            rows = self.conn.execute(
                """
                SELECT * FROM event_log WHERE agent_alias=?
                ORDER BY occurred_at DESC LIMIT ?
                """,
                (alias, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM event_log ORDER BY occurred_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def agent_url(self, alias: str) -> str:
        row = self.conn.execute(
            "SELECT agent_url FROM agent_heartbeat WHERE agent_alias=?",
            (alias,),
        ).fetchone()
        if row is None or not row["agent_url"]:
            return ""
        return row["agent_url"]

    def heartbeats(self) -> dict[str, dict]:
        rows = self.conn.execute("SELECT * FROM agent_heartbeat").fetchall()
        return {row["agent_alias"]: dict(row) for row in rows}

    def dashboard(self) -> dict:
        instances = self.list_instances()
        latest = {row["agent_alias"]: row for row in self.latest_performance()}
        beats = self.heartbeats()
        cards = []
        for inst in instances:
            alias = inst["agent_alias"]
            perf = latest.get(alias, {})
            beat = beats.get(alias, {})
            alerts = []
            cpu = perf.get("cpu_usage")
            active = perf.get("active_sessions")
            locks = perf.get("lock_wait")
            hit = perf.get("buffer_cache_ratio")
            if cpu is not None and cpu >= float(self.setting("threshold.cpu", "80")):
                alerts.append("CPU")
            if active is not None and active >= float(self.setting("threshold.active_sessions", "40")):
                alerts.append("SESSION")
            if locks is not None and locks >= float(self.setting("threshold.lock_wait", "1")):
                alerts.append("LOCK")
            if hit is not None and hit < float(self.setting("threshold.buffer_hit", "90")):
                alerts.append("CACHE")
            online = beat.get("status") == "ONLINE"
            cards.append(
                {
                    "agent_alias": alias,
                    "product": inst["product"],
                    "host_nm": inst["host_nm"],
                    "port": inst["port"],
                    "db_name": inst["db_name"],
                    "group_nm": inst["group_nm"],
                    "description": inst["description"],
                    "enabled": inst["enabled"],
                    "status": beat.get("status") or "OFFLINE",
                    "online": online,
                    "last_seen": beat.get("last_seen"),
                    "message": beat.get("message") or "",
                    "cpu_usage": cpu,
                    "mem_usage": perf.get("mem_usage"),
                    "active_sessions": active,
                    "connected_sessions": perf.get("connected_sessions"),
                    "lock_wait": locks,
                    "buffer_cache_ratio": hit,
                    "execute_cnt": perf.get("execute_cnt"),
                    "tps": perf.get("tps"),
                    "qps": perf.get("qps"),
                    "alerts": alerts,
                }
            )
        title = self.setting("support.title", PRODUCT)
        version = self.setting("support.ver", VERSION)
        return {
            "title": title,
            "version": version,
            "display": display_name(title, version),
            "products": self.setting("support.products", ""),
            "generated_at": now_text(),
            "instances": cards,
            "events": self.events(limit=12),
        }

    def retention_status(self) -> list[dict]:
        policies = self.conn.execute(
            "SELECT * FROM retention_policy ORDER BY data_kind"
        ).fetchall()
        result = []
        for row in policies:
            meta = RETENTION_KINDS.get(row["data_kind"])
            if meta is None:
                continue
            count = self.conn.execute(f"SELECT COUNT(*) AS c FROM {meta['table']}").fetchone()["c"]
            result.append(
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
        return result

    def update_retention(self, updates: list[dict]) -> None:
        with self._lock:
            for item in updates:
                kind = item["data_kind"]
                if kind not in RETENTION_KINDS:
                    continue
                self.conn.execute(
                    "UPDATE retention_policy SET keep_days=?, enabled=? WHERE data_kind=?",
                    (int(item["keep_days"]), 1 if item.get("enabled", True) else 0, kind),
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
                meta = RETENTION_KINDS.get(kind)
                if meta is None:
                    continue
                if not policy["enabled"]:
                    summary.append(
                        {"data_kind": kind, "deleted_rows": 0, "skipped": True, "keep_days": policy["keep_days"]}
                    )
                    continue
                cutoff = now_text(moment - timedelta(days=int(policy["keep_days"])))
                cursor = self.conn.execute(
                    f"DELETE FROM {meta['table']} WHERE {meta['time_column']} < ?",
                    (cutoff,),
                )
                deleted = cursor.rowcount
                self.conn.execute(
                    """
                    UPDATE retention_policy
                    SET last_purge_at=?, last_deleted=?
                    WHERE data_kind=?
                    """,
                    (stamp, deleted, kind),
                )
                self.conn.execute(
                    """
                    INSERT INTO purge_log (ran_at, data_kind, keep_days, deleted_rows)
                    VALUES (?, ?, ?, ?)
                    """,
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

    def purge_log(self, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM purge_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def report(self, alias: str, start: str, end: str) -> dict:
        series = self.performance_series(alias, start, end)
        def avg(key: str) -> float | None:
            vals = [row[key] for row in series if row.get(key) is not None]
            if not vals:
                return None
            return round(sum(vals) / len(vals), 2)

        def peak(key: str) -> float | None:
            vals = [row[key] for row in series if row.get(key) is not None]
            if not vals:
                return None
            return round(max(vals), 2)

        return {
            "agent_alias": alias,
            "start": start,
            "end": end,
            "samples": len(series),
            "summary": {
                "cpu_avg": avg("cpu_usage"),
                "cpu_max": peak("cpu_usage"),
                "active_avg": avg("active_sessions"),
                "active_max": peak("active_sessions"),
                "lock_max": peak("lock_wait"),
                "buffer_avg": avg("buffer_cache_ratio"),
                "tps_avg": avg("tps"),
                "qps_avg": avg("qps"),
            },
            "top_sql": [],
            "events": self.events(alias, limit=15),
        }


def _num(value):
    if value is None or value == "":
        return None
    return float(value)


def _int(value):
    if value is None or value == "":
        return None
    return int(float(value))


def _perf_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    extra = item.get("extra_json")
    item["extra"] = json.loads(extra) if extra else {}
    item.pop("extra_json", None)
    return item
