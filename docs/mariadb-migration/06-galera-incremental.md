# 경로 B. Galera 증분과 컷오버

전제: [G-8](05-galera-initial.md#g-8-합류-확인)이 끝났고 T1만 S1을 복제한다. 증분 이벤트는 T1이 적용한 뒤 Galera가 T2, T3로 보낸다. T2나 T3에서 `07-start-replica.sh`를 실행하지 않는다.

클러스터 안에서 잠시 빠졌던 노드를 gcache로 따라잡는 IST(4568)는 이 증분이 아니다. gcache에 구간이 없으면 그 노드는 SST(4444)로 맞춘다.

샘플은 전환 직전 `orders` 3행, 원본 GTID `0-1-48255`다.

## GI-1. 복제 노드가 하나인지 확인

목적: 같은 이벤트가 두 경로로 들어가지 않게 한다.

T1, T2, T3에서 각각 확인한다.

```bash
mariadb --defaults-extra-file=./target.cnf --host=10.0.2.21 -E -e "SHOW SLAVE STATUS" \
  | sed -n 's/^[[:space:]]*Slave_IO_Running: //p'
mariadb --defaults-extra-file=./target.cnf --host=10.0.2.22 -E -e "SHOW SLAVE STATUS" \
  | sed -n 's/^[[:space:]]*Slave_IO_Running: //p'
mariadb --defaults-extra-file=./target.cnf --host=10.0.2.23 -E -e "SHOW SLAVE STATUS" \
  | sed -n 's/^[[:space:]]*Slave_IO_Running: //p'
```

샘플 출력:

```text
Yes

```

T1만 `Yes`다. T2와 T3는 빈 출력이다. T2나 T3가 `Yes`면 그 노드에서 `STOP SLAVE; RESET SLAVE ALL;`을 실행하고, 중복 적용이 있었는지 [V-1](08-verify-and-rollback.md)의 행 수와 오류를 확인한다.

통과 기준: 복제 IO 스레드는 T1 하나다.

## GI-2. 지연과 Galera 큐를 본다

목적: 비동기 지연과 클러스터 내부 적용 지연이 같이 0인지 본다.

```bash
./08-watch-replica.sh
./12-verify.sh
```

T1 샘플:

```text
Slave_IO_Running: Yes
Slave_SQL_Running: Yes
Seconds_Behind_Master: 0
Gtid_IO_Pos: 0-1-48255
```

대상 노드 샘플:

```text
wsrep_local_recv_queue      0
wsrep_local_send_queue      0
wsrep_flow_control_paused   0.000000
wsrep_last_committed        1204
```

`wsrep_flow_control_paused`가 0에 가깝고 세 노드의 `wsrep_last_committed`가 같으면 된다. 큐가 남아 있으면 컷오버하지 않는다.

통과 기준: T1 지연 0, 대상 세 노드의 송수신 큐 0, `last_committed` 일치.

## GI-3. 원본 모든 노드의 쓰기를 멈춘다

목적: 클러스터 전체에서 새 트랜잭션을 멈춘다. 노드 하나의 `FLUSH TABLES WITH READ LOCK`은 다른 노드의 쓰기를 멈추지 않는다. `read_only`도 그 노드의 클라이언트 쓰기만 막는다. Galera로 들어온 적용은 계속된다. 그래서 세 노드를 모두 멈춘다.

애플리케이션을 먼저 멈춘 뒤:

```bash
./09-freeze-source.sh
```

`SOURCE_NODES`의 각 호스트에 `read_only`와 `super_read_only`를 켠다. 한 노드라도 사용자 세션이 남거나 접속이 실패하면 종료 코드 1이다. 그 상태로는 컷오버하지 않고, 실패한 노드를 해결한 뒤 GI-3을 다시 실행한다.

샘플 출력:

```text
======== freeze 10.0.1.11 ========
======== freeze 10.0.1.12 ========
======== freeze 10.0.1.13 ========
원본 쓰기를 멈췄습니다.
```

통과 기준: 세 노드 모두 읽기 전용이고, 사용자 작업 행이 없다.

## GI-4. 원본 적용 지점과 T1 복제 지점을 맞춘다

목적: 원본 클러스터가 같은 seqno에서 멈췄고 T1이 그 binlog를 모두 적용했는지 확인한다.

`10-promote-target.sh`가 승격 전에 원본 세 노드의 `wsrep_last_committed`와 큐를 다시 읽는다. 미리 보려면:

```bash
mariadb --defaults-extra-file=./source.cnf --host=10.0.1.11 -e "SHOW STATUS LIKE 'wsrep_last_committed'; SELECT @@gtid_current_pos;"
mariadb --defaults-extra-file=./source.cnf --host=10.0.1.12 -e "SHOW STATUS LIKE 'wsrep_last_committed';"
mariadb --defaults-extra-file=./source.cnf --host=10.0.1.13 -e "SHOW STATUS LIKE 'wsrep_last_committed';"
```

샘플:

```text
Variable_name          Value
wsrep_last_committed   90255
@@gtid_current_pos
0-1-48255
```

S2와 S3의 `90255`가 S1과 같고, T1 `Gtid_IO_Pos`가 `0-1-48255`이며 지연이 0이면 맞다.

통과 기준: 원본 세 노드의 `wsrep_last_committed`가 같고 큐가 0이다. T1 지연이 0이다.

## GI-5. 대상을 승격한다

목적: T1 복제만 멈추고 대상 세 노드를 애플리케이션에 연다.

```bash
./10-promote-target.sh
```

큐가 남아 있거나 `last_committed`가 다르거나 T1 지연이 0이 아니면 스크립트는 `STOP SLAVE`를 실행하지 않는다.

샘플 출력:

```text
10.0.1.11 last_committed=90255 recv=0 send=0
10.0.1.12 last_committed=90255 recv=0 send=0
10.0.1.13 last_committed=90255 recv=0 send=0
Slave_IO_Running=Yes
Slave_SQL_Running=Yes
Seconds_Behind_Master=0
======== open 10.0.2.21 ========
======== open 10.0.2.22 ========
======== open 10.0.2.23 ========
대상을 열었습니다.
```

애플리케이션 접속을 대상 클러스터로 바꾼다. 세 노드는 같은 데이터이므로 쓰기는 어느 대상 노드에서 받아도 된다. 원본은 확인이 끝날 때까지 읽기 전용으로 둔다.

통과 기준: T1 `Slave_IO_Running`이 `No`이고 대상 세 노드의 `read_only`가 `OFF`다. [검증](08-verify-and-rollback.md)에서 `orders` 3행을 확인한다.

## GI-6. S1이 빠졌을 때 복제 원본을 바꾼다

목적: 컷오버 전에 S1을 더 이상 쓸 수 없을 때 T1이 S2를 따라가게 한다.

S2에서 `@@gtid_current_pos`를 읽고, T1의 `gtid_slave_pos`가 그 안에 포함되는 것을 확인한 뒤에만 바꾼다. Galera 노드 사이의 GTID는 어긋날 수 있어서 값이 포함되는지 먼저 본다.

```sql
-- S2
SELECT @@gtid_current_pos;
-- 샘플: 0-1-48255

-- T1
STOP SLAVE;
CHANGE MASTER TO
  MASTER_HOST='10.0.1.12',
  MASTER_PORT=3306,
  MASTER_USER='repl',
  MASTER_PASSWORD='change-me',
  MASTER_USE_GTID=slave_pos;
START SLAVE;
```

`07-start-replica.sh`를 그대로 쓰려면 `SOURCE_HOST=10.0.1.12`로 바꾼 뒤, IO 스레드가 이미 떠 있으면 먼저 `STOP SLAVE`를 실행한다. 스크립트는 IO가 `Yes`면 시작을 거절한다.

통과 기준: T1이 S2에 연결되고 지연이 다시 0이 된다. 포함 관계가 확인되지 않으면 GI-6을 진행하지 않고 물리 백업 경로로 되돌린다.
