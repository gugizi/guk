#!/usr/bin/env bash
# C-5. 이관 대상 데이터베이스의 엔진, 크기, 루틴 수를 출력한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

echo "======== SOURCE ${DB_NAME} ========"
mariadb_source -e "
SELECT ENGINE, COUNT(*) AS tables_count
FROM information_schema.tables
WHERE table_schema='${DB_NAME}' AND table_type='BASE TABLE'
GROUP BY ENGINE;
SELECT table_name,
       table_rows,
       ROUND((data_length+index_length)/1024/1024, 1) AS size_mb
FROM information_schema.tables
WHERE table_schema='${DB_NAME}' AND table_type='BASE TABLE'
ORDER BY data_length+index_length DESC;
SELECT
  (SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema='${DB_NAME}') AS routines,
  (SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema='${DB_NAME}') AS triggers,
  (SELECT COUNT(*) FROM information_schema.events WHERE event_schema='${DB_NAME}') AS events;
"

engines=$(mariadb_source_value -e "
SELECT GROUP_CONCAT(DISTINCT ENGINE)
FROM information_schema.tables
WHERE table_schema='${DB_NAME}' AND table_type='BASE TABLE';
")
echo "엔진: ${engines:-없음}"
if [[ -n "$engines" && "$engines" != "InnoDB" ]]; then
  echo "InnoDB 이외 엔진이 있습니다. 단일 인스턴스 덤프는 --lock-all-tables 검토가 필요하고, Galera 는 InnoDB 만 안정적으로 복제합니다." >&2
fi
