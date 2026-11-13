# 경로 A. 증분과 컷오버

전제: [S-6](02-standalone-initial.md#s-6-동기화-확인)에서 복제가 따라가고 있다. 증분은 복제가 계속 적용하는 구간이다. 이 장의 작업은 전환 시점에 한다.

샘플은 전환 직전 원본과 대상의 `orders`가 3행이고, GTID가 `0-1-48255`까지 진행된 상태다.

## I-1. 지연을 감시한다

목적: 전환 전에 복제가 멈추거나 벌어지지 않았는지 확인한다.

```bash
./08-watch-replica.sh
```

기본값은 5초 간격 12회다. `WATCH_COUNT`와 `WATCH_INTERVAL`로 바꿀 수 있다.

샘플 출력:

```text
-------- sample 12/12 --------
Slave_IO_Running: Yes
Slave_SQL_Running: Yes
Seconds_Behind_Master: 0
Last_IO_Error:
Last_SQL_Error:
Gtid_IO_Pos: 0-1-48255
```

통과 기준: 마지막 샘플에서 IO와 SQL이 `Yes`이고 지연이 `0`이며 SQL 오류가 비어 있다. 지연이 줄지 않으면 컷오버로 가지 않는다.

## I-2. 애플리케이션 쓰기를 멈춘다

목적: 복제가 따라잡은 뒤에 새 트랜잭션이 생기지 않게 한다.

애플리케이션 연결 풀을 먼저 멈춘다. 이미 시작된 트랜잭션은 `read_only` 이후에도 커밋될 수 있으므로, 프로세스 목록이 비워진 뒤에 좌표를 비교한다.

```bash
./09-freeze-source.sh
```

스크립트는 원본에 `read_only`와 `super_read_only`를 켜고, `Sleep`과 `system user`를 제외한 작업이 남으면 종료 코드 1로 끝난다. `SOURCE_NODES`가 비어 있으면 `SOURCE_HOST` 한 대만 적용한다.

샘플 출력:

```text
======== freeze 10.0.0.11 ========
원본 쓰기를 멈췄습니다.
```

남은 세션이 있는 샘플:

```text
id    user   db     command  time  state   info
8421  app    appdb  Query    2     Sending SELECT SLEEP(30)
10.0.0.11 에 사용자 작업이 1건 남아 있습니다.
컷오버를 진행하지 마세요.
```

통과 기준: `원본 쓰기를 멈췄습니다.` 가 출력된다. 세션이 남으면 애플리케이션을 멈추고 I-2를 다시 실행한다.

## I-3. 좌표를 대조한다

목적: 원본이 멈춘 위치까지 대상이 적용했는지 확인한다.

원본:

```bash
mariadb --defaults-extra-file=./source.cnf -e "SHOW MASTER STATUS; SELECT @@gtid_current_pos;"
```

대상:

```bash
./08-watch-replica.sh
```

샘플:

```text
File                Position  Binlog_Do_DB  Binlog_Ignore_DB
mysql-bin.000042    2401
@@gtid_current_pos
0-1-48255
```

대상 `Gtid_IO_Pos`가 `0-1-48255`이고 `Seconds_Behind_Master`가 `0`이면 같다.

통과 기준: 원본 GTID와 대상 `Gtid_IO_Pos`가 같다. 파일과 포지션 복제라면 대상 `Master_Log_File`과 `Exec_Master_Log_Pos`가 원본 `SHOW MASTER STATUS`와 같다.

## I-4. 대상을 승격한다

목적: 복제를 멈추고 대상만 쓰기 가능하게 만든다.

`10-promote-target.sh`는 I-3 조건을 스크립트 안에서 다시 확인한다. 지연이 0이 아니거나 SQL 오류가 있으면 멈추지 않는다.

```bash
./10-promote-target.sh
```

샘플 출력:

```text
Slave_IO_Running=Yes
Slave_SQL_Running=Yes
Seconds_Behind_Master=0
Last_SQL_Error=
T1(대상 cnf 호스트)의 복제를 멈췄습니다.
대상을 열었습니다.
```

통과 기준: 대상 `read_only`와 `super_read_only`가 `OFF`다. 원본은 I-2 상태 그대로 둔다.

## I-5. 애플리케이션을 전환하고 샘플 행을 확인한다

목적: 쓰기가 대상에서 수행되는지 확인한다.

애플리케이션 접속을 `10.0.0.21`로 바꾼 뒤 대상에서 샘플 조회를 한다.

```bash
mariadb --defaults-extra-file=./target.cnf -e "SELECT id, customer_id, status FROM appdb.orders ORDER BY id;"
./12-verify.sh
```

샘플 출력:

```text
id  customer_id  status
1   100          paid
2   101          new
3   102          paid
orders source=3 target=3
```

통과 기준: 3행이 보이고 검증 스크립트가 행 수 일치를 출력한다. 원본은 확인이 끝날 때까지 읽기 전용으로 둔다.

## I-6. 되돌리기

목적: 전환 직후 문제를 확인했을 때 접속을 원본으로 돌린다.

애플리케이션을 다시 멈춘 뒤:

```bash
./16-rollback-open-source.sh
```

스크립트는 대상을 읽기 전용으로 두고 원본의 `read_only`를 푼다. 복제는 멈춘 채로 둔다. 대상이 원본과 따로 쓰기를 받지 않게 하기 위해서다.

샘플 출력:

```text
대상 10.0.0.21 를 읽기 전용으로 두었습니다.
======== open source 10.0.0.11 ========
Variable_name  Value
read_only      OFF
원본 쓰기를 열었습니다.
```

통과 기준: 애플리케이션이 원본에서 id `3`까지 읽고, 대상은 읽기 전용이다.

좌표 없는 덤프에 binlog를 이어 붙이는 작업은 하지 않는다. 워터마크 증분은 `updated_at`이 있고 물리 삭제가 없는 테이블에 한정한다. 샘플이라면 이전 추출 시각 이상을 다시 읽어 기본 키로 갱신한다.

```sql
SELECT * FROM appdb.orders
 WHERE updated_at >= '2026-11-13 09:00:00'
   AND updated_at <  '2026-11-13 10:00:00';
```

이 조회는 복제 대신 쓸 수 있는 예이다. 삭제된 행은 반영되지 않는다.
