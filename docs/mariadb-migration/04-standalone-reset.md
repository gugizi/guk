# 경로 A. 기존 데이터를 지우고 다시 이관

지우는 대상은 `10.0.0.21`이다. 원본 `10.0.0.11`은 변경하지 않는다.

이 절차는 최초 적재 앞에 온다. 이전 덤프의 좌표로 복제를 재개하지 않고, 초기화 다음에 새 덤프를 뜬다.

## R-1. 복제를 끊는다

목적: 삭제 도중 이전 복제 이벤트가 테이블에 들어가지 않게 한다.

대상에 복제가 있으면 `11-reset-target-database.sh`가 `STOP SLAVE`와 `RESET SLAVE ALL`을 먼저 실행한다. 복제 정보가 없으면 그 두 명령은 건너뛴다.

작업 전에 대상 애플리케이션 접속은 끊고, [C-8](01-common-prep.md#c-8-대상을-읽기-전용으로-둔다)로 읽기 전용인지 확인한다.

## R-2. 필요하면 대상의 현재 데이터를 보관한다

목적: 잘못된 이전 적재본을 비교용으로 남길 수 있게 한다.

보관이 필요하면 대상을 별도 파일로 덤프한다. 이 파일은 원본 덤프와 다른 경로에 둔다.

```bash
mariadb-dump \
  --defaults-extra-file=./target.cnf \
  --single-transaction \
  --routines --triggers --events \
  --databases appdb \
  > /backup/appdb-target-before-reset.sql
```

샘플 출력은 셸 프롬프트가 바로 돌아오는 것이다. 크기 확인:

```bash
wc -c /backup/appdb-target-before-reset.sql
```

```text
20480 /backup/appdb-target-before-reset.sql
```

통과 기준: 보관 파일을 만들기로 한 경우 크기가 0보다 크다. 보관이 필요 없으면 이 단계를 건너뛴다.

## R-3. 데이터베이스를 삭제한다

목적: 덤프에 없는 테이블이 대상에 남지 않게 한다. 덤프 안의 `DROP TABLE`만으로는 대상에만 있는 테이블이 남는다.

```bash
./11-reset-target-database.sh
```

실행 SQL:

```sql
STOP SLAVE;
RESET SLAVE ALL;
DROP DATABASE IF EXISTS `appdb`;
```

샘플 출력:

```text
대상 appdb 를 삭제합니다. 호스트는 target.cnf 기준입니다.
복제 정보를 제거했습니다.
DROP DATABASE appdb 를 실행했습니다.
```

통과 기준:

```bash
mariadb --defaults-extra-file=./target.cnf -e "SHOW DATABASES LIKE 'appdb';"
```

결과가 비어 있다. `mysql` 시스템 스키마와 다른 데이터베이스는 이 명령으로 지워지지 않는다.

행만 지우고 스키마를 유지해야 하면 `DROP` 대신 아래를 쓴다. 스키마가 원본과 달라졌을 수 있으면 이 방법 대신 R-3의 `DROP`과 전체 덤프를 쓴다.

```sql
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE appdb.orders;
SET FOREIGN_KEY_CHECKS = 1;
```

`TRUNCATE` 뒤에는 데이터만 있는 덤프가 필요하다. 이 절차서의 `04-dump-logical.sh`는 스키마를 포함한 전체 덤프이므로 `DROP DATABASE`와 짝을 이룬다.

## R-4. 새 스냅샷을 넣는다

목적: 초기화 이후의 원본 시점을 새 좌표로 가져온다.

[S-1](02-standalone-initial.md#s-1-논리-덤프)부터 [S-4](02-standalone-initial.md#s-4-적재)를 다시 실행한다. 예전 파일 `/backup/appdb-full.sql`을 재사용하지 않는다. 그 좌표와 현재 원본 사이의 변경분이 빠지거나, 이미 지운 대상과 맞지 않는다.

샘플이라면 새 덤프 헤더는 이전의 `1578`이 아니라 초기화 시점의 위치다.

```text
SET GLOBAL gtid_slave_pos='0-1-48255';
-- CHANGE MASTER TO MASTER_LOG_FILE='mysql-bin.000042', MASTER_LOG_POS=2401;
```

통과 기준: 적재 직후 대상 `@@gtid_slave_pos`가 새 덤프의 값이다.

## R-5. 새 좌표로 복제를 다시 시작한다

목적: 새 스냅샷 이후 변경만 따라간다.

`config.env`의 `GTID_SLAVE_POS`를 새 값으로 바꾸거나 비워서, 방금 적재한 값을 쓰게 한다.

```bash
./07-start-replica.sh
./08-watch-replica.sh
```

통과 기준: [S-6](02-standalone-initial.md#s-6-동기화-확인)과 같다. 그 다음 [증분 컷오버](03-standalone-incremental.md)를 진행한다.
