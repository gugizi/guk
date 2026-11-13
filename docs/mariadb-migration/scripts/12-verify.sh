#!/usr/bin/env bash
# V-1. 샘플 테이블의 행 수를 비교하고, 설정 시 체크섬과 Galera 상태를 출력한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

mismatch=0
IFS=',' read -ra tables <<< "${EXACT_COUNT_TABLES:-}"
for raw in "${tables[@]}"; do
  t=${raw// /}
  [[ -z "$t" ]] && continue
  require_ident "table" "$t"
  s=$(mariadb_source_value -e "SELECT COUNT(*) FROM \`${DB_NAME}\`.\`${t}\`")
  d=$(mariadb_target_value -e "SELECT COUNT(*) FROM \`${DB_NAME}\`.\`${t}\`")
  echo "${t} source=${s} target=${d}"
  if [[ "$s" != "$d" ]]; then
    mismatch=1
  fi
  if [[ "${RUN_CHECKSUM:-0}" == "1" ]]; then
    echo "-- source checksum"
    mariadb_source -e "CHECKSUM TABLE \`${DB_NAME}\`.\`${t}\`"
    echo "-- target checksum"
    mariadb_target -e "CHECKSUM TABLE \`${DB_NAME}\`.\`${t}\`"
  fi
done

echo "======== replica ========"
mariadb_target -E -e "SHOW SLAVE STATUS" | sed -n \
  -e 's/^[[:space:]]*Slave_IO_Running: /Slave_IO_Running: /p' \
  -e 's/^[[:space:]]*Slave_SQL_Running: /Slave_SQL_Running: /p' \
  -e 's/^[[:space:]]*Seconds_Behind_Master: /Seconds_Behind_Master: /p' \
  -e 's/^[[:space:]]*Last_SQL_Error: /Last_SQL_Error: /p' \
  || true

if [[ -n "${TARGET_NODES:-}${SOURCE_NODES:-}" ]]; then
  echo "======== galera ========"
  while read -r host; do
    [[ -z "$host" ]] && continue
    echo "-- source ${host}"
    mariadb_at "$SOURCE_CNF" "$host" -e "SHOW STATUS WHERE Variable_name IN ('wsrep_cluster_size','wsrep_local_state_comment','wsrep_ready','wsrep_last_committed','wsrep_local_recv_queue','wsrep_local_send_queue');"
  done < <(source_node_list)
  while read -r host; do
    [[ -z "$host" ]] && continue
    echo "-- target ${host}"
    mariadb_at "$TARGET_CNF" "$host" -e "SHOW STATUS WHERE Variable_name IN ('wsrep_cluster_size','wsrep_local_state_comment','wsrep_ready','wsrep_last_committed','wsrep_local_recv_queue','wsrep_local_send_queue');"
  done < <(target_node_list)
fi

if [[ "$mismatch" != "0" ]]; then
  echo "행 수가 다릅니다." >&2
  exit 1
fi
echo "비교한 테이블의 행 수가 같습니다."
