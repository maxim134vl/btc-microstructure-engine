#!/usr/bin/env bash
# Plane C — Telegram ops sibling (not part of deploy/vps/docker-compose.yml).
# Points at the sibling btc-ml-telegram-bot repo when present.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIBLING_DEFAULT="$(cd "$REPO_ROOT/.." && pwd)/btc-ml-telegram-bot"
TELEGRAM_ROOT="${VPS_TELEGRAM_ROOT:-$SIBLING_DEFAULT}"
COMPOSE_CANDIDATES=(
  "$TELEGRAM_ROOT/services/telegram-ops-bot/docker-compose.yml"
  "$TELEGRAM_ROOT/docker-compose.yml"
  "$TELEGRAM_ROOT/compose.yaml"
)

usage() {
  cat <<'EOF'
Usage: scripts/deploy/vps_telegram.sh <up|down|status|doctor>

Plane C sibling for VPS assembly. Does not start the model stack.
Set VPS_TELEGRAM_ROOT to override the sibling path.
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

find_compose() {
  local c
  for c in "${COMPOSE_CANDIDATES[@]}"; do
    if [[ -f "$c" ]]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

cmd_doctor() {
  echo "TELEGRAM_ROOT=$TELEGRAM_ROOT"
  if compose="$(find_compose)"; then
    echo "COMPOSE=$compose"
    echo "doctor: OK (sibling compose found)"
  else
    echo "doctor: MISSING sibling telegram compose under $TELEGRAM_ROOT"
    echo "Expected one of:"
    printf '  - %s\n' "${COMPOSE_CANDIDATES[@]}"
    exit 1
  fi
}

compose() {
  local file
  file="$(find_compose)" || die "telegram compose not found; run doctor"
  docker compose -f "$file" --project-name "${TELEGRAM_PROJECT:-btcml-telegram}" "$@"
}

main() {
  [[ $# -ge 1 ]] || { usage; exit 2; }
  local cmd="$1"
  shift
  case "$cmd" in
    doctor) cmd_doctor ;;
    up) compose up -d "$@" ;;
    down) compose down "$@" ;;
    status) compose ps "$@" ;;
    -h|--help|help) usage ;;
    *) die "unknown command: $cmd" ;;
  esac
}

main "$@"
