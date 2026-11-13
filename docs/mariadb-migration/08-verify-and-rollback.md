# 검증과 롤백

최초 적재 직후, 증분을 따라잡은 뒤, 컷오버 직후에 같은 확인을 한다. 샘플 테이블은 `appdb.orders`다.

## V-1. 행 수

목적: 추정치가 아닌 건수로 원본과 대상을 비교한다.

```bash
./12-verify.sh
```

`EXACT_COUNT_TABLES=orders`가 기본값이다. 테이블을 더하려면 쉼표로 적는다. `RUN_CHECKSUM=1`이면 그 테이블에 `CHECKSUM TABLE`도 실행한다. 행이 많은 테이블은 시간이 걸린다.

샘플 출력:

```text
orders source=3 target=3
======== replica ========
Slave_IO_Running: Yes
Slave_SQL_Running: Yes
Seconds_Behind_Master: 0
Last_SQL_Error:
비교한 테이블의 행 수가 같습니다.
```

컷오버 이후에는 IO가 `No`일 수 있다. 그때의 통과 기준은 행 수다. 행 수가 다르면 스크립트가 종료 코드 1로 끝난다.

`SOURCE_NODES` 또는 `TARGET_NODES`가 있으면 노드별 Galera 상태를 이어서 출력한다.

```text
wsrep_cluster_size          3
wsrep_local_state_comment   Synced
wsrep_ready                 ON
wsrep_last_committed        1204
wsrep_local_recv_queue      0
wsrep_local_send_queue      0
```

통과 기준: 비교 테이블의 행 수가 같다. Galera 경로에서는 같은 클러스터의 `wsrep_last_committed`가 노드 사이에서 같다.

## V-2. 샘플 업무 조회

목적: 절차서의 3행이 대상에서 보이는지 확인한다.

```bash
mariadb --defaults-extra-file=./target.cnf -e "
SELECT id, customer_id, status, updated_at
FROM appdb.orders
ORDER BY id;
CALL appdb.order_count();
"
```

샘플 출력:

```text
id  customer_id  status  updated_at
1   100         paid    2026-11-13 09:00:00.000000
2   101         new     2026-11-13 09:05:00.000000
3   102         paid    2026-11-13 09:40:00.000000
order_count
3
```

id `3`은 덤프 이후 증분이다. 최초 적재 직후 복제를 시작하기 전에는 2행만 있는 것이 맞다.

통과 기준: 복제가 따라잡은 뒤에는 3행과 프로시저 결과 `3`이 나온다.

## V-3. 객체 수

목적: 테이블 외 루틴, 트리거, 이벤트가 빠졌는지 본다.

```bash
mariadb --defaults-extra-file=./source.cnf -e "
SELECT
  (SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema='appdb') AS routines,
  (SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema='appdb') AS triggers,
  (SELECT COUNT(*) FROM information_schema.events WHERE event_schema='appdb') AS events;"
mariadb --defaults-extra-file=./target.cnf -e "
SELECT
  (SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema='appdb') AS routines,
  (SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema='appdb') AS triggers,
  (SELECT COUNT(*) FROM information_schema.events WHERE event_schema='appdb') AS events;"
```

샘플:

```text
routines  triggers  events
1         0         0
```

원본과 대상이 같아야 한다. 계정은 논리 덤프에 들어 있지 않으므로 애플리케이션 계정은 대상에 따로 만든다.

## V-4. 롤백

전환 직후 대상 애플리케이션이 정상이 아니면 [I-6](03-standalone-incremental.md#i-6-되돌리기)과 같은 스크립트를 쓴다. Galera에서는 대상 노드 전부를 읽기 전용으로 두고 원본 노드 전부를 연다.

```bash
./16-rollback-open-source.sh
```

순서:

1. 애플리케이션 접속을 끊는다.
2. 스크립트로 대상을 읽기 전용으로 두고 원본 쓰기를 연다.
3. 애플리케이션을 원본으로 붙인다.
4. 원본에서 V-2 조회가 3행인지 확인한다.

복제는 다시 켜지 않는다. 대상을 다시 맞출 때는 초기화 절차로 새 스냅샷부터 한다.

샘플 출력:

```text
대상 10.0.2.21 를 읽기 전용으로 두었습니다.
대상 10.0.2.22 를 읽기 전용으로 두었습니다.
대상 10.0.2.23 를 읽기 전용으로 두었습니다.
======== open source 10.0.1.11 ========
======== open source 10.0.1.12 ========
======== open source 10.0.1.13 ========
원본 쓰기를 열었습니다. 애플리케이션 접속을 원본으로 되돌리세요.
```

통과 기준: 원본 모든 노드의 `read_only`가 `OFF`이고 대상은 `ON`이다.
