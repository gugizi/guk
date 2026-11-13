# 경로 A. 단일 인스턴스 최초 이관

전제: [공통 준비](01-common-prep.md)가 끝났고 대상은 읽기 전용이다. 대상에 `appdb`가 있으면 [초기화](04-standalone-reset.md)를 먼저 한다.

이 장의 샘플은 덤프 시점에 `orders`가 2행이고, 좌표가 `0-1-48231`, `mysql-bin.000042`의 `1578`이다.

## S-1. 논리 덤프

목적: InnoDB 스냅샷과 그 시점의 복제 좌표를 한 파일에 남긴다.

실행 위치: 작업 호스트. 원본 `10.0.0.11`에 접속한다.

```bash
./04-dump-logical.sh
```

같은 명령:

```bash
mariadb-dump \
  --defaults-extra-file=./dump.cnf \
  --single-transaction \
  --master-data=2 \
  --gtid \
  --routines --triggers --events \
  --hex-blob \
  --default-character-set=utf8mb4 \
  --databases appdb \
  > /backup/appdb-full.sql
```

`--single-transaction`은 덤프 동안 테이블을 오래 잠그지 않는다. `--master-data=2`는 `CHANGE MASTER`를 주석으로 넣고, `--gtid`는 `SET GLOBAL gtid_slave_pos`를 넣는다. `--databases`가 있어야 `CREATE DATABASE`가 포함된다. 덤프 중 원본 DDL은 하지 않는다.

샘플 출력:

```text
덤프 시작: /backup/appdb-full.sql
덤프 완료: 18432 bytes
```

통과 기준: 종료 코드 0이고 파일 크기가 0보다 크다.

## S-2. 좌표 기록

목적: 증분 시작점을 작업 기록에 남긴다. 적재가 성공하면 덤프 안의 `SET GLOBAL`이 대상에 같은 값을 넣는다.

```bash
./05-extract-coordinates.sh
```

샘플 출력:

```text
======== GTID ========
22:SET GLOBAL gtid_slave_pos='0-1-48231';
======== BINLOG ========
18:-- CHANGE MASTER TO MASTER_LOG_FILE='mysql-bin.000042', MASTER_LOG_POS=1578;
```

좌표가 없으면 스크립트가 실패한다. 그 덤프로는 증분을 붙이지 않고, S-1부터 다시 한다.

GTID를 쓰려면 `config.env`에 다음을 적는다. 적재 스크립트가 덤프를 그대로 실행하면 대상에 이미 설정되므로 비워 둘 수 있다.

```bash
GTID_SLAVE_POS=0-1-48231
BINLOG_FILE=mysql-bin.000042
BINLOG_POS=1578
```

통과 기준: GTID 한 줄과 binlog 파일, 포지션이 작업 기록에 있다.

## S-3. 대상이 비어 있는지 확인

목적: 기존 테이블 위에 덤프를 겹쳐 넣지 않는다.

```bash
mariadb --defaults-extra-file=./target.cnf -e "SHOW DATABASES LIKE 'appdb';"
```

샘플 출력은 빈 결과다.

```text
```

`appdb`가 보이면 [R-1](04-standalone-reset.md#r-1-복제를-끊는다)부터 초기화한다. 적재 스크립트도 스키마가 있으면 멈추도록 되어 있다.

## S-4. 적재

목적: 스냅샷을 대상 `10.0.0.21`에 만든다.

`CONFIRM=YES`가 필요하다.

```bash
./06-import-logical.sh
```

적재 계정은 `target.cnf`의 관리 계정이다. 덤프의 `SET GLOBAL gtid_slave_pos`를 실행할 권한이 있어야 한다.

샘플 출력:

```text
적재 시작: /backup/appdb-full.sql
적재가 끝났습니다.
0-1-48231
```

통과 기준: 마지막 줄이 덤프의 GTID와 같다.

실패 예: 루틴의 `DEFINER` 계정이 대상에 없으면 해당 객체에서 적재가 멈춘다. 샘플 프로시저 `order_count`의 DEFINER가 `app`@`10.0.0.11`이면 대상에 그 계정을 만들거나 덤프의 DEFINER를 대상 계정으로 바꾼 뒤 S-3 상태로 되돌려 다시 넣는다.

이 시점의 대상 `orders`는 2행이다. 원본에는 덤프 직후 아래 행이 들어왔다고 가정한다. 아직 대상에는 없다.

| id | customer_id | status | updated_at |
| --- | --- | --- | --- |
| 3 | 102 | paid | 2026-11-13 09:40:00 |

## S-5. 복제 시작

목적: 덤프 이후 변경을 대상이 따라가게 한다.

실행 위치: 대상 하나. 이 경로에서는 `10.0.0.21`뿐이다.

```bash
./07-start-replica.sh
```

`GTID_SLAVE_POS`가 있으면 그 값으로 `gtid_slave_pos`를 다시 설정한다. 비어 있으면 적재가 남긴 값을 사용한다. 그 값도 없으면 시작하지 않는다. GTID 없이 파일과 포지션만 있을 때는 `BINLOG_FILE`과 `BINLOG_POS`를 함께 넣는다.

스크립트가 실행하는 GTID 형태:

```sql
CHANGE MASTER TO
  MASTER_HOST='10.0.0.11',
  MASTER_PORT=3306,
  MASTER_USER='repl',
  MASTER_PASSWORD='change-me',
  MASTER_USE_GTID=slave_pos;
START SLAVE;
```

샘플 출력:

```text
덤프가 설정한 gtid_slave_pos=0-1-48231 를 사용합니다.
복제를 시작했습니다.
```

이미 IO 스레드가 `Yes`면 중복 시작을 막기 위해 실패한다.

통과 기준: 종료 코드 0.

## S-6. 동기화 확인

목적: 덤프 이후 행이 대상에 도착했는지 본다.

```bash
./08-watch-replica.sh
./12-verify.sh
```

`12-verify.sh`는 `EXACT_COUNT_TABLES`의 `COUNT(*)`를 비교한다. 샘플은 `orders`다. 복제가 따라잡은 뒤의 샘플:

```text
Slave_IO_Running: Yes
Slave_SQL_Running: Yes
Seconds_Behind_Master: 0
Last_SQL_Error:
orders source=3 target=3
비교한 테이블의 행 수가 같습니다.
```

`Last_SQL_Error`에 `Duplicate entry`가 있으면 좌표가 덤프 스냅샷보다 앞이다. 복제를 멈추고 [초기화](04-standalone-reset.md) 후 S-1부터 다시 한다. 같은 구간을 두 번 적용한 상태다.

통과 기준: IO와 SQL이 `Yes`, 지연이 `0`, 샘플 테이블 행 수가 같다.

컷오버는 [증분 절차](03-standalone-incremental.md)로 넘어간다. 전환 시각까지 복제는 켜 둔다. 증분마다 덤프를 다시 뜨지 않는다.
