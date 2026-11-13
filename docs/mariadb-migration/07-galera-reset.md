# 경로 B. Galera 대상을 지우고 다시 이관

지우는 쪽은 대상 클러스터 `10.0.2.21`~`23`이다. 원본 클러스터는 유지한다.

두 가지 순서가 있다.

- 클러스터를 유지한 채 `appdb`만 교체한다. 덤프가 작고 세 노드가 `Synced`일 때 [GR-2A](#gr-2a-데이터베이스만-삭제)를 쓴다.
- 데이터 디렉터리를 백업으로 다시 맞춘다. 덤프가 크거나 노드 상태를 다시 만들어야 하면 [GR-2B](#gr-2b-조인-노드에-sst를-강제)를 쓴다.

어느 쪽이든 먼저 복제를 끊고, 끝난 뒤에는 새 백업의 좌표로 T1만 복제를 다시 시작한다.

## GR-1. T1 복제를 끊는다

목적: 삭제나 디렉터리 교체 중에 S1 이벤트가 들어오지 않게 한다.

`11-reset-target-database.sh`는 복제가 설정되어 있으면 `STOP SLAVE`와 `RESET SLAVE ALL`을 실행한 다음 데이터베이스를 삭제한다. 디렉터리 전체를 교체할 때는 삭제 SQL이 필요 없다. 그때는 T1에서 복제만 멈춘다.

```sql
STOP SLAVE;
RESET SLAVE ALL;
```

샘플 출력은 빈 결과와 프롬프트다. `SHOW SLAVE STATUS`가 이후 빈 결과면 끊긴 것이다.

통과 기준: T1에 복제 IO 스레드가 없다.

## GR-2A. 데이터베이스만 삭제

목적: 세 노드가 떠 있는 상태에서 `appdb`만 비운다.

기본 TOI에서는 T1의 `DROP DATABASE`가 T2, T3에 복제된다. 스크립트는 삭제 후 `TARGET_NODES`마다 스키마가 없는지 확인한다.

```bash
./11-reset-target-database.sh
```

샘플 출력:

```text
대상 appdb 를 삭제합니다.
복제 정보를 제거했습니다.
DROP DATABASE appdb 를 실행했습니다.
10.0.2.21 schema_count=0
10.0.2.22 schema_count=0
10.0.2.23 schema_count=0
```

한 노드라도 `schema_count=1`이면 `replicate-do-db` 때문에 DDL이 빠졌을 수 있다. 그 노드에서 같은 `DROP DATABASE`를 실행해 0으로 맞춘다.

통과 기준: 세 노드 모두 `appdb`가 없다.

이어서 논리 덤프 경로로 다시 넣는다. 세 노드가 떠 있으면 적재 write-set이 클러스터 전체로 퍼진다. 용량이 크면 GR-2A 대신 T2, T3를 멈추고 T1만 남긴 상태에서 `06-import-logical.sh`를 실행한 뒤 SST로 맞춘다.

1. S1에서 `04-dump-logical.sh`로 새 덤프를 뜬다. 예전 좌표 `1578` 파일을 재사용하지 않는다.
2. `06-import-logical.sh`
3. 새 GTID로 `07-start-replica.sh`
4. [G-8](05-galera-initial.md#g-8-합류-확인)

새 덤프 헤더 샘플:

```text
SET GLOBAL gtid_slave_pos='0-1-48255';
-- CHANGE MASTER TO MASTER_LOG_FILE='mysql-bin.000042', MASTER_LOG_POS=2401;
```

## GR-2B. 조인 노드에 SST를 강제

목적: T1을 새 물리 백업으로 교체한 뒤 T2, T3가 옛 seqno로 IST 하지 않게 한다.

순서:

1. 대상 세 노드의 애플리케이션 접속을 끊고 MariaDB를 멈춘다.
2. S1에서 `13-galera-backup.sh`로 새 백업을 만든다.
3. T1에서만 `14-galera-restore.sh`를 실행하고 `galera_new_cluster`로 올린다.
4. T2와 T3 각각에서 `NODE_ROLE=joiner`를 설정하고 `15-galera-force-sst.sh`를 실행한다. T1에서는 실행하지 않는다.

T2에서의 명령:

```bash
NODE_ROLE=joiner ./15-galera-force-sst.sh
```

스크립트는 그 노드의 MariaDB를 멈추고 `grastate.dat`를 `grastate.dat.bak.시각`으로 옮긴 다음 다시 기동한다.

샘플 출력:

```text
grastate.dat 를 옮겼습니다.
기동했습니다. 저널에서 SST 완료를 확인하세요: journalctl -u mariadb -n 50
```

저널에 SST 완료가 보이고 `wsrep_local_state_comment`가 `Synced`면 조인이 끝난 것이다. IST로 붙었다는 로그만 보이고 행 수가 T1과 다르면 노드를 멈추고 `grastate.dat`뿐 아니라 그 노드의 `galera.cache`를 치운 뒤 다시 기동한다.

통과 기준: 대상 size가 `3`이고 세 노드의 `wsrep_last_committed`가 같으며 `orders` 행 수가 T1과 같다.

## GR-3. 새 좌표로 T1 복제만 재개

목적: 이번 백업 이후의 변경만 따라간다.

`xtrabackup_binlog_info`의 새 GTID를 `GTID_SLAVE_POS`에 넣고 T1에서만:

```bash
./07-start-replica.sh
./08-watch-replica.sh
```

T2, T3의 복제 설정은 비어 있는 상태를 유지한다.

통과 기준: [GI-1](06-galera-incremental.md#gi-1-복제-노드가-하나인지-확인)과 [GI-2](06-galera-incremental.md#gi-2-지연과-galera-큐를-본다)를 만족한다. 이후 컷오버는 [GI-3](06-galera-incremental.md#gi-3-원본-모든-노드의-쓰기를-멈춘다)부터다.
