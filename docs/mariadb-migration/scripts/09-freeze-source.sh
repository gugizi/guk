#!/usr/bin/env bash
# I-2 / GI-3. 원본 쓰기를 멈춘다. Galera면 SOURCE_NODES 전부, 아니면 SOURCE_HOST 한 대.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_confirm

nodes=$(source_node_list)
if [[ -z "$nodes" ]]; then
  echo "SOURCE_HOST 또는 SOURCE_NODES 를 설정하세요." >&2
  exit 1
fi

fail=0
while read -r host; do
  echo "======== freeze ${host} ========"
  mariadb_at "$SOURCE_CNF" "$host" -e "
SET GLOBAL read_only=ON;
SET GLOBAL super_read_only=ON;
SELECT id, user, db, command, time, state, LEFT(IFNULL(info,''), 120) AS info
FROM information_schema.processlist
WHERE id <> CONNECTION_ID()
  AND command <> 'Sleep'
  AND user <> 'system user';
"
  busy=$(mariadb --defaults-extra-file="$SOURCE_CNF" --host="$host" --batch --skip-column-names --raw -e "
SELECT COUNT(*)
FROM information_schema.processlist
WHERE id <> CONNECTION_ID()
  AND command <> 'Sleep'
  AND user <> 'system user';
")
  if [[ "$busy" != "0" ]]; then
    echo "${host} 에 사용자 작업이 ${busy}건 남아 있습니다." >&2
    fail=1
  fi
done <<< "$nodes"

if [[ "$fail" != "0" ]]; then
  echo "컷오버를 진행하지 마세요. 애플리케이션을 멈춘 뒤 이 스크립트를 다시 실행하세요." >&2
  exit 1
fi
echo "원본 쓰기를 멈췄습니다."
