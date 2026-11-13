#!/usr/bin/env bash
# S-5 / G-6. 대상 한 노드에서만 원본을 따라가는 복제를 시작한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_confirm
reject_quote "REPL_PASSWORD" "${REPL_PASSWORD:-}"

running=$(mariadb_target -E -e "SHOW SLAVE STATUS" | sed -n 's/^[[:space:]]*Slave_IO_Running: //p' | head -n 1 || true)
if [[ "$running" == "Yes" ]]; then
  echo "이미 IO 스레드가 실행 중입니다. 중복 시작을 멈추었습니다." >&2
  exit 1
fi

if [[ -n "${GTID_SLAVE_POS:-}" ]]; then
  if [[ ! "$GTID_SLAVE_POS" =~ ^[0-9]+-[0-9]+-[0-9]+(,[0-9]+-[0-9]+-[0-9]+)*$ ]]; then
    echo "GTID_SLAVE_POS 형식이 아닙니다. 예: 0-1-48231" >&2
    exit 1
  fi
  mariadb_target -e "SET GLOBAL gtid_slave_pos='${GTID_SLAVE_POS}'"
  echo "gtid_slave_pos 를 ${GTID_SLAVE_POS} 로 설정했습니다."
  use_gtid=1
elif [[ -n "${BINLOG_FILE:-}" || -n "${BINLOG_POS:-}" ]]; then
  if [[ ! "${BINLOG_FILE:-}" =~ ^[A-Za-z0-9._-]+$ || ! "${BINLOG_POS:-}" =~ ^[0-9]+$ ]]; then
    echo "BINLOG_FILE 과 BINLOG_POS 를 함께, 샘플 형식으로 설정하세요." >&2
    exit 1
  fi
  use_gtid=0
else
  current=$(mariadb_target_value -e "SELECT @@gtid_slave_pos")
  if [[ -z "$current" ]]; then
    echo "gtid_slave_pos 가 비어 있습니다. 좌표를 config.env 에 넣은 뒤 다시 실행하세요." >&2
    exit 1
  fi
  echo "덤프가 설정한 gtid_slave_pos=${current} 를 사용합니다."
  use_gtid=1
fi

if [[ "$use_gtid" == "1" ]]; then
  mariadb_target <<SQL
CHANGE MASTER TO
  MASTER_HOST='${SOURCE_HOST}',
  MASTER_PORT=${SOURCE_PORT},
  MASTER_USER='${REPL_USER}',
  MASTER_PASSWORD='${REPL_PASSWORD}',
  MASTER_USE_GTID=slave_pos;
START SLAVE;
SQL
else
  mariadb_target <<SQL
CHANGE MASTER TO
  MASTER_HOST='${SOURCE_HOST}',
  MASTER_PORT=${SOURCE_PORT},
  MASTER_USER='${REPL_USER}',
  MASTER_PASSWORD='${REPL_PASSWORD}',
  MASTER_LOG_FILE='${BINLOG_FILE}',
  MASTER_LOG_POS=${BINLOG_POS};
START SLAVE;
SQL
fi

echo "복제를 시작했습니다. 대상 노드 하나에서만 실행해야 합니다. ./08-watch-replica.sh 로 지연을 확인하세요."
