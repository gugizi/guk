#!/usr/bin/env bash
# C-4. 원본과 대상에 접속하고 binlog 사전 조건을 확인한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

report_server() {
  local label=$1
  local runner=$2
  echo "======== $label ========"
  $runner -e "SELECT @@hostname AS hostname, @@port AS port, @@version AS version, @@version_comment AS version_comment;"
  $runner -e "SHOW VARIABLES WHERE Variable_name IN ('server_id','log_bin','binlog_format','log_slave_updates','binlog_expire_logs_seconds','expire_logs_days','read_only','super_read_only','gtid_domain_id','wsrep_on','wsrep_gtid_mode','wsrep_gtid_domain_id','wsrep_sst_method');"
}

report_server "SOURCE" mariadb_source
report_server "TARGET" mariadb_target

log_bin=$(mariadb_source_value -e "SELECT @@log_bin")
fmt=$(mariadb_source_value -e "SELECT @@binlog_format")
if [[ "$log_bin" != "1" ]]; then
  echo "원본 log_bin 이 꺼져 있습니다. 증분 복제를 할 수 없습니다." >&2
  exit 1
fi
if [[ "$fmt" != "ROW" ]]; then
  echo "원본 binlog_format 이 ROW 가 아닙니다. 현재 값: $fmt" >&2
  exit 1
fi

if [[ -n "${SOURCE_NODES:-}" ]]; then
  echo "======== SOURCE NODES ========"
  while read -r host; do
    echo "-- $host"
    mariadb_at "$SOURCE_CNF" "$host" -e "SHOW STATUS WHERE Variable_name IN ('wsrep_cluster_size','wsrep_local_state_comment','wsrep_ready','wsrep_cluster_status','wsrep_last_committed');"
  done < <(source_node_list)
fi

echo "사전 점검이 끝났습니다."
