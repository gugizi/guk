"""Live collectors for Oracle, Tibero, MariaDB, and PostgreSQL.

The agent is installed on the database host. It reads OS counters locally and
pulls active sessions, sampled session history, and SQL text from the instance.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agent.osmetrics import read_host_metrics
from agent.simulate import Simulator, sql_id
from collector.store import now_text


def make_collector(target: dict):
    mode = (target.get("mode") or "simulate").lower()
    product = target["product"].upper()
    if mode != "live":
        return Simulator(target)
    if product == "ORACLE":
        return OracleCollector(target)
    if product == "TIBERO":
        return TiberoCollector(target)
    if product == "MARIADB":
        return MariaCollector(target)
    if product == "POSTGRESQL":
        return PostgresCollector(target)
    raise ValueError(f"지원하지 않는 DBMS 입니다: {product}")


class LiveBase:
    def __init__(self, target: dict):
        self.target = target
        self.alias = target["agent_alias"]
        self.product = target["product"].upper()
        self._prev: dict[str, float] = {}
        self._sql_prev: dict[str, dict] = {}

    def delta_fields(self, sql_id: str, fields: dict) -> dict:
        """Turn cumulative SQL counters into the change since the previous sample."""
        previous = self._sql_prev.get(sql_id)
        self._sql_prev[sql_id] = fields
        if previous is None:
            return {key: (0 if isinstance(value, (int, float)) else value) for key, value in fields.items()}
        changed = {}
        for key, value in fields.items():
            if isinstance(value, (int, float)) and isinstance(previous.get(key), (int, float)):
                changed[key] = max(0, value - previous[key])
            else:
                changed[key] = value
        return changed

    def delta(self, key: str, value: float) -> float:
        previous = self._prev.get(key)
        self._prev[key] = value
        if previous is None:
            return 0
        return max(0, value - previous)

    def envelope(self, performance: dict, sessions: list[dict], history: list[dict], texts: list[dict], stats: list[dict]) -> dict:
        return {
            "agent_alias": self.alias,
            "product": self.product,
            "collect_tm": now_text(),
            "version": "5.0.1",
            "status": "ONLINE",
            "message": "live",
            "performance": performance,
            "active_sessions": sessions,
            "session_history": history,
            "sql_texts": texts,
            "sql_stats": stats,
        }


class OracleCollector(LiveBase):
    SYSSTAT = (
        "user commits",
        "user rollbacks",
        "execute count",
        "parse count (hard)",
        "physical reads",
        "db block gets",
        "consistent gets",
        "redo size",
        "session logical reads",
    )

    def collect(self) -> dict:
        import oracledb

        target = self.target
        dsn = oracledb.makedsn(target["host"], int(target["port"]), service_name=target.get("database") or "ORCL")
        with oracledb.connect(user=target["user"], password=target.get("password") or "", dsn=dsn) as conn:
            stats = _oracle_sysstat(conn, self.SYSSTAT)
            sessions = _oracle_sessions(conn)
            texts, sql_stats = _oracle_sql(conn)
        return self._pack(stats, sessions, texts, sql_stats)

    def _pack(self, stats: dict, sessions: list[dict], texts: list[dict], sql_stats: list[dict]) -> dict:
        commits = self.delta("commits", float(stats.get("user commits", 0)))
        rollbacks = self.delta("rollbacks", float(stats.get("user rollbacks", 0)))
        executes = self.delta("exec", float(stats.get("execute count", 0)))
        physical = self.delta("phy", float(stats.get("physical reads", 0)))
        logical = self.delta("logical", float(stats.get("db block gets", 0)) + float(stats.get("consistent gets", 0)))
        redo = self.delta("redo", float(stats.get("redo size", 0)))
        hard = self.delta("hard", float(stats.get("parse count (hard)", 0)))
        hit = 100.0 if logical <= 0 else max(0, min(100, (1 - physical / logical) * 100))
        active = sum(1 for row in sessions if row["status"] == "ACTIVE")
        locks = sum(1 for row in sessions if row.get("blocking_sid"))
        host = read_host_metrics()
        interval = float(self.target.get("interval_sec") or 5)
        history = [dict(row, source="sample") for row in sessions if row["status"] == "ACTIVE"]
        sql_stats = [_delta_sql(self, row) for row in sql_stats]
        performance = {
            "instance_nm": self.target.get("database") or self.alias,
            "cpu_usage": host["cpu_usage"],
            "mem_usage": host["mem_usage"],
            "active_sessions": active,
            "connected_sessions": len(sessions),
            "lock_wait": locks,
            "buffer_cache_ratio": round(hit, 2),
            "execute_cnt": int(executes),
            "user_commits": int(commits),
            "user_rollbacks": int(rollbacks),
            "physical_reads": int(physical),
            "logical_reads": int(logical),
            "tps": round(commits / interval, 2),
            "qps": round(executes / interval, 2),
            "redo_size": int(redo),
            "parse_hard": int(hard),
            "wait_user_io": round(max(0, 100 - hit) / 5, 2),
            "wait_lock": float(locks),
            "wait_cpu": host["cpu_usage"],
            "wait_network": 0,
            "tablespace_used_pct": None,
            "extra": {"mode": "live", "product": self.product},
        }
        return self.envelope(performance, sessions, history, texts, sql_stats)


class TiberoCollector(OracleCollector):
    """Tibero exposes Oracle-compatible V$SESSION / V$SYSSTAT / V$SQLAREA views."""

    def collect(self) -> dict:
        try:
            import jaydebeapi
        except ImportError as exc:
            raise RuntimeError(
                "Tibero 수집에는 JDBC 드라이버와 jaydebeapi가 필요합니다. "
                "tibero jdbc jar 경로를 TIBERO_JDBC_JAR 환경변수로 지정하세요."
            ) from exc
        import os

        jar = os.environ.get("TIBERO_JDBC_JAR", "")
        if not jar:
            raise RuntimeError("TIBERO_JDBC_JAR 가 설정되지 않았습니다.")
        target = self.target
        url = "jdbc:tibero:thin:@%s:%s:%s" % (target["host"], int(target["port"]), target.get("database") or "tibero")
        conn = jaydebeapi.connect(
            "com.tmax.tibero.jdbc.TbDriver",
            url,
            [target["user"], target.get("password") or ""],
            jar,
        )
        try:
            stats = dict(_fetch_pairs(conn, "SELECT name, value FROM v$sysstat WHERE name IN (%s)" % ",".join("?" * len(self.SYSSTAT)), self.SYSSTAT))
            sessions = _oracle_sessions(conn)
            texts, sql_stats = _oracle_sql(conn)
        finally:
            conn.close()
        return self._pack(stats, sessions, texts, sql_stats)


class MariaCollector(LiveBase):
    STATUS_NAMES = (
        "Threads_connected",
        "Threads_running",
        "Questions",
        "Com_commit",
        "Com_rollback",
        "Innodb_buffer_pool_read_requests",
        "Innodb_buffer_pool_reads",
        "Slow_queries",
        "Table_locks_waited",
        "Innodb_row_lock_current_waits",
    )

    def collect(self) -> dict:
        import pymysql

        target = self.target
        conn = pymysql.connect(
            host=target["host"],
            port=int(target["port"]),
            user=target["user"],
            password=target.get("password") or "",
            database=target.get("database") or None,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(self.STATUS_NAMES))
                cur.execute(
                    f"SHOW GLOBAL STATUS WHERE Variable_name IN ({placeholders})",
                    self.STATUS_NAMES,
                )
                status = {row["Variable_name"]: float(row["Value"]) for row in cur.fetchall()}
                cur.execute(
                    """
                    SELECT id, user, host, db, command, time, state, info
                    FROM information_schema.processlist
                    WHERE id <> CONNECTION_ID()
                    """
                )
                processlist = cur.fetchall()
                digest_rows = []
                history_rows = []
                try:
                    cur.execute(
                        """
                        SELECT DIGEST, DIGEST_TEXT, COUNT_STAR,
                               SUM_TIMER_WAIT/1000000000 AS elapsed_ms,
                               SUM_ROWS_EXAMINED, SUM_ROWS_SENT
                        FROM performance_schema.events_statements_summary_by_digest
                        WHERE DIGEST_TEXT IS NOT NULL
                        ORDER BY SUM_TIMER_WAIT DESC
                        LIMIT 40
                        """
                    )
                    digest_rows = cur.fetchall()
                except Exception:
                    digest_rows = []
                try:
                    cur.execute(
                        """
                        SELECT THREAD_ID, SQL_TEXT, TIMER_WAIT/1000000000 AS elapsed_ms
                        FROM performance_schema.events_statements_history
                        WHERE SQL_TEXT IS NOT NULL
                        ORDER BY TIMER_START DESC
                        LIMIT 40
                        """
                    )
                    history_rows = cur.fetchall()
                except Exception:
                    history_rows = []
        finally:
            conn.close()

        questions = self.delta("questions", status.get("Questions", 0))
        commits = self.delta("commits", status.get("Com_commit", 0))
        rollbacks = self.delta("rollbacks", status.get("Com_rollback", 0))
        pool_reads = self.delta("pool_reads", status.get("Innodb_buffer_pool_reads", 0))
        pool_req = self.delta("pool_req", status.get("Innodb_buffer_pool_read_requests", 0))
        hit = 100.0 if pool_req <= 0 else max(0, min(100, (1 - pool_reads / pool_req) * 100))
        host = read_host_metrics()
        interval = float(target.get("interval_sec") or 5)
        sessions = []
        for row in processlist:
            info = row.get("info") or ""
            command = (row.get("command") or "").upper()
            active = command not in {"SLEEP", "DAEMON", "BINLOG DUMP"}
            sessions.append(
                {
                    "sid": int(row["id"]),
                    "serial_number": 0,
                    "status": "ACTIVE" if active else "INACTIVE",
                    "db_user": row.get("user") or "",
                    "os_user": "",
                    "program": row.get("db") or "",
                    "module": command,
                    "machine": row.get("host") or "",
                    "sql_id": sql_id(info) if info else "",
                    "sql_text": info[:4000],
                    "wait_event": row.get("state") or "",
                    "wait_class": "Lock" if "lock" in (row.get("state") or "").lower() else ("CPU" if active else "Idle"),
                    "elapsed_ms": int(float(row.get("time") or 0) * 1000),
                    "blocking_sid": None,
                    "cpu_used": None,
                    "logical_reads": None,
                    "physical_reads": None,
                    "command": command,
                }
            )
        history = [dict(row, source="sample") for row in sessions if row["status"] == "ACTIVE"]
        for row in history_rows:
            text = row.get("SQL_TEXT") or ""
            history.append(
                {
                    "sid": int(row.get("THREAD_ID") or 0),
                    "serial_number": 0,
                    "status": "DONE",
                    "db_user": "",
                    "os_user": "",
                    "program": "",
                    "module": "",
                    "machine": "",
                    "sql_id": sql_id(text),
                    "sql_text": text[:4000],
                    "wait_event": "",
                    "wait_class": "CPU",
                    "elapsed_ms": int(float(row.get("elapsed_ms") or 0)),
                    "blocking_sid": None,
                    "cpu_used": None,
                    "logical_reads": None,
                    "physical_reads": None,
                    "command": "HISTORY",
                    "source": "performance_schema",
                }
            )
        texts = []
        stats = []
        for row in digest_rows:
            text = row.get("DIGEST_TEXT") or ""
            ident = row.get("DIGEST") or sql_id(text)
            texts.append({"sql_id": ident, "sql_text": text[:4000], "command_type": "", "db_user": ""})
            stats.append(
                _delta_sql(
                    self,
                    {
                        "sql_id": ident,
                        "executions": int(row.get("COUNT_STAR") or 0),
                        "elapsed_ms": float(row.get("elapsed_ms") or 0),
                        "cpu_ms": None,
                        "buffer_gets": None,
                        "disk_reads": None,
                        "rows_processed": int(row.get("SUM_ROWS_SENT") or 0),
                        "db_user": "",
                        "program": "performance_schema",
                    },
                )
            )
        for row in sessions:
            if row["sql_text"]:
                texts.append(
                    {
                        "sql_id": row["sql_id"],
                        "sql_text": row["sql_text"],
                        "command_type": row["command"],
                        "db_user": row["db_user"],
                    }
                )
        active = sum(1 for row in sessions if row["status"] == "ACTIVE")
        locks = int(status.get("Innodb_row_lock_current_waits", 0))
        performance = {
            "instance_nm": target.get("database") or self.alias,
            "cpu_usage": host["cpu_usage"],
            "mem_usage": host["mem_usage"],
            "active_sessions": active or int(status.get("Threads_running", 0)),
            "connected_sessions": int(status.get("Threads_connected", len(sessions))),
            "lock_wait": locks,
            "buffer_cache_ratio": round(hit, 2),
            "execute_cnt": int(questions),
            "user_commits": int(commits),
            "user_rollbacks": int(rollbacks),
            "physical_reads": int(pool_reads),
            "logical_reads": int(pool_req),
            "tps": round(commits / interval, 2),
            "qps": round(questions / interval, 2),
            "redo_size": None,
            "parse_hard": None,
            "wait_user_io": None,
            "wait_lock": float(locks),
            "wait_cpu": host["cpu_usage"],
            "wait_network": None,
            "tablespace_used_pct": None,
            "extra": {
                "mode": "live",
                "slow_queries": int(status.get("Slow_queries", 0)),
                "table_locks_waited": int(status.get("Table_locks_waited", 0)),
            },
        }
        return self.envelope(performance, sessions, history, texts, stats)


class PostgresCollector(LiveBase):
    def collect(self) -> dict:
        import psycopg

        target = self.target
        conn = psycopg.connect(
            host=target["host"],
            port=int(target["port"]),
            user=target["user"],
            password=target.get("password") or "",
            dbname=target.get("database") or "postgres",
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT datname, xact_commit, xact_rollback, blks_hit, blks_read,
                           tup_returned, tup_fetched, deadlocks, numbackends
                    FROM pg_stat_database
                    WHERE datname = current_database()
                    """
                )
                dbrow = cur.fetchone()
                cur.execute(
                    """
                    SELECT pid, usename, application_name, client_addr::text, state,
                           wait_event_type, wait_event, query,
                           EXTRACT(EPOCH FROM (clock_timestamp() - COALESCE(query_start, xact_start, backend_start))) * 1000 AS elapsed_ms,
                           (pg_blocking_pids(pid))[1] AS blocking_pid
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND pid <> pg_backend_pid()
                    """
                )
                activity = cur.fetchall()
                statements = []
                try:
                    cur.execute(
                        """
                        SELECT queryid::text, query, calls, total_exec_time, mean_exec_time,
                               rows, shared_blks_hit, shared_blks_read
                        FROM pg_stat_statements
                        ORDER BY total_exec_time DESC
                        LIMIT 40
                        """
                    )
                    statements = cur.fetchall()
                except Exception:
                    conn.rollback()
                    statements = []
        finally:
            conn.close()

        names = ["datname", "xact_commit", "xact_rollback", "blks_hit", "blks_read", "tup_returned", "tup_fetched", "deadlocks", "numbackends"]
        stat = dict(zip(names, dbrow))
        commits = self.delta("commits", float(stat["xact_commit"]))
        rollbacks = self.delta("rollbacks", float(stat["xact_rollback"]))
        hits = self.delta("hits", float(stat["blks_hit"]))
        reads = self.delta("reads", float(stat["blks_read"]))
        logical = hits + reads
        hit_ratio = 100.0 if logical <= 0 else max(0, min(100, hits / logical * 100))
        host = read_host_metrics()
        interval = float(target.get("interval_sec") or 5)
        sessions = []
        for pid, user, app, client, state, wait_type, wait_event, query, elapsed, blocking in activity:
            text = query or ""
            active = (state or "") == "active"
            sessions.append(
                {
                    "sid": int(pid),
                    "serial_number": 0,
                    "status": "ACTIVE" if active else "INACTIVE",
                    "db_user": user or "",
                    "os_user": "",
                    "program": app or "",
                    "module": state or "",
                    "machine": client or "",
                    "sql_id": sql_id(text) if text else "",
                    "sql_text": text[:4000],
                    "wait_event": wait_event or "",
                    "wait_class": wait_type or ("CPU" if active else "Idle"),
                    "elapsed_ms": int(elapsed or 0),
                    "blocking_sid": int(blocking) if blocking else None,
                    "cpu_used": None,
                    "logical_reads": None,
                    "physical_reads": None,
                    "command": "QUERY" if active else "IDLE",
                }
            )
        history = [dict(row, source="sample") for row in sessions if row["status"] == "ACTIVE"]
        texts = []
        sql_stats = []
        for queryid, query, calls, total_ms, mean_ms, rows, blks_hit, blks_read in statements:
            ident = queryid or sql_id(query or "")
            texts.append({"sql_id": ident, "sql_text": (query or "")[:4000], "command_type": "STATEMENT", "db_user": ""})
            sql_stats.append(
                _delta_sql(
                    self,
                    {
                        "sql_id": ident,
                        "executions": int(calls or 0),
                        "elapsed_ms": float(total_ms or 0),
                        "cpu_ms": None,
                        "buffer_gets": int(blks_hit or 0),
                        "disk_reads": int(blks_read or 0),
                        "rows_processed": int(rows or 0),
                        "db_user": "",
                        "program": "pg_stat_statements",
                    },
                )
            )
        for row in sessions:
            if row["status"] == "ACTIVE" and row["sql_text"]:
                texts.append(
                    {"sql_id": row["sql_id"], "sql_text": row["sql_text"], "command_type": "ACTIVE", "db_user": row["db_user"]}
                )
        active = sum(1 for row in sessions if row["status"] == "ACTIVE")
        locks = sum(1 for row in sessions if row.get("blocking_sid"))
        performance = {
            "instance_nm": stat["datname"],
            "cpu_usage": host["cpu_usage"],
            "mem_usage": host["mem_usage"],
            "active_sessions": active,
            "connected_sessions": int(stat["numbackends"]),
            "lock_wait": locks,
            "buffer_cache_ratio": round(hit_ratio, 2),
            "execute_cnt": int(commits + rollbacks),
            "user_commits": int(commits),
            "user_rollbacks": int(rollbacks),
            "physical_reads": int(reads),
            "logical_reads": int(logical),
            "tps": round((commits + rollbacks) / interval, 2),
            "qps": round((commits + rollbacks) / interval, 2),
            "redo_size": None,
            "parse_hard": None,
            "wait_user_io": None,
            "wait_lock": float(locks),
            "wait_cpu": host["cpu_usage"],
            "wait_network": None,
            "tablespace_used_pct": None,
            "extra": {"mode": "live", "deadlocks": int(stat["deadlocks"] or 0), "tup_fetched": int(stat["tup_fetched"] or 0)},
        }
        return self.envelope(performance, sessions, history, texts, sql_stats)


def _delta_sql(collector: LiveBase, row: dict) -> dict:
    changed = collector.delta_fields(
        row["sql_id"],
        {
            "executions": row.get("executions") or 0,
            "elapsed_ms": row.get("elapsed_ms") or 0,
            "cpu_ms": row.get("cpu_ms") or 0,
            "buffer_gets": row.get("buffer_gets") or 0,
            "disk_reads": row.get("disk_reads") or 0,
            "rows_processed": row.get("rows_processed") or 0,
        },
    )
    return {**row, **changed}


def _oracle_sysstat(conn, names: tuple[str, ...]) -> dict[str, float]:
    binds = {f"n{index}": name for index, name in enumerate(names)}
    sql = "SELECT name, value FROM v$sysstat WHERE name IN (%s)" % ",".join(
        f":n{index}" for index in range(len(names))
    )
    cur = conn.cursor()
    try:
        cur.execute(sql, binds)
        return {row[0]: float(row[1]) for row in cur.fetchall()}
    finally:
        cur.close()


def _fetch_pairs(conn, sql: str, params: tuple) -> list[tuple]:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return [(row[0], float(row[1])) for row in cur.fetchall()]
    finally:
        cur.close()


def _oracle_sessions(conn) -> list[dict]:
    sql = """
        SELECT s.sid,
               s.serial#,
               s.username,
               s.status,
               s.osuser,
               s.program,
               s.module,
               s.machine,
               s.sql_id,
               s.event,
               s.wait_class,
               s.blocking_session,
               s.last_call_et,
               (SELECT SUBSTR(q.sql_text, 1, 1000)
                  FROM v$sql q
                 WHERE q.sql_id = s.sql_id
                   AND q.child_number = s.sql_child_number
                   AND ROWNUM = 1) sql_text
          FROM v$session s
         WHERE s.type = 'USER'
    """
    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchall()
    finally:
        cur.close()
    sessions = []
    for sid, serial, username, status, osuser, program, module, machine, ident, event, wait_class, blocking, elapsed, text in rows:
        sessions.append(
            {
                "sid": int(sid),
                "serial_number": int(serial or 0),
                "status": status or "",
                "db_user": username or "",
                "os_user": osuser or "",
                "program": program or "",
                "module": module or "",
                "machine": machine or "",
                "sql_id": ident or (sql_id(text) if text else ""),
                "sql_text": (text or "")[:4000],
                "wait_event": event or "",
                "wait_class": wait_class or "",
                "elapsed_ms": int(float(elapsed or 0) * 1000),
                "blocking_sid": int(blocking) if blocking else None,
                "cpu_used": None,
                "logical_reads": None,
                "physical_reads": None,
                "command": "",
            }
        )
    return sessions


def _oracle_sql(conn) -> tuple[list[dict], list[dict]]:
    sql = """
        SELECT sql_id,
               SUBSTR(sql_text, 1, 1000),
               executions,
               elapsed_time/1000,
               cpu_time/1000,
               buffer_gets,
               disk_reads,
               rows_processed,
               parsing_schema_name
          FROM v$sql
         WHERE last_active_time > SYSDATE - 1/24
           AND executions > 0
         ORDER BY elapsed_time DESC
         FETCH FIRST 40 ROWS ONLY
    """
    cur = conn.cursor()
    try:
        try:
            cur.execute(sql)
        except Exception:
            cur.execute(
                """
                SELECT * FROM (
                    SELECT sql_id, SUBSTR(sql_text, 1, 1000), executions,
                           elapsed_time/1000, cpu_time/1000, buffer_gets, disk_reads,
                           rows_processed, parsing_schema_name
                      FROM v$sql
                     WHERE last_active_time > SYSDATE - 1/24
                       AND executions > 0
                     ORDER BY elapsed_time DESC
                ) WHERE ROWNUM <= 40
                """
            )
        fetched = cur.fetchall()
    finally:
        cur.close()
    texts = []
    stats = []
    for ident, text, executions, elapsed, cpu, buffers, disks, rows, schema in fetched:
        texts.append({"sql_id": ident, "sql_text": text or "", "command_type": "", "db_user": schema or ""})
        stats.append(
            {
                "sql_id": ident,
                "executions": int(executions or 0),
                "elapsed_ms": float(elapsed or 0),
                "cpu_ms": float(cpu or 0),
                "buffer_gets": int(buffers or 0),
                "disk_reads": int(disks or 0),
                "rows_processed": int(rows or 0),
                "db_user": schema or "",
                "program": "v$sql",
            }
        )
    return texts, stats


def fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:13]


def empty_error(target: dict, message: str) -> dict[str, Any]:
    return {
        "agent_alias": target["agent_alias"],
        "product": target.get("product") or "",
        "collect_tm": now_text(),
        "version": "5.0.1",
        "status": "ERROR",
        "message": message[:500],
        "performance": None,
        "active_sessions": [],
        "session_history": [],
        "sql_texts": [],
        "sql_stats": [],
    }
