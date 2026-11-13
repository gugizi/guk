#!/usr/bin/env bash
# 컷오버 이후 애플리케이션을 원본으로 되돌릴 때. 대상은 읽기 전용으로 두고 원본 쓰기만 연다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_confirm

freeze_target() {
  local host=$1
  mariadb --defaults-extra-file="$TARGET_CNF" --host="$host" -e "SET GLOBAL read_only=ON; SET GLOBAL super_read_only=ON;"
  echo "대상 ${host} 를 읽기 전용으로 두었습니다."
}

if [[ -n "${TARGET_NODES:-}" ]]; then
  while read -r host; do
    freeze_target "$host"
  done < <(target_node_list)
else
  if [[ -z "${TARGET_HOST:-}" ]]; then
    echo "TARGET_HOST 를 설정하세요." >&2
    exit 1
  fi
  freeze_target "$TARGET_HOST"
fi

nodes=$(source_node_list)
if [[ -z "$nodes" ]]; then
  echo "SOURCE_HOST 또는 SOURCE_NODES 를 설정하세요." >&2
  exit 1
fi

while read -r host; do
  echo "======== open source ${host} ========"
  mariadb_at "$SOURCE_CNF" "$host" -e "SET GLOBAL super_read_only=OFF; SET GLOBAL read_only=OFF; SHOW VARIABLES LIKE 'read_only';"
done <<< "$nodes"

echo "원본 쓰기를 열었습니다. 애플리케이션 접속을 원본으로 되돌리세요."
