# OKEDBMON 수집서버 / DB 에이전트

Oracle, Tibero, MariaDB, PostgreSQL을 같은 화면에서 보는 모니터링 구성입니다. 제품 버전은 `major.minor.patch.build` 네 자리이고, 화면에는 `OKEDBMON V1.0.0.0`처럼 제품명 뒤에 `V`를 붙여 표시합니다. 초기 버전은 `1.0.0.0`입니다.

- **에이전트**는 DB 서버에 두고 Active Session, Session History, 수행 SQL Text를 수집해 수집서버로 보냅니다.
- **수집서버**는 DB 성능 정보와 프로그램 환경 설정을 저장하고, 화면에서 조회합니다.
- 성능, 세션, SQL, 이벤트는 **데이터 종류별 보관일수**가 지나면 삭제됩니다.

## 실행

Python 3.10 이상이 필요합니다. 프로그램은 모두 이 `OKEDBMON` 폴더 안에 있습니다. 수집서버를 먼저 띄웁니다. 에이전트는 모니터링할 DB 서버마다 하나씩 띄우고, 그 서버의 인스턴스만 수집합니다.

| OS | 수집서버 | DB 서버 에이전트 | 한 PC에서 4종 데모 |
| --- | --- | --- | --- |
| Windows | `run_collector.bat` | `run_agent.bat` | `run_demo_agent.bat` |
| Linux / Unix | `./run_collector.sh` | `./run_agent.sh` | `./run_demo_agent.sh` |

처음 실행할 때 `.venv`를 만들고 패키지를 설치합니다. 수집서버를 띄운 PC의 브라우저에서 `http://127.0.0.1:8080/` 을 엽니다. 다른 PC에서는 `http://<수집서버 IP>:8080/` 으로 접속하며, 방화벽에서 8080 포트를 열어야 합니다. 초기 계정은 `admin` / `okedbmon` 입니다.

## 화면 구성

- 상단: 조회 메뉴 (통합 관제, 실시간, 세션 이력, SQL Text, 성능 추이, 점검 요약, 환경 설정, 보관 주기)
- 왼쪽: 모니터링 대상 목록. 그룹별로 묶고 상태, CPU, Active Session, Lock을 보여줍니다. 검색으로 거를 수 있습니다.
- 가운데: 선택한 대상과 메뉴에 해당하는 조회 결과

## 설정

| 파일 | 역할 |
| --- | --- |
| `config/default.properties` | 수집서버 제목, 포트, 임계치, 기본 보관일수, 에이전트 토큰 |
| `config/agent.json` | 이 DB 서버의 인스턴스 하나, 접속 정보, `simulate` 또는 `live` |
| `config/demo-agents.json` | 한 PC 데모 전용. 대상마다 독립된 수집 스레드를 둡니다 |

`config/agent.json`에 대상을 여러 개 넣으면 에이전트는 시작하지 않습니다. 느린 인스턴스가 다른 인스턴스 수집을 밀지 않도록, 프로세스 하나는 인스턴스 하나만 담당합니다. 수집 주기는 그 대상의 `interval_sec`가 있으면 그 값이고, 없으면 설정의 `interval_sec`입니다.

에이전트 모드:

- `simulate`: DB에 접속하지 않고 동일한 페이로드 형식으로 샘플을 보냅니다. Oracle, Tibero 데모에 사용합니다.
- `live`: DB 서버 로컬에서 실제 세션과 SQL을 읽습니다.
  - PostgreSQL: `psycopg`
  - MariaDB: `pymysql`, 가능하면 `performance_schema`
  - Oracle: `oracledb`, `V$SESSION` / `V$SQL` / `V$SYSSTAT`
  - Tibero: Oracle 호환 `V$` 뷰. `TIBERO_JDBC_JAR`와 `jaydebeapi`가 필요합니다.

접속 비밀번호는 에이전트 설정에만 두고, 수집서버 화면에는 다시 표시하지 않습니다.

## 저장 방식

수집서버는 성능 데이터와 환경 설정을 `data/okedbmon.sqlite`에 둡니다. Active Session, 세션 이력, SQL Text는 각 에이전트의 `data/agents/<별칭>.sqlite`에 둡니다. 수집서버는 성능 숫자만 받고, 세션과 SQL 화면은 그 에이전트에 조회합니다. 에이전트가 알려 주는 주소는 `advertise_host`와 `listen_port`입니다. DB 서버에서는 `advertise_host`를 수집서버가 접속할 수 있는 IP로 바꿉니다.

| 위치 | 테이블 | 내용 |
| --- | --- | --- |
| 수집서버 | `env_setting`, `mon_instance`, `app_user` | 제품 설정, 대상 등록, 로그인 |
| 수집서버 | `o_performance`, `event_log` | CPU, 세션 수, Lock 건수, 임계치 이벤트 |
| 에이전트 | `active_session` | 그 시각의 세션 스냅샷 |
| 에이전트 | `session_history` | Active Session 이력 |
| 에이전트 | `sql_text`, `sql_stat` | SQL 문과 수집 구간 수행 통계 |

## 보관 주기

화면의 **보관 주기**는 두 부분입니다.

- 수집서버: 성능과 이벤트의 보관일수
- 선택한 에이전트: 세션과 SQL의 저장 주기(초), 삭제 주기(초), 종류별 보관일수

저장 주기는 세션과 SQL을 에이전트 파일에 기록하는 간격입니다. 삭제 주기는 보관일수가 지난 행을 지우는 작업 간격입니다. 보관일수 `0`은 현재 시각보다 이전 데이터를 삭제합니다. 사용 해제한 종류는 지우지 않습니다.

## 테스트

```bash
cd OKEDBMON
.venv/bin/python -m pytest tests -q
```
