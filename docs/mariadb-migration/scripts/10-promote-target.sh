#!/usr/bin/env bash
# I-4 / GI-5. 지연이 0일 때만 복제를 멈추고 대상을 쓰기 가능으로 연다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_confirm

if [[ -n "${SOURCE_NODES:-}" ]]; then
  prev=""
  while read -r host; do
    committed=$(mariadb --defaults-extra-file="$SOURCE_CNF" --host="$host" --batch --skip-column-names --raw -e "SHOW STATUS LIKE 'wsrep_last_committed'")
    committed=${committed#*$'\t'}
    recv=$(mariadb --defaults-extra-file="$SOURCE_CNF" --host="$host" --batch --skip-column-names --raw -e "SHOW STATUS LIKE 'wsrep_local_recv_queue'")
    send=$(mariadb --defaults-extra-file="$SOURCE_CNF" --host="$host" --batch --skip-column-names --raw -e "SHOW STATUS LIKE 'wsrep_local_send_queue'")
    recv=${recv#*$'\t'}
    send=${send#*$'\t'}
    echo "${host} last_committed=${committed} recv=${recv} send=${send}"
    if [[ "$recv" != "0" || "$send" != "0" ]]; then
      echo "${host} 의 Galera 큐가 비어 있지 않습니다." >&2
      exit 1
    fi
    if [[ -n "$prev" && "$prev" != "$committed" ]]; then
      echo "원본 노드의 wsrep_last_committed 가 다릅니다." >&2
      exit 1
    fi
    prev=$committed
  done < <(source_node_list)
fi

status=$(mariadb_target -E -e "SHOW SLAVE STATUS")
io=$(slave_field "$status" "Slave_IO_Running")
sql=$(slave_field "$status" "Slave_SQL_Running")
lag=$(slave_field "$status" "Seconds_Behind_Master")
err=$(slave_field "$status" "Last_SQL_Error")

echo "Slave_IO_Running=${io:-<empty>}"
echo "Slave_SQL_Running=${sql:-<empty>}"
echo "Seconds_Behind_Master=${lag:-<empty>}"
echo "Last_SQL_Error=${err:-}"

if [[ "$io" != "Yes" || "$sql" != "Yes" || "$lag" != "0" || -n "$err" ]]; then
  echo "복제가 따라잡히지 않았습니다. 승격하지 않습니다." >&2
  exit 1
fi

mariadb_target -e "STOP SLAVE;"
echo "T1(대상 cnf 호스트)의 복제를 멈췄습니다."

if [[ -n "${TARGET_NODES:-}" ]]; then
  while read -r host; do
    echo "======== open ${host} ========"
    mariadb_at "$TARGET_CNF" "$host" -e "SET GLOBAL super_read_only=OFF; SET GLOBAL read_only=OFF; SHOW VARIABLES LIKE 'read_only';"
  done < <(target_node_list)
else
  mariadb_target -e "SET GLOBAL super_read_only=OFF; SET GLOBAL read_only=OFF;"
fi
echo "대상을 열었습니다. 애플리케이션 접속을 바꾼 뒤 12-verify.sh 를 실행하세요."
