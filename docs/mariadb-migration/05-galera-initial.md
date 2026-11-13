# 경로 B. Galera 최초 이관

전제: [공통 준비](01-common-prep.md)가 끝났고, 원본 세 노드와 대상 세 노드가 샘플 주소다. 대상은 원본 클러스터의 네 번째 노드로 조인하지 않는다.

덤프와 비동기 복제는 S1과 T1만 담당한다. 같은 덤프를 T2, T3에 다시 넣지 않는다. 라이브 노드에서 `wsrep_on=OFF`로 넣으면 그 노드만 데이터가 생기고 클러스터가 어긋난다.

대용량이거나 대상 클러스터를 새로 맞출 때는 물리 백업 경로를 쓴다. 데이터가 작고 대상 T1만 떠 있는 상태면 [논리 덤프 경로](#논리-덤프-경로)를 쓴다.

## G-1. 클러스터 상태

목적: 백업 노드와 조인 노드가 Primary이고 동기화된 상태인지 확인한다.

```bash
./01-precheck.sh
```

`SOURCE_NODES`가 채워져 있으면 노드별 상태가 출력된다.

샘플 출력:

```text
-- 10.0.1.11
Variable_name               Value
wsrep_cluster_size          3
wsrep_local_state_comment   Synced
wsrep_ready                 ON
wsrep_cluster_status        Primary
wsrep_last_committed        90210
```

S2, S3도 `wsrep_last_committed`가 `90210`이고 size가 `3`이어야 한다.

통과 기준: 세 노드가 `Synced`, `wsrep_ready=ON`, `Primary`, 같은 `wsrep_last_committed`다. 대상 노드를 이미 띄운 상태라면 대상도 size `3`인지 본다. 새로 구성하는 중이면 대상은 아직 1대일 수 있다.

## G-2. 복제에 필요한 설정

목적: 비동기 복제 이벤트가 Galera write-set으로 나머지 노드에 전달되게 한다.

모든 노드에서 다음이 같거나, 문서에 적은 대로 노드마다 달라야 한다.

| 항목 | 샘플 | 범위 |
| --- | --- | --- |
| `log_bin` | `/var/log/mysql/mysql-bin` | 클러스터 안에서 같은 경로 |
| `log_slave_updates` | `ON` | 모든 노드 |
| `wsrep_gtid_mode` | `ON` | 모든 노드 |
| `wsrep_gtid_domain_id` | 원본 `10`, 대상 `20` | 클러스터 안에서 같고, 클러스터끼리는 다름 |
| `server_id` | 원본 `100`, 대상 `200` | 클러스터 안에서 같고, 클러스터끼리는 다름 |
| `gtid_domain_id` | S1 `111`, T1 `221` | 노드마다 다르고 `wsrep_gtid_domain_id`와 다름 |
| `wsrep_sst_method` | `mariabackup` | 모든 노드. 거부하면 `mariadb-backup` |
| `innodb_autoinc_lock_mode` | `2` | 모든 노드 |

설정 파일 예는 [`samples/galera-node.cnf.sample`](samples/galera-node.cnf.sample)이다. SST에는 `socat`이 필요하다. 노드 사이 포트는 `3306`, Galera `4567`, IST `4568`, SST `4444`다.

통과 기준: C-4 출력에 위 값이 보인다.

## G-3. S1 물리 백업

목적: 클러스터 전체 상태가 들어 있는 일관 백업과 binlog 좌표를 S1에서 만든다.

실행 위치: S1 `10.0.1.11`. 스크립트와 `backup.cnf`, `config.env`를 S1에 두고 실행한다. `BACKUP_DIR`는 비어 있는 디렉터리여야 한다.

```bash
./13-galera-backup.sh
```

같은 명령:

```bash
mariabackup --backup \
  --target-dir=/backup/appdb-full \
  --defaults-extra-file=./backup.cnf
mariabackup --prepare --target-dir=/backup/appdb-full
```

샘플 출력:

```text
백업 시작: /backup/appdb-full
======== xtrabackup_binlog_info ========
mysql-bin.000042	1578	0-1-48231
```

필드는 binlog 파일, 포지션, GTID다. 탭으로 구분된다.

통과 기준: `xtrabackup_binlog_info`에 GTID `0-1-48231`이 있다. 세 번째 필드가 없으면 `wsrep_gtid_mode`와 `log_slave_updates`를 확인한 뒤 백업을 다시 뜬다.

## G-4. 좌표 기록

목적: T1 복제의 시작점을 백업 파일 기준으로 고정한다.

S1의 좌표를 작업 호스트 `config.env`에 적는다.

```bash
GTID_SLAVE_POS=0-1-48231
BINLOG_FILE=mysql-bin.000042
BINLOG_POS=1578
SOURCE_HOST=10.0.1.11
```

다른 노드의 `SHOW MASTER STATUS` 값으로 바꾸지 않는다. 백업을 뜬 노드와 복제 원본 노드는 S1로 같다.

통과 기준: 설정 파일의 GTID가 `xtrabackup_binlog_info` 세 번째 필드와 같다.

## G-5. T1 복원

목적: 대상 클러스터의 첫 노드만 백업 내용으로 만든다.

실행 위치: T1. 먼저 T2, T3의 MariaDB는 멈춘다. T1도 멈춘다.

```bash
systemctl stop mariadb
```

T1에서 `CONFIRM=YES`와 `CONFIRM_DATADIR=YES`를 설정한 뒤:

```bash
./14-galera-restore.sh
```

스크립트는 `DATADIR`이 `/`, `/var`, `/var/lib`이면 거절한다. 기본값 `/var/lib/mysql`은 시각이 붙은 디렉터리로 옮긴 다음 `--copy-back` 한다.

샘플 출력:

```text
기존 데이터 디렉터리를 /var/lib/mysql.bak.20261113110000 로 옮깁니다.
복원이 끝났습니다. 이 노드에서만 다음을 실행하세요: galera_new_cluster
mysql-bin.000042	1578	0-1-48231
```

이어서 T1에서만:

```bash
galera_new_cluster
```

`systemctl start`로 첫 노드를 올리면 Primary를 찾지 못한다. `galera_new_cluster`가 새 클러스터를 만든다.

통과 기준: T1에서 아래 값이 나온다.

```text
wsrep_cluster_size          1
wsrep_local_state_comment   Synced
wsrep_ready                 ON
```

`orders`는 백업 시점의 2행이다.

## G-6. T1만 복제

목적: S1의 덤프 이후 변경을 T1이 받고, Galera가 T2와 T3에 전달할 기반을 만든다.

T1의 관리 접속으로 작업 호스트에서 실행한다. `target.cnf`의 host는 T1이다. T2와 T3에서는 실행하지 않는다.

```bash
./07-start-replica.sh
```

`GTID_SLAVE_POS=0-1-48231`이면 스크립트가 그 값을 설정한 뒤 `MASTER_USE_GTID=slave_pos`로 S1을 본다.

샘플 출력:

```text
gtid_slave_pos 를 0-1-48231 로 설정했습니다.
복제를 시작했습니다.
```

```bash
./08-watch-replica.sh
```

샘플:

```text
Slave_IO_Running: Yes
Slave_SQL_Running: Yes
Seconds_Behind_Master: 0
Gtid_IO_Pos: 0-1-48255
```

T1 `orders`는 증분 행이 반영되어 3행이다. 아직 T2, T3는 멈춰 있다.

통과 기준: T1의 IO와 SQL이 `Yes`이고 지연이 `0`이다. `SHOW SLAVE STATUS`는 T1에서만 복제 스레드가 보여야 한다.

## G-7. 나머지 노드 SST

목적: T2와 T3가 T1의 데이터 디렉터리를 통째로 받게 한다.

T2, T3는 일반 기동이다. 클러스터 주소에 T1이 들어 있어야 한다.

```bash
systemctl start mariadb
```

옛 `grastate.dat`의 seqno가 남으면 IST가 이전 데이터 위에 차이만 얹을 수 있다. 대상 데이터를 백업으로 다시 맞추는 경우에는 T2, T3에서 [GR-2B](07-galera-reset.md#gr-2b-조인-노드에-sst를-강제)의 `15-galera-force-sst.sh`를 쓴다. 새 디렉터리로 처음 조인하는 노드에는 `grastate.dat`가 없으므로 `systemctl start`만으로 SST가 시작된다.

SST 방법 `mariabackup`은 donor를 장시간 잠그지 않는다. donor는 T1이다. T1의 비동기 복제는 SST 중에도 유지된다.

저널 샘플:

```text
WSREP_SST: [INFO] mariabackup SST started
WSREP_SST: [INFO] Procedure completed
```

통과 기준: T2, T3가 `Synced`가 되고 `wsrep_cluster_size`가 `3`이다.

## G-8. 합류 확인

목적: 세 노드가 같은 적용 지점에 있는지 확인한다.

```bash
./12-verify.sh
```

샘플 출력:

```text
orders source=3 target=3
-- target 10.0.2.21
wsrep_cluster_size          3
wsrep_local_state_comment   Synced
wsrep_last_committed        1204
-- target 10.0.2.22
wsrep_last_committed        1204
-- target 10.0.2.23
wsrep_last_committed        1204
```

세 대상 노드의 `wsrep_last_committed`가 같아야 한다. 값은 원본의 `90210`과 숫자 자체가 같지 않아도 된다. 클러스터가 다르기 때문이다. 같은 클러스터 안에서는 같아야 한다.

통과 기준: 행 수가 같고, 대상 세 노드가 `Synced`이며 size가 `3`이다. 컷오버는 [Galera 증분](06-galera-incremental.md)이다.

## 논리 덤프 경로

물리 백업 대신 `04-dump-logical.sh`를 쓸 때의 순서다. 좌표는 덤프 헤더의 `0-1-48231`을 그대로 쓴다.

1. T2, T3를 멈춘다.
2. T1만 `galera_new_cluster`로 띄운다. 데이터 디렉터리에 이전 `appdb`가 있으면 [GR-2A](07-galera-reset.md#gr-2a-데이터베이스만-삭제)를 노드가 T1뿐일 때 실행한다.
3. `06-import-logical.sh`로 T1에만 넣는다.
4. `07-start-replica.sh`를 T1에만 실행한다.
5. T2, T3를 기동해 SST를 받는다.
6. G-8을 확인한다.

라이브 3노드에 대용량 덤프를 그대로 넣으면 write-set 크기와 flow control로 클러스터가 멈출 수 있다. 그 경우는 이 순서처럼 노드 하나를 먼저 채운다.
