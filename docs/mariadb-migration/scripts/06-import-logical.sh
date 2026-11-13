#!/usr/bin/env bash
# S-4. 비어 있는 대상에 논리 덤프를 넣는다. 기존 데이터베이스가 있으면 멈추고 초기화 절차를 안내한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_confirm

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "덤프 파일이 없습니다: $DUMP_FILE" >&2
  exit 1
fi

exists=$(mariadb_target_value -e "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='${DB_NAME}'")
if [[ "$exists" != "0" ]]; then
  echo "대상에 ${DB_NAME} 가 이미 있습니다. 11-reset-target-database.sh 로 비운 뒤 다시 실행하세요." >&2
  exit 1
fi

# read_only 는 유지한다. SUPER 관리 계정만 적재하고, 일반 계정은 막힌 상태가 유지된다.
mariadb_target -e "SET GLOBAL super_read_only=OFF; SET GLOBAL read_only=ON;"
echo "적재 시작: ${DUMP_FILE}"
mariadb_target --default-character-set="${CHARSET}" < "${DUMP_FILE}"
echo "적재가 끝났습니다."
mariadb_target_value -e "SELECT @@gtid_slave_pos"
