#!/usr/bin/env bash
# GR-2B. T2, T3 에서만 실행한다. grastate.dat 를 치워 SST 를 받게 한다.
set -euo pipefail
REQUIRE_CNF=0
source "$(dirname "$0")/lib.sh"
require_confirm

if [[ "${NODE_ROLE:-}" != "joiner" ]]; then
  echo "NODE_ROLE=joiner 인 노드에서만 실행합니다. 부트스트랩한 T1 에서는 실행하지 마세요." >&2
  exit 1
fi

grastate="${DATADIR%/}/grastate.dat"
if systemctl is-active --quiet mariadb; then
  systemctl stop mariadb
fi

if [[ -f "$grastate" ]]; then
  mv "$grastate" "${grastate}.bak.$(date +%Y%m%d%H%M%S)"
  echo "grastate.dat 를 옮겼습니다."
else
  echo "grastate.dat 가 없습니다. 기동 시 SST 를 요청합니다."
fi

systemctl start mariadb
echo "기동했습니다. 저널에서 SST 완료를 확인하세요: journalctl -u mariadb -n 50"
