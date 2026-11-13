# MariaDB 이관 작업서

이 파일만 보고 진행한다. MariaDB 10.6 이상이다. 명령은 `docs/mariadb-migration/scripts`에서 실행한다.

대상에 데이터가 있으면 초기화를 먼저 하고, 그 다음 스냅샷을 넣고, 그 좌표 이후만 복제로 따라간다. 지연이 0이면 전환한다.

## 샘플

출력 예는 아래 값을 쓴다. [`samples/appdb-seed.sql`](samples/appdb-seed.sql)은 설명용이며 운영 서버에 실행하지 않는다.

| 항목 | 단일 인스턴스 | Galera |
| --- | --- | --- |
| 원본 | `10.0.0.11` | S1 `10.0.1.11`, S2 `.12`, S3 `.13` |
| 대상 | `10.0.0.21` | T1 `10.0.2.21`, T2 `.22`, T3 `.23` |
| DB | `appdb` | `appdb` |

덤프 시점 `orders`는 2행, GTID `0-1-48231`, binlog `mysql-bin.000042` / `1578`이다. 이후 원본에 id `3`이 생기고, 복제가 따라잡은 컷오버 시점은 GTID `0-1-48255`이다.

| id | customer_id | status |
| --- | --- | --- |
| 1 | 100 | paid |
| 2 | 101 | new |
| 3 | 102 | paid (덤프 이후 증분) |

## 진행 순서

경로 A, 단일 인스턴스:

- [ ] 1. 준비
- [ ] 2. 대상에 `appdb`가 있으면 삭제
- [ ] 3. 덤프, 적재, 복제
- [ ] 4. 컷오버
- [ ] 5. 확인

경로 B, Galera:

- [ ] 1. 준비. `SOURCE_NODES`, `TARGET_NODES`를 채운다
- [ ] 2. 물리 백업으로 새 클러스터를 만들거나, 떠 있는 클러스터의 `appdb`만 삭제
- [ ] 3. T1만 복제하고 나머지는 SST
- [ ] 4. 컷오버
- [ ] 5. 확인

Galera 대상은 원본 클러스터에 조인하지 않는다. `galera_new_cluster`로 별도 클러스터를 만든다. 복제 스레드는 T1 하나만 켠다.

## 0. 설정

```bash
cd docs/mariadb-migration/scripts
cp config.sample.env config.env
cp source.cnf.sample source.cnf
cp target.cnf.sample target.cnf
cp dump.cnf.sample dump.cnf
cp backup.cnf.sample backup.cnf
chmod 600 config.env source.cnf target.cnf dump.cnf backup.cnf
```

`source.cnf`와 `target.cnf`는 관리 계정, `dump.cnf`는 덤프 계정, `backup.cnf`는 S1의 로컬 `backup` 계정이다. `mariabackup`은 `[mariabackup]` 그룹만 읽는다. 단일 인스턴스는 `SOURCE_NODES`와 `TARGET_NODES`를 비운다.

데이터를 바꾸는 스크립트는 `CONFIRM=YES`가 있어야 한다. T1 데이터 디렉터리 교체는 `CONFIRM_DATADIR=YES`도 필요하다. `NODE_ROLE=joiner`는 `config.env`에 넣지 않고 실행 앞에 붙인다.

애플리케이션 계정에는 `SUPER`를 주지 않는다. 대상은 적재 동안 `read_only=ON`, `super_read_only=OFF`라서 일반 계정은 쓰기가 막히고 관리 계정만 넣는다.

원본에는 binlog가 필요하다. 보관 기간은 덤프부터 복제 연결까지보다 길어야 한다. Galera는 모든 노드에 같은 `log_bin` 경로, `log_slave_updates=ON`, `binlog_format=ROW`, `innodb_autoinc_lock_mode=2`, `wsrep_gtid_mode=ON`을 둔다. `server_id`와 `wsrep_gtid_domain_id`는 클러스터 안에서 같고 클러스터끼리는 다르다. 노드별 `gtid_domain_id`는 서로 다르고 `wsrep_gtid_domain_id`와도 다르다. 예는 [`samples/galera-node.cnf.sample`](samples/galera-node.cnf.sample)이다.

```ini
server-id = 1
log_bin = mysql-bin
binlog_format = ROW
log_slave_updates = ON
binlog_expire_logs_seconds = 604800
```

## 1. 준비

```bash
./01-precheck.sh
./02-collect-inventory.sh
```

통과: 원본 `log_bin=ON`, `binlog_format=ROW`. 엔진이 InnoDB가 아니면 단일 경로는 `--lock-all-tables`가 필요하고, Galera는 InnoDB만 노드 전체에 복제된다. `table_rows`는 추정치라 이 단계의 실패 기준이 아니다.

```bash
# CONFIRM=YES
./03-create-users.sh
./set-target-readonly.sh
```

생성되는 계정은 `dump`@`%`, `repl`@`%`, S1 로컬 `backup`@`localhost`이다. 운영에서는 `repl` 호스트를 대상 IP로 좁힌다.

통과: 대상 `read_only=ON`, `super_read_only=OFF`.

## 2. 단일 인스턴스

### 2.1 대상에 데이터가 있으면 삭제

원본은 지우지 않는다. 보관이 필요하면 대상만 따로 떠 둔다.

```bash
mariadb-dump --defaults-extra-file=./target.cnf \
  --single-transaction --routines --triggers --events \
  --databases appdb > /backup/appdb-target-before-reset.sql
./11-reset-target-database.sh
```

통과: `SHOW DATABASES LIKE 'appdb'` 결과가 비어 있다. 이어서 새 덤프를 뜬다. 예전 `/backup/appdb-full.sql`은 재사용하지 않는다.

스키마를 유지한 채 행만 지울 때는 `SET FOREIGN_KEY_CHECKS=0` 아래 `TRUNCATE`를 쓴다. 스키마가 원본과 다를 수 있으면 `DROP DATABASE`와 전체 덤프를 쓴다.

### 2.2 덤프와 적재

```bash
./04-dump-logical.sh
./05-extract-coordinates.sh
./06-import-logical.sh
```

덤프는 `--single-transaction --master-data=2 --gtid --routines --triggers --events`로 `appdb` 전체를 받는다. 덤프 중 원본 DDL은 하지 않는다.

통과 예:

```text
SET GLOBAL gtid_slave_pos='0-1-48231';
-- CHANGE MASTER TO MASTER_LOG_FILE='mysql-bin.000042', MASTER_LOG_POS=1578;
0-1-48231
```

좌표가 없으면 증분을 붙이지 않고 덤프를 다시 뜬다. 적재 직후 대상 `orders`는 2행이다. id `3`은 아직 없다. `DEFINER` 계정이 대상에 없으면 그 객체에서 적재가 멈추므로, 계정을 만들거나 DEFINER를 바꾼 뒤 2.1부터 다시 한다.

### 2.3 복제

```bash
./07-start-replica.sh
./08-watch-replica.sh
./12-verify.sh
```

`GTID_SLAVE_POS`가 있으면 그 값으로 시작하고, 비어 있으면 적재가 넣은 `gtid_slave_pos`를 쓴다. 둘 다 없으면 시작하지 않는다. 파일과 포지션만 있을 때는 `BINLOG_FILE`과 `BINLOG_POS`를 함께 넣는다.

통과:

```text
Slave_IO_Running: Yes
Slave_SQL_Running: Yes
Seconds_Behind_Master: 0
Gtid_IO_Pos: 0-1-48255
orders source=3 target=3
```

`Duplicate entry`가 나오면 좌표가 스냅샷보다 앞이다. 복제를 멈추고 2.1부터 다시 한다.

### 2.4 컷오버

애플리케이션을 먼저 멈춘다. 이미 열린 트랜잭션은 `read_only` 이후에도 커밋될 수 있다.

```bash
./09-freeze-source.sh
./10-promote-target.sh
```

`09`는 원본에 `read_only`와 `super_read_only`를 켠다. 사용자 세션이 남아 있으면 실패하며, 그때는 전환하지 않는다. `10`은 지연이 0이고 SQL 오류가 없을 때만 복제를 멈추고 대상을 연다.

통과: 대상 `read_only=OFF`. 원본은 확인이 끝날 때까지 읽기 전용으로 둔다. 애플리케이션을 `10.0.0.21`로 바꾼다.

### 2.5 되돌리기

```bash
./16-rollback-open-source.sh
```

대상을 읽기 전용으로 두고 원본 쓰기만 연다. 복제는 다시 켜지 않는다. 다시 맞출 때는 2.1의 새 스냅샷부터 한다.

## 3. Galera

복제와 백업은 S1, 비동기 복제 시작은 T1만 한다. 같은 덤프를 노드마다 넣지 않는다. 라이브 노드에서 `wsrep_on=OFF`로 넣으면 그 노드만 데이터가 생긴다. SST는 `wsrep_sst_method=mariabackup`과 `socat`을 쓴다. 그 값을 거부하면 `mariadb-backup`을 쓴다.

### 3.1 상태 확인

`./01-precheck.sh`에서 원본 세 노드가 모두 `Synced`, `wsrep_ready=ON`, `Primary`이고 `wsrep_cluster_size=3`, `wsrep_last_committed`가 같으면 된다.

### 3.2 물리 백업으로 새 클러스터

S1에서 백업한다. `BACKUP_DIR`는 비어 있어야 한다.

```bash
./13-galera-backup.sh
```

통과 예: `xtrabackup_binlog_info`가 `mysql-bin.000042  1578  0-1-48231`이다. 세 번째 필드가 없으면 설정을 확인한 뒤 다시 뜬다. 이 GTID를 `GTID_SLAVE_POS`에 넣고 `SOURCE_HOST`는 S1로 둔다. 다른 노드의 `SHOW MASTER STATUS`로 바꾸지 않는다.

T2, T3, T1을 멈춘 뒤 T1에서만 복원한다.

```bash
./14-galera-restore.sh
galera_new_cluster
```

첫 노드는 `systemctl start`로 올리지 않는다. 통과: T1의 `wsrep_cluster_size=1`, `Synced`.

T1에서만 복제를 시작한다.

```bash
./07-start-replica.sh
./08-watch-replica.sh
```

통과: T1 지연 0, `orders` 3행. T2와 T3는 아직 멈춘 상태다.

T2, T3는 `systemctl start mariadb`로 SST를 받는다. 옛 데이터가 있는 노드가 IST로 붙지 않게 하려면 각 joiner에서만 다음을 실행한다. T1에서는 실행하지 않는다.

```bash
NODE_ROLE=joiner ./15-galera-force-sst.sh
```

통과: 대상 `wsrep_cluster_size=3`, 세 노드 `Synced`, `wsrep_last_committed`가 서로 같다. 원본 숫자와 같을 필요는 없다.

### 3.3 떠 있는 클러스터의 DB만 교체

T1에서 복제를 끊고 `appdb`만 지운다. `DROP DATABASE`는 기본 설정에서 세 노드에 복제된다.

```bash
./11-reset-target-database.sh
```

통과: 세 노드 모두 `schema_count=0`. 한 노드에 남으면 그 노드에서 `DROP DATABASE appdb`를 다시 실행한다.

이어서 S1에서 `04-dump-logical.sh`로 새 덤프를 뜨고, T1에만 `06-import-logical.sh`, `07-start-replica.sh`를 실행한다. 예전 좌표의 덤프 파일은 재사용하지 않는다. 덤프가 크면 T2, T3를 멈춘 뒤 T1만 채우고 3.2의 SST로 맞춘다.

### 3.4 컷오버

T1만 `Slave_IO_Running=Yes`인지 확인한다. T2나 T3도 Yes면 그 노드에서 `STOP SLAVE; RESET SLAVE ALL;`을 실행한다.

```bash
./08-watch-replica.sh
./09-freeze-source.sh
./10-promote-target.sh
```

원본은 세 노드 모두 읽기 전용이어야 한다. 노드 하나의 `FLUSH TABLES WITH READ LOCK`은 다른 노드의 쓰기를 멈추지 않는다. `10`은 세 노드의 송수신 큐가 0이고 `wsrep_last_committed`가 같으며 T1 지연이 0일 때만 복제를 멈추고 대상 세 노드를 연다.

S1이 빠지면 S2의 `gtid_current_pos`가 T1 위치를 포함하는지 확인한 뒤에만 `SOURCE_HOST`를 S2로 바꿔 복제를 다시 건다. 포함되지 않으면 3.2부터 다시 한다.

### 3.5 되돌리기

`./16-rollback-open-source.sh`는 대상 세 노드를 읽기 전용으로 두고 원본 세 노드의 쓰기만 연다.

## 4. 확인

복제가 따라잡힌 뒤, 그리고 컷오버 직후 새 쓰기가 들어가기 전에 실행한다.

```bash
./12-verify.sh
mariadb --defaults-extra-file=./target.cnf -e "
SELECT id, status FROM appdb.orders ORDER BY id;
CALL appdb.order_count();"
```

통과: `orders source=3 target=3`, 프로시저 결과 `3`. 행이 다르면 스크립트가 실패한다. Galera는 같은 클러스터 안에서 `wsrep_last_committed`가 같아야 한다. `RUN_CHECKSUM=1`이면 `orders` 체크섬도 비교한다.

계정은 논리 덤프에 없다. 애플리케이션 계정은 대상에 따로 만든다.
