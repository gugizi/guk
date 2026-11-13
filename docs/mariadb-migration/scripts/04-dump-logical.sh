#!/usr/bin/env bash
# S-1 / 논리 덤프. 작업 호스트에서 원본으로 접속해 실행한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

DUMP_CNF=$(resolve_path "${DUMP_CNF:-dump.cnf}")
require_file "$DUMP_CNF"

mkdir -p "$(dirname "$DUMP_FILE")"
echo "덤프 시작: ${DUMP_FILE}"
mariadb-dump \
  --defaults-extra-file="$DUMP_CNF" \
  --single-transaction \
  --master-data=2 \
  --gtid \
  --routines --triggers --events \
  --hex-blob \
  --default-character-set="${CHARSET}" \
  --databases "${DB_NAME}" \
  > "${DUMP_FILE}"
echo "덤프 완료: $(wc -c < "${DUMP_FILE}") bytes"
