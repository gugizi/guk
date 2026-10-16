# SpaceMon 수집서버 / DB 에이전트

Oracle, Tibero, MariaDB, PostgreSQL을 같은 화면에서 보는 모니터링 구성입니다.

- **에이전트**는 DB 서버에 두고 Active Session, Session History, 수행 SQL Text를 수집해 수집서버로 보냅니다.
- **수집서버**는 DB 성능 정보와 프로그램 환경 설정을 저장하고, 화면에서 조회합니다.
- 성능, 세션, SQL, 이벤트는 **데이터 종류별 보관일수**가 지나면 삭제됩니다.

## 실행

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m collector
```

다른 터미널에서 에이전트를 실행합니다.

```bash
.venv/bin/python -m agent
```

브라우저에서 `http://127.0.0.1:8080/` 을 엽니다. 초기 계정은 `admin` / `spacemon` 입니다.

## 설정

| 파일 | 역할 |
| --- | --- |
| `config/default.properties` | 수집서버 제목, 포트, 임계치, 기본 보관일수, 에이전트 토큰 |
| `config/agent.json` | 수집 대상, 접속 정보, `simulate` 또는 `live` |

에이전트 모드:

- `simulate`: DB에 접속하지 않고 동일한 페이로드 형식으로 샘플을 보냅니다. Oracle, Tibero 데모에 사용합니다.
- `live`: DB 서버 로컬에서 실제 세션과 SQL을 읽습니다.
  - PostgreSQL: `psycopg`
  - MariaDB: `pymysql`, 가능하면 `performance_schema`
  - Oracle: `oracledb`, `V$SESSION` / `V$SQL` / `V$SYSSTAT`
  - Tibero: Oracle 호환 `V$` 뷰. `TIBERO_JDBC_JAR`와 `jaydebeapi`가 필요합니다.

접속 비밀번호는 에이전트 설정에만 두고, 수집서버 화면에는 다시 표시하지 않습니다.

## 보관 주기

화면의 **보관 주기**에서 종류별 일수를 바꿉니다. 수집서버는 설정 간격마다, 그리고 `지금 삭제 실행` 때 기준 시각보다 오래된 행을 지웁니다.

| 종류 | 저장 내용 |
| --- | --- |
| performance | DB 성능 샘플 |
| active_session | 수집 시점의 세션 스냅샷 |
| session_history | Active Session 샘플과 완료 SQL 이력 |
| sql_stat / sql_text | 수행 통계와 SQL 문 |
| event | 임계치 이벤트 |

보관일수 `0`은 현재 시각보다 이전 데이터를 삭제합니다. 사용 해제한 종류는 지우지 않습니다.

## 테스트

```bash
.venv/bin/python -m pytest tests -q
```
