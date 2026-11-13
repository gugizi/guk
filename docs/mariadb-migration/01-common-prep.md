# C. 공통 준비

경로 A와 경로 B가 같이 수행한다. Galera는 `SOURCE_NODES`와 `TARGET_NODES`를 비워 두지 않는다. 단일 인스턴스는 두 값을 비워 둔다.

## C-1. 경로와 샘플 값을 확정한다

목적: 이후 스크립트가 어느 호스트를 원본과 대상으로 볼지 고정한다.

`scripts/config.sample.env`를 `scripts/config.env`로 복사한다. 단일 인스턴스 샘플은 아래와 같다.

```bash
SOURCE_HOST=10.0.0.11
SOURCE_PORT=3306
TARGET_HOST=10.0.0.21
TARGET_PORT=3306
DB_NAME=appdb
DUMP_FILE=/backup/appdb-full.sql
BACKUP_DIR=/backup/appdb-full
CONFIRM=NO
```

Galera 샘플은 호스트를 노드 목록으로 바꾼다. `SOURCE_HOST`는 백업과 복제 원본으로 쓸 S1이다. `target.cnf`의 host는 T1이다.

```bash
SOURCE_HOST=10.0.1.11
TARGET_HOST=10.0.2.21
SOURCE_NODES=10.0.1.11,10.0.1.12,10.0.1.13
TARGET_NODES=10.0.2.21,10.0.2.22,10.0.2.23
```

통과 기준: `config.env`가 작업 대상 호스트만 가리킨다.

## C-2. 클라이언트 설정 파일을 만든다

목적: 비밀번호를 프로세스 인자 대신 옵션 파일로 전달한다.

```bash
cd docs/mariadb-migration/scripts
cp source.cnf.sample source.cnf
cp target.cnf.sample target.cnf
cp dump.cnf.sample dump.cnf
cp backup.cnf.sample backup.cnf
chmod 600 source.cnf target.cnf dump.cnf backup.cnf config.env
```

`source.cnf`와 `target.cnf`는 관리 계정이다. `dump.cnf`는 C-7에서 만들 덤프 계정과 비밀번호가 같아야 한다. `backup.cnf`는 S1 로컬의 `backup`@`localhost` 계정이며 `[mariabackup]` 그룹을 사용한다. `mariabackup`은 `[client]` 그룹을 읽지 않는다.

샘플 `source.cnf`:

```ini
[client]
host=10.0.0.11
port=3306
user=root
password=change-me
default-character-set=utf8mb4
```

통과 기준: 네 파일의 host, user, password가 C-1과 같다. 이 파일은 git에 올리지 않는다.

## C-3. 작업 호스트에 클라이언트가 있는지 확인한다

목적: 이후 스크립트가 사용할 바이너리를 확인한다.

실행 위치: 덤프 파일을 저장할 작업 호스트.

```bash
command -v mariadb
command -v mariadb-dump
command -v mariabackup
```

샘플 출력:

```text
/usr/bin/mariadb
/usr/bin/mariadb-dump
/usr/bin/mariabackup
```

물리 백업을 쓰지 않는 경로 A는 `mariabackup`이 작업 호스트에 없어도 된다. G-3와 G-5는 S1과 T1에 `mariabackup`이 있어야 한다.

## C-4. 접속과 binlog를 점검한다

목적: 증분을 붙일 수 있는 원본인지 확인한다.

```bash
./01-precheck.sh
```

스크립트는 원본과 대상의 버전, `server_id`, `log_bin`, `binlog_format`을 출력한다. `SOURCE_NODES`가 있으면 노드마다 Galera 상태도 출력한다.

샘플 출력:

```text
hostname  port  version  version_comment
db-src    3306  10.11.13 MariaDB Server
Variable_name                  Value
server_id                      1
log_bin                        ON
binlog_format                  ROW
log_slave_updates              ON
binlog_expire_logs_seconds     604800
```

통과 기준: 접속이 되고, 원본 `log_bin`이 `ON`, `binlog_format`이 `ROW`다. 하나라도 아니면 스크립트가 종료 코드 1로 끝난다.

`log_bin`을 켜려면 원본 재시작이 필요하다. 보관 기간은 덤프 시작부터 복제가 연결되기까지보다 길어야 한다. 10.6 미만은 `expire_logs_days`를 쓴다.

```ini
[mariadb]
server-id = 1
log_bin = mysql-bin
binlog_format = ROW
log_slave_updates = ON
binlog_expire_logs_seconds = 604800
```

Galera는 모든 노드에 같은 `log_bin` 경로, `log_slave_updates=ON`, `binlog_format=ROW`, `innodb_autoinc_lock_mode=2`가 필요하다. 설정 예는 [`samples/galera-node.cnf.sample`](samples/galera-node.cnf.sample)이다. `server_id`와 `wsrep_gtid_domain_id`는 클러스터 안에서 같고 클러스터끼리는 다르다. 노드별 `gtid_domain_id`는 서로 다르고 `wsrep_gtid_domain_id`와도 다르다.

## C-5. 이관 대상을 조사한다

목적: 엔진, 용량, 루틴 수를 적재 전에 남긴다.

```bash
./02-collect-inventory.sh
```

샘플 출력:

```text
ENGINE   tables_count
InnoDB   1
table_name  table_rows  size_mb
orders      2           0.1
routines  triggers  events
1         0         0
엔진: InnoDB
```

통과 기준: 대상 데이터베이스 이름과 테이블 목록이 애플리케이션 범위와 같다. `table_rows`는 InnoDB 추정치라서 2가 아니어도 이 단계에서는 실패로 보지 않는다. 정확한 건수는 V-1에서 `COUNT(*)`로 비교한다.

InnoDB 이외 엔진이 있으면 스크립트가 경고를 낸다. 경로 A의 `--single-transaction`은 InnoDB 스냅샷이다. MyISAM이나 Aria가 있으면 덤프 전에 `--lock-all-tables`가 필요하다. Galera는 InnoDB만 노드 전체에 안정적으로 복제한다.

## C-6. 디스크 여유를 확인한다

목적: 덤프 파일과 적재 중 임시 공간을 확보한다.

실행 위치: 덤프를 저장할 호스트와 대상 서버.

```bash
df -h /backup /var/lib/mysql
```

샘플 출력:

```text
Filesystem   Size  Used Avail Use% Mounted on
/dev/sda1    200G   40G  160G  20% /
```

통과 기준: 덤프를 받을 쪽에 데이터베이스 크기 이상의 여유가 있고, 대상 데이터 디렉터리에는 적재분이 들어갈 여유가 있다. 물리 복원은 기존 디렉터리를 `DATADIR.bak.시각`으로 옮기므로 T1에는 데이터 크기만큼의 추가 여유가 더 필요하다.

## C-7. 이관 계정을 만든다

목적: 덤프, 복제, 로컬 물리 백업 권한을 관리 계정과 분리한다.

`CONFIRM=YES`로 바꾼 뒤 원본에서 실행한다.

```bash
./03-create-users.sh
```

스크립트가 만드는 계정:

| 계정 | 호스트 | 용도 |
| --- | --- | --- |
| `dump` | `%` | `mariadb-dump`. `SELECT`, `SHOW VIEW`, `TRIGGER`, `LOCK TABLES`, `EVENT`, `RELOAD`, `REPLICATION CLIENT` |
| `repl` | `REPL_HOST` 기본 `%` | `REPLICATION SLAVE` |
| `backup` | `localhost` | S1의 `mariabackup`. `RELOAD`, `PROCESS`, `LOCK TABLES`, `REPLICATION CLIENT` |

샘플 출력:

```text
계정을 만들었습니다.
GRANT SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT, RELOAD, REPLICATION CLIENT ON *.* TO `dump`@`%`
GRANT REPLICATION SLAVE ON *.* TO `repl`@`%`
```

통과 기준: 세 `SHOW GRANTS`가 출력된다. 운영에서는 `repl` 호스트를 대상 노드 IP로 좁힌다. 비밀번호에 작은따옴표가 있으면 스크립트가 멈춘다.

애플리케이션 계정에는 `SUPER`를 주지 않는다. 컷오버의 `read_only`는 `SUPER` 계정에 적용되지 않고, `super_read_only`까지 켜야 막힌다.

## C-8. 대상을 읽기 전용으로 둔다

목적: 적재와 증분 동안 대상에 다른 쓰기가 섞이지 않게 한다.

```bash
./set-target-readonly.sh
```

Galera면 `TARGET_NODES` 전부를 바꾼다. 스크립트는 `read_only=ON`, `super_read_only=OFF`로 둔다. 일반 애플리케이션 계정은 쓰기가 막히고, `SUPER` 관리 계정은 적재와 `DROP`을 할 수 있다. 복제 스레드와 Galera 적용 스레드는 `read_only`에서도 동작한다. `super_read_only`는 원본을 전환 직전에 동결할 때만 켠다.

샘플 출력:

```text
Variable_name     Value
read_only         ON
super_read_only   OFF
```

통과 기준: 대상의 모든 노드가 `read_only=ON`, `super_read_only=OFF`다.

다음 단계는 경로 A면 [최초 이관](02-standalone-initial.md), 경로 B면 [Galera 최초 이관](05-galera-initial.md)이다. 대상에 `appdb`가 이미 있으면 적재 전에 [초기화](04-standalone-reset.md) 또는 [Galera 초기화](07-galera-reset.md)를 한다.
