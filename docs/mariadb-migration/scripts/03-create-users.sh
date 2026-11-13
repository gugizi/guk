#!/usr/bin/env bash
# C-7. 원본에 덤프 계정, 복제 계정, 로컬 백업 계정을 만든다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

reject_quote "DUMP_PASSWORD" "${DUMP_PASSWORD:-}"
reject_quote "REPL_PASSWORD" "${REPL_PASSWORD:-}"
reject_quote "BACKUP_PASSWORD" "${BACKUP_PASSWORD:-}"

if [[ ! "${REPL_HOST:-%}" =~ ^[A-Za-z0-9_.:%-]+$ ]]; then
  echo "REPL_HOST 형식이 올바르지 않습니다." >&2
  exit 1
fi

require_confirm

mariadb_source <<SQL
CREATE USER IF NOT EXISTS '${DUMP_USER}'@'%' IDENTIFIED BY '${DUMP_PASSWORD}';
ALTER USER '${DUMP_USER}'@'%' IDENTIFIED BY '${DUMP_PASSWORD}';
GRANT SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT, RELOAD, REPLICATION CLIENT
  ON *.* TO '${DUMP_USER}'@'%';

CREATE USER IF NOT EXISTS '${REPL_USER}'@'${REPL_HOST}' IDENTIFIED BY '${REPL_PASSWORD}';
ALTER USER '${REPL_USER}'@'${REPL_HOST}' IDENTIFIED BY '${REPL_PASSWORD}';
GRANT REPLICATION SLAVE ON *.* TO '${REPL_USER}'@'${REPL_HOST}';

CREATE USER IF NOT EXISTS '${BACKUP_USER}'@'localhost' IDENTIFIED BY '${BACKUP_PASSWORD}';
ALTER USER '${BACKUP_USER}'@'localhost' IDENTIFIED BY '${BACKUP_PASSWORD}';
GRANT RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT
  ON *.* TO '${BACKUP_USER}'@'localhost';
SQL

echo "계정을 만들었습니다. dump.cnf, 복제 비밀번호, backup.cnf 가 같은 값인지 확인하세요."
mariadb_source -e "SHOW GRANTS FOR '${DUMP_USER}'@'%'; SHOW GRANTS FOR '${REPL_USER}'@'${REPL_HOST}';"
