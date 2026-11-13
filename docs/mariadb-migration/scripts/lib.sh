#!/usr/bin/env bash
# 다른 스크립트에서 source 한다. 직접 실행하지 않는다.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "lib.sh 는 직접 실행하지 않습니다." >&2
  exit 1
fi

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [[ ! -f "$SCRIPT_DIR/config.env" ]]; then
  echo "scripts/config.env 가 없습니다. config.sample.env 를 복사해 값을 채우세요." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$SCRIPT_DIR/config.env"
set +a

resolve_path() {
  local p=$1
  if [[ "$p" = /* ]]; then
    printf '%s\n' "$p"
  else
    printf '%s\n' "$SCRIPT_DIR/$p"
  fi
}

SOURCE_CNF=$(resolve_path "${SOURCE_CNF:-source.cnf}")
TARGET_CNF=$(resolve_path "${TARGET_CNF:-target.cnf}")

require_file() {
  local f=$1
  if [[ ! -f "$f" ]]; then
    echo "파일이 없습니다: $f" >&2
    exit 1
  fi
}

if [[ "${REQUIRE_CNF:-1}" == "1" ]]; then
  require_file "$SOURCE_CNF"
  require_file "$TARGET_CNF"
fi

require_ident() {
  local name=$1 value=$2
  if [[ ! "$value" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "$name 은 영문, 숫자, 밑줄만 사용할 수 있습니다: $value" >&2
    exit 1
  fi
}

require_ident "DB_NAME" "${DB_NAME:-}"
require_ident "REPL_USER" "${REPL_USER:-}"
require_ident "DUMP_USER" "${DUMP_USER:-}"

reject_quote() {
  local name=$1 value=$2
  if [[ "$value" == *"'"* ]]; then
    echo "$name 에 작은따옴표를 넣지 마세요." >&2
    exit 1
  fi
}

require_confirm() {
  if [[ "${CONFIRM:-}" != "YES" ]]; then
    echo "데이터를 바꾸기 전에 scripts/config.env 의 CONFIRM 값을 YES 로 설정하세요." >&2
    exit 1
  fi
}

mariadb_source() {
  mariadb --defaults-extra-file="$SOURCE_CNF" "$@"
}

mariadb_target() {
  mariadb --defaults-extra-file="$TARGET_CNF" "$@"
}

mariadb_source_value() {
  mariadb --defaults-extra-file="$SOURCE_CNF" --batch --skip-column-names --raw "$@"
}

mariadb_target_value() {
  mariadb --defaults-extra-file="$TARGET_CNF" --batch --skip-column-names --raw "$@"
}

mariadb_at() {
  local cnf=$1 host=$2
  shift 2
  mariadb --defaults-extra-file="$cnf" --host="$host" "$@"
}

# SOURCE_NODES 가 비어 있으면 SOURCE_HOST 한 대만 사용한다.
source_node_list() {
  local csv=${SOURCE_NODES:-${SOURCE_HOST:-}}
  local IFS=','
  local n
  for n in $csv; do
    n=${n// /}
    [[ -n "$n" ]] && printf '%s\n' "$n"
  done
}

target_node_list() {
  local csv=${TARGET_NODES:-}
  local IFS=','
  local n
  if [[ -z "$csv" ]]; then
    return 0
  fi
  for n in $csv; do
    n=${n// /}
    [[ -n "$n" ]] && printf '%s\n' "$n"
  done
}

slave_field() {
  local status=$1 key=$2
  printf '%s\n' "$status" | sed -n "s/^[[:space:]]*${key}: //p" | head -n 1
}
