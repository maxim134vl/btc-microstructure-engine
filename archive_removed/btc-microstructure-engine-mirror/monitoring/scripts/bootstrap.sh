#!/usr/bin/env bash
# =============================================================================
# bootstrap.sh — first-time setup. Idempotent.
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MON_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$MON_DIR"

c_red(){ printf "\033[31m%s\033[0m" "$*"; }
c_grn(){ printf "\033[32m%s\033[0m" "$*"; }
c_cyn(){ printf "\033[36m%s\033[0m" "$*"; }
step(){ printf "  %s %s\n" "$(c_cyn '·')" "$1"; }
ok(){   printf "  %s %s\n" "$(c_grn '✓')" "$1"; }
die(){  printf "  %s %s\n" "$(c_red '✗')" "$1" >&2; exit 1; }

step "checking docker"
command -v docker >/dev/null 2>&1 || die "docker not installed"
docker info >/dev/null 2>&1 || die "docker daemon not running"
ok "docker"

step "checking docker compose v2"
docker compose version >/dev/null 2>&1 || die "docker compose v2 required"
ok "compose"

if [[ ! -f .env ]]; then
  step "materializing .env from .env.example"
  cp .env.example .env
  chmod 600 .env
  ok ".env created (chmod 600)"
else
  ok ".env present"
fi

ensure_vol() {
  if docker volume inspect "$1" >/dev/null 2>&1; then
    ok "volume $1 exists"
  else
    step "creating volume $1"
    docker volume create "$1" >/dev/null
    ok "volume $1 created"
  fi
}
ensure_vol btc_engine_data
ensure_vol btc_engine_logs
ensure_vol btc_obs_redis

cat <<EOF

$(c_grn 'bootstrap complete.')

Next:
  1. make build
  2. make up
  3. open http://localhost:8080
EOF
