# MariaDB 데이터 이관 작업 절차

MariaDB 10.6 이상, 대상이 단일 인스턴스이거나 MariaDB Galera인 경우를 다룬다. 작업은 아래 순서만 따른다.

1. 경로를 고른다.
2. 공통 준비를 한다.
3. 대상에 데이터가 있으면 초기화를 먼저 한다.
4. 최초 스냅샷을 넣는다.
5. 그 좌표 이후를 복제로 따라간다.
6. 지연이 0이면 전환한다.
7. 샘플 기준으로 검증한다.

스크립트는 [`scripts/`](scripts/)에 있다. 호스트와 비밀번호는 샘플이므로 `config.sample.env`와 `*.cnf.sample`을 복사해 실제 값으로 바꾼 뒤 실행한다.

## 샘플 환경

절차서의 출력 예는 모두 이 값을 사용한다.

| 항목 | 단일 인스턴스 | Galera |
| --- | --- | --- |
| 원본 | `10.0.0.11:3306` | S1 `10.0.1.11`, S2 `10.0.1.12`, S3 `10.0.1.13` |
| 대상 | `10.0.0.21:3306` | T1 `10.0.2.21`, T2 `10.0.2.22`, T3 `10.0.2.23` |
| 데이터베이스 | `appdb` | `appdb` |
| 문자셋 | `utf8mb4` | `utf8mb4` |
| 덤프 시점 GTID | `0-1-48231` | `0-1-48231` |
| 덤프 시점 binlog | `mysql-bin.000042` / `1578` | 같은 값 |
| 컷오버 시점 GTID | `0-1-48255` | `0-1-48255` |

샘플 데이터는 [`samples/appdb-seed.sql`](samples/appdb-seed.sql)이다. 운영 서버에 실행하지 않는다. 내용은 `appdb.orders` 2행과 프로시저 `order_count`다.

| id | customer_id | status | updated_at |
| --- | --- | --- | --- |
| 1 | 100 | paid | 2026-11-13 09:00:00 |
| 2 | 101 | new | 2026-11-13 09:05:00 |

덤프 이후 원본에 id `3`이 추가되고, 복제가 그 행을 대상에 반영하는 것이 증분 샘플이다.

## 경로 선택

| 경로 | 문서 | 사용할 때 |
| --- | --- | --- |
| A. 단일 인스턴스 | [최초](02-standalone-initial.md), [증분](03-standalone-incremental.md), [초기화](04-standalone-reset.md) | 원본과 대상이 각각 서버 1대 |
| B. Galera | [최초](05-galera-initial.md), [증분](06-galera-incremental.md), [초기화](07-galera-reset.md) | 원본 또는 대상이 Galera |

Galera 대상은 원본 클러스터에 조인하지 않는다. `galera_new_cluster`로 별도 클러스터를 만든다. 덤프와 비동기 복제는 노드 하나, 나머지 노드는 SST다.

## 경로 A 작업 순서

대상이 비어 있을 때:

- [ ] [C-1 ~ C-8 공통 준비](01-common-prep.md)
- [ ] [S-1 논리 덤프](02-standalone-initial.md#s-1-논리-덤프)
- [ ] [S-2 좌표 기록](02-standalone-initial.md#s-2-좌표-기록)
- [ ] [S-3 대상이 비어 있는지 확인](02-standalone-initial.md#s-3-대상이-비어-있는지-확인)
- [ ] [S-4 적재](02-standalone-initial.md#s-4-적재)
- [ ] [S-5 복제 시작](02-standalone-initial.md#s-5-복제-시작)
- [ ] [S-6 동기화 확인](02-standalone-initial.md#s-6-동기화-확인)
- [ ] [I-1 ~ I-5 컷오버](03-standalone-incremental.md)
- [ ] [V-1 검증](08-verify-and-rollback.md)

대상에 이전 이관 데이터가 있을 때:

- [ ] C-1 ~ C-8
- [ ] [R-1 ~ R-3 초기화](04-standalone-reset.md)
- [ ] S-1부터 다시 진행

## 경로 B 작업 순서

대상 클러스터를 새로 비우고 물리 백업으로 올릴 때:

- [ ] C-1 ~ C-8. `SOURCE_NODES`, `TARGET_NODES`를 채운다
- [ ] [G-1 ~ G-2 클러스터 확인](05-galera-initial.md#g-1-클러스터-상태)
- [ ] [G-3 S1 백업](05-galera-initial.md#g-3-s1-물리-백업)
- [ ] [G-4 좌표 기록](05-galera-initial.md#g-4-좌표-기록)
- [ ] [G-5 T1 복원과 부트스트랩](05-galera-initial.md#g-5-t1-복원)
- [ ] [G-6 T1만 복제 시작](05-galera-initial.md#g-6-t1만-복제)
- [ ] [G-7 T2 T3 SST](05-galera-initial.md#g-7-나머지-노드-sst)
- [ ] [G-8 클러스터 확인](05-galera-initial.md#g-8-합류-확인)
- [ ] [GI-1 ~ GI-5 컷오버](06-galera-incremental.md)
- [ ] V-1 검증

이미 떠 있는 대상 클러스터의 데이터베이스만 갈아끼울 때:

- [ ] C-1 ~ C-8
- [ ] [GR-1 ~ GR-2A 논리 초기화](07-galera-reset.md#gr-2a-데이터베이스만-삭제)
- [ ] 논리 덤프 경로([G-L](05-galera-initial.md#논리-덤프-경로))로 S-1, S-4, G-6
- [ ] GI 컷오버

## 스크립트와 단계

작업 호스트에서 `docs/mariadb-migration/scripts`로 이동해 실행한다. 서버 안에서만 실행하는 스크립트는 각 단계에 적어 둔다.

| 스크립트 | 단계 | 데이터를 변경함 |
| --- | --- | --- |
| `01-precheck.sh` | C-4 | 아니오 |
| `02-collect-inventory.sh` | C-5 | 아니오 |
| `03-create-users.sh` | C-7 | 계정 생성 |
| `set-target-readonly.sh` | C-8 | 대상 read_only |
| `04-dump-logical.sh` | S-1 | 아니오 |
| `05-extract-coordinates.sh` | S-2 | 아니오 |
| `06-import-logical.sh` | S-4 | 대상 적재 |
| `07-start-replica.sh` | S-5, G-6 | 복제 시작 |
| `08-watch-replica.sh` | I-1, S-6 | 아니오 |
| `09-freeze-source.sh` | I-2, GI-3 | 원본 read_only |
| `10-promote-target.sh` | I-4, GI-5 | 복제 중지, 대상 개방 |
| `11-reset-target-database.sh` | R-3, GR-2A | 대상 DROP |
| `12-verify.sh` | V-1 | 아니오 |
| `13-galera-backup.sh` | G-3 | S1에 백업 파일 생성 |
| `14-galera-restore.sh` | G-5 | T1 데이터 디렉터리 교체 |
| `15-galera-force-sst.sh` | GR-2B | joiner의 grastate 제거 |
| `16-rollback-open-source.sh` | 롤백 | 원본 개방, 대상 동결 |

변경 스크립트는 `config.env`의 `CONFIRM=YES`가 있어야 실행된다. `14-galera-restore.sh`는 `CONFIRM_DATADIR=YES`도 필요하다. `15-galera-force-sst.sh`는 실행 시에 `NODE_ROLE=joiner`를 앞에 붙인다. 이 값은 `config.env`에 넣지 않는다.
