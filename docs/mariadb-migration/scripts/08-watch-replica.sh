#!/usr/bin/env bash
# I-1. 복제 지연을 일정 횟수 출력한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

count=${WATCH_COUNT:-12}
interval=${WATCH_INTERVAL:-5}
i=1
while [[ "$i" -le "$count" ]]; do
  echo "-------- sample ${i}/${count} --------"
  status=$(mariadb_target -E -e "SHOW SLAVE STATUS")
  printf '%s\n' "$status" | sed -n \
    -e 's/^[[:space:]]*Slave_IO_Running: /Slave_IO_Running: /p' \
    -e 's/^[[:space:]]*Slave_SQL_Running: /Slave_SQL_Running: /p' \
    -e 's/^[[:space:]]*Seconds_Behind_Master: /Seconds_Behind_Master: /p' \
    -e 's/^[[:space:]]*Last_IO_Error: /Last_IO_Error: /p' \
    -e 's/^[[:space:]]*Last_SQL_Error: /Last_SQL_Error: /p' \
    -e 's/^[[:space:]]*Gtid_IO_Pos: /Gtid_IO_Pos: /p'
  i=$((i + 1))
  if [[ "$i" -le "$count" ]]; then
    sleep "$interval"
  fi
done
