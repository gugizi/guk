#!/usr/bin/env bash
# G-3. S1 에서 물리 백업을 뜬다. 이 스크립트는 백업 대상 서버에서 실행한다.
set -euo pipefail
REQUIRE_CNF=0
source "$(dirname "$0")/lib.sh"

BACKUP_CNF=$(resolve_path "${BACKUP_CNF:-backup.cnf}")
require_file "$BACKUP_CNF"

mkdir -p "$BACKUP_DIR"
if [[ -n "$(ls -A "$BACKUP_DIR" 2>/dev/null || true)" ]]; then
  echo "BACKUP_DIR 이 비어 있지 않습니다: $BACKUP_DIR" >&2
  exit 1
fi

echo "백업 시작: $BACKUP_DIR"
mariabackup --backup --target-dir="$BACKUP_DIR" --defaults-extra-file="$BACKUP_CNF"
mariabackup --prepare --target-dir="$BACKUP_DIR"
echo "======== xtrabackup_binlog_info ========"
cat "$BACKUP_DIR/xtrabackup_binlog_info"
echo
echo "좌표의 세 번째 필드를 config.env 의 GTID_SLAVE_POS 에 넣으세요."
