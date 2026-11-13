#!/usr/bin/env bash
# S-2. 덤프 헤더에서 복제 시작 좌표를 출력한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "덤프 파일이 없습니다: $DUMP_FILE" >&2
  exit 1
fi

echo "======== GTID ========"
grep -n "gtid_slave_pos" "$DUMP_FILE" | head -n 5 || true
echo "======== BINLOG ========"
grep -n "CHANGE MASTER TO" "$DUMP_FILE" | head -n 5 || true

if ! grep -q "gtid_slave_pos" "$DUMP_FILE" && ! grep -q "CHANGE MASTER TO" "$DUMP_FILE"; then
  echo "좌표가 없습니다. --master-data=2 --gtid 로 다시 덤프하세요." >&2
  exit 1
fi
