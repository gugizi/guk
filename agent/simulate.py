"""Deterministic demo samples for instances that are not connected yet."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime

from collector.store import now_text

CATALOG = {
    "ORACLE": [
        ("SELECT o.order_id, o.status, c.name FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.created_at > SYSDATE-1", "SELECT", "APP_ORDER", "JDBC Thin Client"),
        ("UPDATE orders SET status='PAID' WHERE order_id=:1", "UPDATE", "APP_PAY", "JDBC Thin Client"),
        ("SELECT /*+ FULL(t) */ * FROM audit_log t WHERE event_dt > SYSDATE-1/24", "SELECT", "BATCH", "sqlplus"),
        ("INSERT INTO payment_hist SELECT * FROM payment_stage WHERE batch_id=:1", "INSERT", "APP_PAY", "JDBC Thin Client"),
        ("SELECT sid, event, seconds_in_wait FROM v$session WHERE status='ACTIVE'", "SELECT", "MONITOR", "spacemon-agent"),
    ],
    "TIBERO": [
        ("SELECT emp_no, dept_cd, salary FROM erp.employee WHERE dept_cd=:1", "SELECT", "ERP_HR", "tbJDBC"),
        ("UPDATE erp.slip SET close_yn='Y' WHERE slip_dt=:1 AND dept_cd=:2", "UPDATE", "ERP_FIN", "tbJDBC"),
        ("SELECT item_cd, SUM(qty) FROM erp.stock GROUP BY item_cd", "SELECT", "ERP_INV", "tbJDBC"),
        ("DELETE FROM erp.if_queue WHERE created_at < SYSDATE-7", "DELETE", "ERP_IF", "tbSQL"),
    ],
    "MARIADB": [
        ("SELECT id, user_id, amount FROM payments WHERE status='PENDING' ORDER BY id LIMIT 50", "SELECT", "web", "mysql-connector"),
        ("UPDATE sessions SET last_seen=NOW() WHERE token=?", "UPDATE", "web", "mysql-connector"),
        ("SELECT COUNT(*) FROM click_log WHERE created_at > NOW() - INTERVAL 5 MINUTE", "SELECT", "analytics", "mysql-connector"),
        ("INSERT INTO audit (user_id, action, created_at) VALUES (?, ?, NOW())", "INSERT", "web", "mysql-connector"),
    ],
    "POSTGRESQL": [
        ("SELECT day, SUM(revenue) FROM fact_sales WHERE day >= CURRENT_DATE - 30 GROUP BY day", "SELECT", "bi", "psql"),
        ("SELECT customer_id, COUNT(*) FROM events WHERE ts > now() - interval '15 minutes' GROUP BY 1 ORDER BY 2 DESC LIMIT 20", "SELECT", "analytics", "psycopg"),
        ("UPDATE warehouse.job SET status='RUNNING', started_at=now() WHERE id=$1", "UPDATE", "etl", "psycopg"),
        ("SELECT pid, state, query FROM pg_stat_activity WHERE state='active'", "SELECT", "monitor", "spacemon-agent"),
    ],
}


def sql_id(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:13]


class Simulator:
    def __init__(self, target: dict):
        self.target = target
        self.alias = target["agent_alias"]
        self.product = target["product"].upper()
        self.catalog = CATALOG.get(self.product, CATALOG["ORACLE"])
        self._tick = 0

    def collect(self, moment: datetime | None = None) -> dict:
        moment = moment or datetime.now()
        self._tick += 1
        phase = moment.timestamp() / 40 + _bias(self.alias)
        cpu = _wave(phase, 28, 72, 18)
        if self.product == "ORACLE":
            cpu = min(96, cpu + 8)
        mem = _wave(phase + 1.2, 48, 78, 8)
        active = int(_wave(phase + 0.4, 4, 28, 6))
        if self.product == "POSTGRESQL":
            active = max(2, active // 2)
        connected = active + int(_wave(phase, 20, 90, 10))
        lock_wait = 2 if (self.product in {"ORACLE", "TIBERO"} and int(phase) % 17 == 0) else (1 if active > 24 else 0)
        hit = round(min(99.8, 96 + math.sin(phase) * 3), 2)
        if lock_wait and self.product == "ORACLE":
            hit = round(hit - 8, 2)
        executes = int(80 + active * 12 + (self._tick % 7) * 3)
        commits = int(executes * 0.35)
        rollbacks = 1 if self._tick % 11 == 0 else 0
        physical = int(400 + (100 - hit) * 30)
        logical = physical * 25
        sessions = self._sessions(moment, active, connected, lock_wait)
        history = [dict(row, source="sample") for row in sessions if row["status"] == "ACTIVE"]
        active = sum(1 for row in sessions if row["status"] == "ACTIVE")
        connected = len(sessions)
        lock_wait = sum(1 for row in sessions if row.get("blocking_sid"))
        texts = []
        stats = []
        for text, command, user, program in self.catalog:
            sid = sql_id(text)
            texts.append(
                {"sql_id": sid, "sql_text": text, "command_type": command, "db_user": user}
            )
            weight = 1 + (hash(sid) % 5)
            stats.append(
                {
                    "sql_id": sid,
                    "executions": executes // weight,
                    "elapsed_ms": round(executes * weight * 1.7, 1),
                    "cpu_ms": round(executes * weight * 0.6, 1),
                    "buffer_gets": logical // weight,
                    "disk_reads": physical // weight,
                    "rows_processed": executes * 3 // weight,
                    "db_user": user,
                    "program": program,
                }
            )
        extra = {"product": self.product, "mode": "simulate"}
        if self.product == "MARIADB":
            extra["innodb_buffer_pool_hit"] = hit
            extra["slow_queries"] = 1 if cpu > 70 else 0
        elif self.product == "POSTGRESQL":
            extra["blks_hit"] = logical
            extra["deadlocks"] = 1 if lock_wait else 0
        elif self.product in {"ORACLE", "TIBERO"}:
            extra["library_hit"] = round(min(99.5, hit + 1.2), 2)
            extra["shared_pool_free_mb"] = round(400 - cpu, 1)
        return {
            "agent_alias": self.alias,
            "product": self.product,
            "collect_tm": now_text(moment),
            "version": "5.0.1",
            "status": "ONLINE",
            "message": "simulate",
            "performance": {
                "instance_nm": self.target.get("database") or self.alias,
                "cpu_usage": round(cpu, 2),
                "mem_usage": round(mem, 2),
                "active_sessions": active,
                "connected_sessions": connected,
                "lock_wait": lock_wait,
                "buffer_cache_ratio": hit,
                "execute_cnt": executes,
                "user_commits": commits,
                "user_rollbacks": rollbacks,
                "physical_reads": physical,
                "logical_reads": logical,
                "tps": round(commits / 5, 2),
                "qps": round(executes / 5, 2),
                "redo_size": executes * 180,
                "parse_hard": max(0, executes // 40),
                "wait_user_io": round(max(0, 100 - hit) / 4, 2),
                "wait_lock": float(lock_wait),
                "wait_cpu": round(cpu / 10, 2),
                "wait_network": round(2 + math.sin(phase) , 2),
                "tablespace_used_pct": round(62 + (hash(self.alias) % 15) + math.sin(phase / 5), 2),
                "extra": extra,
            },
            "active_sessions": sessions,
            "session_history": history,
            "sql_texts": texts,
            "sql_stats": stats,
        }

    def _sessions(self, moment: datetime, active: int, connected: int, lock_wait: int) -> list[dict]:
        rows = []
        shown = min(connected, max(active, 8), 16)
        blocker = 100 + (hash(self.alias) % 20)
        for index in range(shown):
            text, command, user, program = self.catalog[index % len(self.catalog)]
            is_active = index < active
            sid = 100 + index
            waiting = lock_wait > 0 and index == 1
            rows.append(
                {
                    "sid": sid,
                    "serial_number": 1000 + index,
                    "status": "ACTIVE" if is_active else "INACTIVE",
                    "db_user": user,
                    "os_user": "app" if index % 2 == 0 else "batch",
                    "program": program,
                    "module": command,
                    "machine": self.target.get("host") or "localhost",
                    "sql_id": sql_id(text) if is_active or index < 3 else "",
                    "sql_text": text if is_active else "",
                    "wait_event": "enq: TX - row lock contention" if waiting else ("db file sequential read" if is_active else "SQL*Net message from client"),
                    "wait_class": "Lock" if waiting else ("User I/O" if is_active else "Idle"),
                    "elapsed_ms": (800 + index * 450) if is_active else 0,
                    "blocking_sid": blocker if waiting else None,
                    "cpu_used": round(0.4 + index * 0.15, 2) if is_active else 0,
                    "logical_reads": 1200 * (index + 1) if is_active else 10,
                    "physical_reads": 40 * (index + 1) if is_active else 0,
                    "command": command if is_active else "IDLE",
                }
            )
        if lock_wait:
            holder_text = self.catalog[0][0]
            rows.append(
                {
                    "sid": blocker,
                    "serial_number": 9,
                    "status": "ACTIVE",
                    "db_user": self.catalog[0][2],
                    "os_user": "app",
                    "program": self.catalog[0][3],
                    "module": "UPDATE",
                    "machine": self.target.get("host") or "localhost",
                    "sql_id": sql_id(holder_text),
                    "sql_text": holder_text,
                    "wait_event": "ON CPU",
                    "wait_class": "CPU",
                    "elapsed_ms": 4200,
                    "blocking_sid": None,
                    "cpu_used": 1.8,
                    "logical_reads": 8800,
                    "physical_reads": 20,
                    "command": "UPDATE",
                }
            )
        return rows


def _bias(alias: str) -> float:
    return (hash(alias) % 100) / 20


def _wave(phase: float, low: float, high: float, wobble: float) -> float:
    mid = (low + high) / 2
    amp = (high - low) / 2
    return mid + amp * math.sin(phase) + wobble * math.sin(phase * 2.3) * 0.15
