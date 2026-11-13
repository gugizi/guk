# OKEDBMON API 명세서

- 버전: 1.0.0.0
- 기준일: 2026-11-14
- 기본 주소: `http://127.0.0.1:8080`
- 화면 API: `Authorization: Bearer <token>`. 없거나 만료면 401
- 수집 API: `X-Agent-Token`. 토큰이 다르면 401
- 시각 문자열: `YYYY-MM-DD HH:MM:SS`

## 1. 로그인

### POST /api/login

```json
{ "username": "admin", "password": "okedbmon" }
```

성공 `{ "token": "...", "user": { "user_id", "display_name", "role" } }`. 토큰은 12시간이다.

### GET /api/me

현재 사용자.

### GET /api/health

인증 없음. `{ "status": "ok", "time", "title", "version", "display" }`. `display`는 `OKEDBMON V1.0.0.0`이다.

## 2. 화면 조회

### GET /api/dashboard

인스턴스 목록, 최신 성능, 최근 이벤트, 제품명, 버전.

### GET /api/instances

등록 인스턴스.

### POST /api/instances

### PUT /api/instances/{alias}

### DELETE /api/instances/{alias}

본문 예:

```json
{
  "agent_alias": "ORA_PROD",
  "product": "ORACLE",
  "host_nm": "db-ora-01",
  "port": 1521,
  "db_name": "ORCL",
  "username": "monitor",
  "group_nm": "운영",
  "collect_interval_sec": 5,
  "enabled": true,
  "description": ""
}
```

### GET /api/settings

### PUT /api/settings

`{ "values": { "support.title": "OKEDBMON" } }`

### GET /api/performance?alias=&start=&end=

`start`/`end`가 없으면 최근 1시간. `{ "series": [ o_performance 행 ] }`.

### GET /api/sessions/times?alias=

수집 시각 목록. 최신이 앞이다. 최대 120개.

### GET /api/sessions/series?alias=

수집단위별 Active Session 수. 오래된 시각이 앞이다.

```json
{ "points": [{ "collect_tm": "2026-11-14 00:00:45", "active_sessions": 5, "connected_sessions": 8 }] }
```

### GET /api/sessions/active?alias=&at=

`at`가 없으면 마지막 수집. 있으면 그 시각의 스냅샷.

```json
{ "collect_tm": "2026-11-14 00:00:45", "sessions": [], "locks": [] }
```

`locks`는 `blocking_sid`로 만든 트리. 노드 필드: `sid`, `db_user`, `sql_id`, `sql_text`, `wait_event`, `elapsed_ms`, `children`.

### GET /api/sessions/history?alias=&start=&end=&sql_id=

기본 구간은 최근 1시간. `{ "sessions": [] }`. 최대 200행.

### GET /api/sql?alias=&q=&limit=

SQL 목록. `q`는 SQL 전문 또는 SQL ID. 기본 `limit` 80. 수행, Elapsed, CPU, Buffer, Disk, Rows는 `sql_stat` 합계다.

### GET /api/sql/detail?alias=&sql_id=

없으면 404.

```json
{
  "sql": { "sql_id": "", "sql_text": "", "command_type": "", "first_seen": "", "last_seen": "" },
  "stats": { "executions": 0, "elapsed_ms": 0, "cpu_ms": 0, "buffer_gets": 0, "disk_reads": 0, "rows_processed": 0 },
  "series": [],
  "trace": []
}
```

`series`는 최근 40개 수집 통계를 시간순으로, `trace`는 그 SQL의 세션 이력 최근 40행이다.

### GET /api/events?alias=

최근 이벤트. `alias`가 없으면 전체. 최대 40행.

### GET /api/report?alias=&start=&end=

기본 구간은 최근 6시간. 요약과 `top_sql` 10건.

### GET /api/retention

정책, 현재 건수, 삭제 이력.

### PUT /api/retention

```json
{ "policies": [{ "data_kind": "active_session", "keep_days": 2, "enabled": true }] }
```

`keep_days`는 0 이상 3650 이하.

### POST /api/retention/run

보관 주기가 지난 행을 지금 삭제한다.

## 3. 수집 수신

### POST /api/ingest

헤더 `X-Agent-Token`. 본문:

```json
{
  "agent_alias": "ORA_PROD",
  "product": "ORACLE",
  "collect_tm": "2026-11-14 00:00:45",
  "version": "1.0.0.0",
  "status": "ONLINE",
  "message": "",
  "performance": { "cpu_usage": 40, "active_sessions": 5 },
  "active_sessions": [],
  "session_history": [],
  "sql_texts": [{ "sql_id": "abc", "sql_text": "SELECT 1 FROM dual", "command_type": "SELECT" }],
  "sql_stats": [{ "sql_id": "abc", "executions": 4, "elapsed_ms": 80 }]
}
```

성공 `{ "accepted": true, "agent_alias", "collect_tm" }`.

수신은 `agent_heartbeat`와 성능·세션·SQL 테이블에 저장한다. 좌측 목록에 나오게 하려면 `mon_instance`에 같은 `agent_alias`가 있어야 한다. 성능 임계치를 넘으면 `event_log`에 넣는다.

## 4. 화면

`GET /`는 `web/index.html`이다. `/static`은 `web/`이다.
