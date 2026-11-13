# OKEDBMON 변경 이력

형식은 주.부.수정.빌드(`A.B.C.D`)이다. 화면 표시는 `OKEDBMON V` 뒤에 이 번호를 붙인다.

## 1.0.0.0

기준일: 2026-11-14

- Oracle, Tibero, MariaDB, PostgreSQL을 한 화면에서 조회한다.
- 수집서버가 성능, Active Session, Session History, SQL Text, SQL 통계, 이벤트, 환경 설정을 `data/okedbmon.sqlite`에 저장한다.
- DB 서버의 에이전트 프로세스는 인스턴스 하나만 수집해 수집서버로 보낸다.
- 화면은 왼쪽 인스턴스 목록, 상단 조회 메뉴, 가운데 결과다. 메뉴는 실시간, 성능 분석, 환경설정이다.
- 시점별 Active Session은 수집 1회당 막대 하나이고, 막대를 고르면 그 시각의 세션 상세가 나온다.
- SQL 수행시간 분포는 SQL 하나당 점 하나다. 점을 고르면 SQL Trace가 열리고 선택한 SQL이 주황 점으로 표시된다.
- 보관 주기는 성능 14일, Active Session 2일, Session History 7일, SQL 통계 14일, SQL Text 30일, 이벤트 30일이다.
- 버전 표시는 `OKEDBMON V1.0.0.0`이다.
- 초기 로그인 계정은 `admin` / `okedbmon`이다.
