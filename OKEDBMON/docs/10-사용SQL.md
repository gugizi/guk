# OKEDBMON 사용 SQL

- 버전: 1.0.0.0
- 기준일: 2026-11-14
- 원본: `agent/collectors.py`, `collector/store.py`, `agent/simulate.py`

에이전트가 대상 DB에서 실행하는 문과, 수집서버가 `data/okedbmon.sqlite`에서 실행하는 문을 나누어 적었다. `:n`, `?`, `%s`는 바인드 자리다. 시뮬레이터 문장은 대상 DB에 실행하지 않고, 수집 결과의 SQL Text로만 넣는다.

## 1. Oracle

`OracleCollector`. 드라이버는 `oracledb`. Tibero도 같은 문을 쓴다. Tibero는 5절이다.

### 1.1 성능 카운터

`V$SYSSTAT`에서 아래 이름만 읽는다.

- `user commits`
- `user rollbacks`
- `execute count`
- `parse count (hard)`
- `physical reads`
- `db block gets`
- `consistent gets`
- `redo size`
- `session logical reads`

```sql
SELECT name, value
  FROM v$sysstat
 WHERE name IN (:n0, :n1, :n2, :n3, :n4, :n5, :n6, :n7, :n8)
```

누적값의 차이로 TPS, QPS, 버퍼 적중률을 만든다. 논리 읽기는 `db block gets`와 `consistent gets`의 합이다.

### 1.2 세션

사용자 세션과 그 세션의 SQL 앞 1000자를 읽는다.

```sql
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
```

`status`가 `ACTIVE`인 행만 Session History에 `source = sample`로 넣는다. `last_call_et`는 초이므로 1000을 곱해 ms로 저장한다.

### 1.3 SQL 통계

최근 1시간, 실행 횟수가 1 이상인 SQL을 경과 시간이 긴 순으로 40건 읽는다. `elapsed_time`과 `cpu_time`은 마이크로초이므로 1000으로 나누어 ms로 저장한다.

```sql
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
```

`FETCH FIRST`가 실패하면 아래 문으로 다시 실행한다.

```sql
SELECT * FROM (
    SELECT sql_id, SUBSTR(sql_text, 1, 1000), executions,
           elapsed_time/1000, cpu_time/1000, buffer_gets, disk_reads,
           rows_processed, parsing_schema_name
      FROM v$sql
     WHERE last_active_time > SYSDATE - 1/24
       AND executions > 0
     ORDER BY elapsed_time DESC
) WHERE ROWNUM <= 40
```

실행 횟수와 경과 시간은 누적값이다. 에이전트는 이전 샘플과의 차이만 수집서버로 보낸다. 첫 샘플의 차이는 0이다.

## 2. MariaDB

`MariaCollector`. 드라이버는 `pymysql`.

### 2.1 전역 상태

```sql
SHOW GLOBAL STATUS
 WHERE Variable_name IN (
       'Threads_connected',
       'Threads_running',
       'Questions',
       'Com_commit',
       'Com_rollback',
       'Innodb_buffer_pool_read_requests',
       'Innodb_buffer_pool_reads',
       'Slow_queries',
       'Table_locks_waited',
       'Innodb_row_lock_current_waits'
 )
```

`Questions`, `Com_commit`, `Com_rollback`, InnoDB 버퍼 풀 읽기는 누적값의 차이를 쓴다. Lock 대기는 `Innodb_row_lock_current_waits`의 현재 값이다.

### 2.2 프로세스

에이전트 자신의 연결은 빼다.

```sql
SELECT id, user, host, db, command, time, state, info
  FROM information_schema.processlist
 WHERE id <> CONNECTION_ID()
```

`command`가 `SLEEP`, `DAEMON`, `BINLOG DUMP`가 아니면 Active로 본다. `time`은 초이므로 1000을 곱한다. `info`가 있으면 그 문장을 SQL Text로 저장한다.

### 2.3 SQL 다이제스트

`performance_schema`가 없으면 이 조회는 건너뛰고 프로세스 목록만 남긴다.

```sql
SELECT DIGEST, DIGEST_TEXT, COUNT_STAR,
       SUM_TIMER_WAIT/1000000000 AS elapsed_ms,
       SUM_ROWS_EXAMINED, SUM_ROWS_SENT
  FROM performance_schema.events_statements_summary_by_digest
 WHERE DIGEST_TEXT IS NOT NULL
 ORDER BY SUM_TIMER_WAIT DESC
 LIMIT 40
```

`SUM_TIMER_WAIT`는 피코초이므로 1,000,000,000으로 나누어 ms로 만든다. `COUNT_STAR`와 경과 시간은 누적값이라 이전 샘플과의 차이만 보낸다.

### 2.4 문장 이력

```sql
SELECT THREAD_ID, SQL_TEXT, TIMER_WAIT/1000000000 AS elapsed_ms
  FROM performance_schema.events_statements_history
 WHERE SQL_TEXT IS NOT NULL
 ORDER BY TIMER_START DESC
 LIMIT 40
```

이 결과는 Session History에 `source = performance_schema`, `command = HISTORY`로 넣는다.

## 3. PostgreSQL

`PostgresCollector`. 드라이버는 `psycopg`. 접속한 데이터베이스만 본다.

### 3.1 데이터베이스 통계

```sql
SELECT datname, xact_commit, xact_rollback, blks_hit, blks_read,
       tup_returned, tup_fetched, deadlocks, numbackends
  FROM pg_stat_database
 WHERE datname = current_database()
```

커밋, 롤백, 블록 적중, 블록 읽기는 누적값의 차이를 쓴다. 적중률은 `blks_hit / (blks_hit + blks_read)`다.

### 3.2 세션

```sql
SELECT pid, usename, application_name, client_addr::text, state,
       wait_event_type, wait_event, query,
       EXTRACT(EPOCH FROM (clock_timestamp() - COALESCE(query_start, xact_start, backend_start))) * 1000 AS elapsed_ms,
       (pg_blocking_pids(pid))[1] AS blocking_pid
  FROM pg_stat_activity
 WHERE datname = current_database()
   AND pid <> pg_backend_pid()
```

`state`가 `active`인 행이 Active Session이다. `query`를 SQL Text로 저장하고, Active 행만 Session History에 `source = sample`로 넣는다.

### 3.3 SQL 통계

`pg_stat_statements`가 없으면 이 조회는 롤백하고 건너뛴다.

```sql
SELECT queryid::text, query, calls, total_exec_time, mean_exec_time,
       rows, shared_blks_hit, shared_blks_read
  FROM pg_stat_statements
 ORDER BY total_exec_time DESC
 LIMIT 40
```

`calls`, `total_exec_time`, `rows`, 블록 수는 누적값의 차이를 보낸다. `total_exec_time` 단위는 ms다.

## 4. Tibero

`TiberoCollector`는 Oracle과 같은 `V$`를 JDBC로 읽는다. 드라이버는 `jaydebeapi`, JAR 경로는 환경변수 `TIBERO_JDBC_JAR`다. 이름 조건은 `?` 바인드다.

```sql
SELECT name, value
  FROM v$sysstat
 WHERE name IN (?, ?, ?, ?, ?, ?, ?, ?, ?)
```

세션 문과 SQL 문은 1.2, 1.3과 같다. SQL 통계도 Oracle과 같이 `FETCH FIRST`를 먼저 시도하고, 실패하면 `ROWNUM` 문을 실행한다.

## 5. 수집서버 SQLite

파일은 `data/okedbmon.sqlite`다. 연결마다 다음을 실행한다.

```sql
PRAGMA journal_mode=WAL
PRAGMA busy_timeout=5000
PRAGMA foreign_keys=ON
```

`agent_heartbeat`에 `agent_url`이 없으면 한 번 더 실행한다.

```sql
PRAGMA table_info(agent_heartbeat)
ALTER TABLE agent_heartbeat ADD COLUMN agent_url TEXT
```

### 5.1 처음 열 때

설정 키와 보관 정책은 없을 때만 넣는다.

```sql
INSERT INTO env_setting (setting_key, setting_value, description, updated_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(setting_key) DO NOTHING

INSERT INTO retention_policy (data_kind, keep_days, enabled)
VALUES (?, ?, 1)
ON CONFLICT(data_kind) DO NOTHING

SELECT 1 FROM app_user WHERE user_id='admin'

INSERT INTO app_user (user_id, password_hash, display_name, role)
VALUES (?, ?, ?, ?)

SELECT COUNT(*) AS c FROM mon_instance

INSERT INTO mon_instance (
    agent_alias, product, host_nm, port, db_name, username,
    group_nm, collect_interval_sec, enabled, description, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
```

예전 제품명이 남아 있으면 제목, 버전, 저장 경로, 에이전트 토큰을 현재 값으로 바꾼다.

```sql
UPDATE env_setting
   SET setting_value=?, description=?, updated_at=?
 WHERE setting_key='support.title'

UPDATE env_setting
   SET setting_value=?, description=?, updated_at=?
 WHERE setting_key='support.ver'

UPDATE env_setting
   SET setting_value=?, updated_at=?
 WHERE setting_key='db.repository.path'

UPDATE env_setting
   SET setting_value=?, updated_at=?
 WHERE setting_key='agent.token'
```

### 5.2 로그인과 설정

```sql
SELECT password_hash FROM app_user WHERE user_id=?

INSERT INTO auth_token (token, user_id, expires_at) VALUES (?, ?, ?)

SELECT u.user_id, u.display_name, u.role, t.expires_at
  FROM auth_token t
  JOIN app_user u ON u.user_id = t.user_id
 WHERE t.token=?

SELECT setting_value FROM env_setting WHERE setting_key=?

SELECT setting_key, setting_value, description, updated_at
  FROM env_setting
 ORDER BY setting_key

SELECT 1 FROM env_setting WHERE setting_key=?

UPDATE env_setting
   SET setting_value=?, updated_at=?
 WHERE setting_key=?
```

### 5.3 인스턴스

```sql
SELECT * FROM mon_instance ORDER BY product, agent_alias

SELECT 1 FROM mon_instance WHERE agent_alias=?

UPDATE mon_instance
   SET product=?, host_nm=?, port=?, db_name=?, username=?, group_nm=?,
       collect_interval_sec=?, enabled=?, description=?
 WHERE agent_alias=?

INSERT INTO mon_instance (
    agent_alias, product, host_nm, port, db_name, username,
    group_nm, collect_interval_sec, enabled, description, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

DELETE FROM mon_instance WHERE agent_alias=?
```

### 5.4 수집 수신

한 트랜잭션이다. 같은 별칭, 같은 시각의 성능과 Active Session은 지우고 다시 넣는다.

```sql
INSERT INTO agent_heartbeat (agent_alias, product, last_seen, status, message, version, agent_url)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(agent_alias) DO UPDATE SET
    product=excluded.product,
    last_seen=excluded.last_seen,
    status=excluded.status,
    message=excluded.message,
    version=excluded.version,
    agent_url=COALESCE(excluded.agent_url, agent_heartbeat.agent_url)

DELETE FROM o_performance WHERE agent_alias=? AND agent_collect_tm=?

INSERT INTO o_performance (
    agent_alias, agent_collect_tm, instance_nm, cpu_usage, mem_usage,
    active_sessions, connected_sessions, lock_wait, buffer_cache_ratio,
    execute_cnt, user_commits, user_rollbacks, physical_reads, logical_reads,
    tps, qps, redo_size, parse_hard, wait_user_io, wait_lock, wait_cpu,
    wait_network, tablespace_used_pct, extra_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

DELETE FROM active_session WHERE agent_alias=? AND agent_collect_tm=?

INSERT INTO sql_text (
    agent_alias, sql_id, sql_text, command_type, db_user, first_seen, last_seen
) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(agent_alias, sql_id) DO UPDATE SET
    sql_text=excluded.sql_text,
    command_type=excluded.command_type,
    db_user=excluded.db_user,
    last_seen=excluded.last_seen

INSERT INTO sql_stat (
    agent_alias, agent_collect_tm, sql_id, executions, elapsed_ms, cpu_ms,
    buffer_gets, disk_reads, rows_processed, db_user, program
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

INSERT INTO event_log (agent_alias, occurred_at, event_cd, event_nm, severity, message)
VALUES (?, ?, ?, ?, ?, ?)
```

세션 행은 `active_session` 또는 `session_history`에 넣는다. 이력에만 `source` 컬럼이 있다. 테이블 이름은 이 둘만 코드에 있다.

```sql
INSERT INTO active_session (
    agent_alias, agent_collect_tm, sid, serial_number, status, db_user, os_user,
    program, module, machine, sql_id, sql_text, wait_event, wait_class,
    elapsed_ms, blocking_sid, cpu_used, logical_reads, physical_reads, command
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

INSERT INTO session_history (
    agent_alias, agent_collect_tm, sid, serial_number, status, db_user, os_user,
    program, module, machine, sql_id, sql_text, wait_event, wait_class,
    elapsed_ms, blocking_sid, cpu_used, logical_reads, physical_reads, command, source
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

처음 기동할 때 `o_performance`가 비어 있는지 이 문으로 확인한다.

```sql
SELECT COUNT(*) AS c FROM o_performance
```

### 5.5 조회

```sql
SELECT * FROM o_performance
 WHERE agent_alias=?
 ORDER BY agent_collect_tm DESC
 LIMIT 1

SELECT p.*
  FROM o_performance p
  JOIN (
        SELECT agent_alias, MAX(agent_collect_tm) AS tm
          FROM o_performance
         GROUP BY agent_alias
       ) t ON t.agent_alias = p.agent_alias AND t.tm = p.agent_collect_tm

SELECT * FROM o_performance
 WHERE agent_alias=? AND agent_collect_tm>=? AND agent_collect_tm<=?
 ORDER BY agent_collect_tm

SELECT MAX(agent_collect_tm) AS tm
  FROM active_session
 WHERE agent_alias=?

SELECT * FROM active_session
 WHERE agent_alias=? AND agent_collect_tm=?
 ORDER BY CASE status WHEN 'ACTIVE' THEN 0 ELSE 1 END, elapsed_ms DESC

SELECT agent_collect_tm AS collect_tm,
       SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) AS active_sessions,
       COUNT(*) AS connected_sessions
  FROM active_session
 WHERE agent_alias=?
 GROUP BY agent_collect_tm
 ORDER BY agent_collect_tm DESC
 LIMIT ?

SELECT * FROM session_history
 WHERE agent_alias=? AND agent_collect_tm>=? AND agent_collect_tm<=?
 ORDER BY agent_collect_tm DESC, elapsed_ms DESC
 LIMIT ?
```

`sql_id`가 있으면 Session History 조건에 `AND sql_id=?`를 붙인다.

```sql
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

SELECT * FROM sql_text WHERE agent_alias=? AND sql_id=?

SELECT COALESCE(SUM(executions), 0) AS executions,
       COALESCE(SUM(elapsed_ms), 0) AS elapsed_ms,
       COALESCE(SUM(cpu_ms), 0) AS cpu_ms,
       COALESCE(SUM(buffer_gets), 0) AS buffer_gets,
       COALESCE(SUM(disk_reads), 0) AS disk_reads,
       COALESCE(SUM(rows_processed), 0) AS rows_processed
  FROM sql_stat
 WHERE agent_alias=? AND sql_id=?

SELECT agent_collect_tm, executions, elapsed_ms, cpu_ms, buffer_gets, disk_reads, rows_processed
  FROM sql_stat
 WHERE agent_alias=? AND sql_id=?
 ORDER BY agent_collect_tm DESC
 LIMIT 40

SELECT agent_collect_tm, sid, serial_number, db_user, program, machine, status,
       wait_class, wait_event, elapsed_ms, blocking_sid
  FROM session_history
 WHERE agent_alias=? AND sql_id=?
 ORDER BY agent_collect_tm DESC, elapsed_ms DESC
 LIMIT 40

SELECT * FROM event_log WHERE agent_alias=? ORDER BY occurred_at DESC LIMIT ?

SELECT * FROM event_log ORDER BY occurred_at DESC LIMIT ?

SELECT agent_url FROM agent_heartbeat WHERE agent_alias=?

SELECT * FROM agent_heartbeat
```

### 5.6 보관

정책과 건수를 읽은 뒤, 사용 중인 종류만 기준 시각보다 오래된 행을 지운다. 테이블과 시각 컬럼은 아래 여섯 가지다.

| 종류 | DELETE 대상 | 시각 컬럼 |
|---|---|---|
| 성능 | `o_performance` | `agent_collect_tm` |
| Active Session | `active_session` | `agent_collect_tm` |
| Session History | `session_history` | `agent_collect_tm` |
| SQL 통계 | `sql_stat` | `agent_collect_tm` |
| SQL Text | `sql_text` | `last_seen` |
| 이벤트 | `event_log` | `occurred_at` |

```sql
SELECT * FROM retention_policy ORDER BY data_kind

SELECT COUNT(*) AS c FROM o_performance

UPDATE retention_policy SET keep_days=?, enabled=? WHERE data_kind=?

SELECT * FROM retention_policy

DELETE FROM o_performance WHERE agent_collect_tm < ?

UPDATE retention_policy
   SET last_purge_at=?, last_deleted=?
 WHERE data_kind=?

INSERT INTO purge_log (ran_at, data_kind, keep_days, deleted_rows)
VALUES (?, ?, ?, ?)

SELECT * FROM purge_log ORDER BY id DESC LIMIT ?
```

`DELETE`의 테이블과 컬럼만 위 표의 다른 종류로 바뀐다. 요청 문자열로 테이블 이름을 만들지 않는다.

## 6. 시뮬레이터에 넣는 예시 문장

`mode`가 `live`가 아니면 대상 DB에 접속하지 않는다. 아래 문장은 수집 결과의 `sql_text`로만 저장된다.

Oracle:

```sql
SELECT o.order_id, o.status, c.name
  FROM orders o
  JOIN customers c ON c.id=o.customer_id
 WHERE o.created_at > SYSDATE-1

UPDATE orders SET status='PAID' WHERE order_id=:1

SELECT /*+ FULL(t) */ * FROM audit_log t WHERE event_dt > SYSDATE-1/24

INSERT INTO payment_hist SELECT * FROM payment_stage WHERE batch_id=:1

SELECT sid, event, seconds_in_wait FROM v$session WHERE status='ACTIVE'
```

Tibero:

```sql
SELECT emp_no, dept_cd, salary FROM erp.employee WHERE dept_cd=:1

UPDATE erp.slip SET close_yn='Y' WHERE slip_dt=:1 AND dept_cd=:2

SELECT item_cd, SUM(qty) FROM erp.stock GROUP BY item_cd

DELETE FROM erp.if_queue WHERE created_at < SYSDATE-7
```

MariaDB:

```sql
SELECT id, user_id, amount FROM payments WHERE status='PENDING' ORDER BY id LIMIT 50

UPDATE sessions SET last_seen=NOW() WHERE token=?

SELECT COUNT(*) FROM click_log WHERE created_at > NOW() - INTERVAL 5 MINUTE

INSERT INTO audit (user_id, action, created_at) VALUES (?, ?, NOW())
```

PostgreSQL:

```sql
SELECT day, SUM(revenue) FROM fact_sales WHERE day >= CURRENT_DATE - 30 GROUP BY day

SELECT customer_id, COUNT(*)
  FROM events
 WHERE ts > now() - interval '15 minutes'
 GROUP BY 1
 ORDER BY 2 DESC
 LIMIT 20

UPDATE warehouse.job SET status='RUNNING', started_at=now() WHERE id=$1

SELECT pid, state, query FROM pg_stat_activity WHERE state='active'
```
