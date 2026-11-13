#!/usr/bin/env bash
# C-8. 적재와 증분 동안 대상에 애플리케이션 쓰기가 들어가지 않게 한다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_confirm

open_one() {
  local host=$1
  mariadb --defaults-extra-file="$TARGET_CNF" --host="$host" -e "
SET GLOBAL super_read_only=OFF;
SET GLOBAL read_only=ON;
SHOW VARIABLES WHERE Variable_name IN ('read_only','super_read_only');
"
}

if [[ -n "${TARGET_NODES:-}" ]]; then
  while read -r host; do
    echo "======== readonly ${host} ========"
    open_one "$host"
  done < <(target_node_list)
else
  if [[ -z "${TARGET_HOST:-}" ]]; then
    echo "TARGET_HOST 를 설정하세요." >&2
    exit 1
  fi
  open_one "${TARGET_HOST}"
fi
