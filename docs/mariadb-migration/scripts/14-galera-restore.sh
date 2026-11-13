#!/usr/bin/env bash
# G-5. T1 에서만 실행한다. mariadb 가 중지된 상태에서 데이터 디렉터리를 백업본으로 바꾼다.
set -euo pipefail
REQUIRE_CNF=0
source "$(dirname "$0")/lib.sh"
require_confirm

if [[ "${CONFIRM_DATADIR:-}" != "YES" ]]; then
  echo "데이터 디렉터리 전체를 교체합니다. CONFIRM_DATADIR=YES 를 설정하세요." >&2
  exit 1
fi

case "$DATADIR" in
  /|/root|/home|/usr|/var|/var/lib|"")
    echo "DATADIR 값이 위험합니다: $DATADIR" >&2
    exit 1
    ;;
esac

if [[ ! -f "$BACKUP_DIR/xtrabackup_binlog_info" ]]; then
  echo "준비된 백업이 없습니다: $BACKUP_DIR" >&2
  exit 1
fi

if systemctl is-active --quiet mariadb; then
  echo "mariadb 가 실행 중입니다. systemctl stop mariadb 후 다시 실행하세요." >&2
  exit 1
fi

stamp=$(date +%Y%m%d%H%M%S)
echo "기존 데이터 디렉터리를 ${DATADIR}.bak.${stamp} 로 옮깁니다."
mv "$DATADIR" "${DATADIR}.bak.${stamp}"
mkdir -p "$DATADIR"
mariabackup --copy-back --target-dir="$BACKUP_DIR" --datadir="$DATADIR"
chown -R mysql:mysql "$DATADIR"
echo "복원이 끝났습니다. 이 노드에서만 다음을 실행하세요: galera_new_cluster"
echo "좌표:"
cat "$BACKUP_DIR/xtrabackup_binlog_info"
echo
