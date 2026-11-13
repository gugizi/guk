#!/usr/bin/env bash
# R-1, R-3 / GR-1, GR-2A. 대상 복제를 해제하고 해당 데이터베이스만 삭제한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_confirm

echo "대상 ${DB_NAME} 를 삭제합니다. 호스트는 target.cnf 기준입니다."
mariadb_target -e "SET GLOBAL super_read_only=OFF; SET GLOBAL read_only=ON;"
has_slave=$(mariadb_target -E -e "SHOW SLAVE STATUS" | sed -n 's/^[[:space:]]*Slave_IO_Running: //p' | head -n 1 || true)
if [[ -n "$has_slave" ]]; then
  mariadb_target -e "STOP SLAVE; RESET SLAVE ALL;"
  echo "복제 정보를 제거했습니다."
else
  echo "설정된 복제가 없어 STOP SLAVE 는 건너뜁니다."
fi

mariadb_target -e "DROP DATABASE IF EXISTS \`${DB_NAME}\`;"
echo "DROP DATABASE ${DB_NAME} 를 실행했습니다."

if [[ -n "${TARGET_NODES:-}" ]]; then
  while read -r host; do
    left=$(mariadb --defaults-extra-file="$TARGET_CNF" --host="$host" --batch --skip-column-names --raw -e "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='${DB_NAME}'")
    echo "${host} schema_count=${left}"
    if [[ "$left" != "0" ]]; then
      echo "${host} 에 ${DB_NAME} 가 남아 있습니다. replicate-do-db 필터를 확인하세요." >&2
      exit 1
    fi
  done < <(target_node_list)
fi
