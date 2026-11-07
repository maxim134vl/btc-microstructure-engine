#!/usr/bin/env bash
# One-command VPS full-model deployment operations. Never touches unrelated Docker projects.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${VPS_COMPOSE_FILE:-$REPO_ROOT/deploy/vps/docker-compose.yml}"
ENV_FILE="${VPS_ENV_FILE:-$REPO_ROOT/deploy/vps/.env}"
PROJECT="${COMPOSE_PROJECT_NAME:-btcml-vps}"
VOLUME_NAME="${VPS_VOLUME_NAME:-btc_ml_data_vps}"

REQUIRED_SERVICES=(
  collector-watchdog
  canonical-runtime
  context-refresh-daemon
  cognition-runtime
  paper-manager
  timeframe-manager
  intrabar-supervisor
  trd-outcome2
  ops-api
  dashboard-ui
  context-refresher
  trade-chart
)

usage() {
  cat <<'EOF'
Usage: scripts/deploy/vps_stack.sh <command> [options]

Commands:
  bootstrap   Create isolated paper epoch under the named volume
  build       Build VPS images
  up          Start the FULL model + dashboard stack (no exclude profiles)
  down        Stop the stack (keeps volumes)
  restart     Restart stack services
  status      Compose ps
  health      Show health; fails if any required service is unhealthy
  logs        Tail logs (optional service name)
  smoke       Bounded isolated smoke (project btcml-vps-smoke)
  doctor      Local preflight checks

Environment:
  COMPOSE_PROJECT_NAME   default: btcml-vps
  VPS_VOLUME_NAME        default: btc_ml_data_vps
  VPS_ENV_FILE           default: deploy/vps/.env (falls back to .env.example)
  VPS_COMPOSE_FILE       default: deploy/vps/docker-compose.yml
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

resolve_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    echo "$ENV_FILE"
  elif [[ -f "$REPO_ROOT/deploy/vps/.env.example" ]]; then
    echo "$REPO_ROOT/deploy/vps/.env.example"
  else
    die "missing env file"
  fi
}

compose() {
  local envf
  envf="$(resolve_env_file)"
  docker compose \
    --project-name "$PROJECT" \
    --env-file "$envf" \
    -f "$COMPOSE_FILE" \
    "$@"
}

cmd_doctor() {
  echo "REPO_ROOT=$REPO_ROOT"
  echo "COMPOSE_FILE=$COMPOSE_FILE"
  echo "PROJECT=$PROJECT"
  echo "VOLUME_NAME=$VOLUME_NAME"
  command -v docker >/dev/null || die "docker missing"
  docker compose version >/dev/null || die "docker compose missing"
  python3 --version
  test -f "$COMPOSE_FILE" || die "compose file missing"
  test -f "$REPO_ROOT/scripts/deploy/bootstrap_vps_environment.py" || die "bootstrap script missing"
  test -d "$REPO_ROOT/deploy/vps/entrypoints" || die "entrypoints missing"
  compose config --quiet
  echo "required_services=${#REQUIRED_SERVICES[@]}"
  printf '  - %s\n' "${REQUIRED_SERVICES[@]}"
  # Full model (~17 containers) needs headroom; Desktop/VPS under ~8GiB thrash.
  local mem_gi
  mem_gi="$(
    docker info 2>/dev/null | awk -F': ' '/Total Memory/ {
      v=$2; gsub(/GiB/,"",v); gsub(/ /,"",v); print v; exit
    }'
  )"
  if [[ -n "$mem_gi" ]]; then
    echo "docker_total_memory_gib=$mem_gi"
    python3 - "$mem_gi" <<'PY' || true
import sys
try:
    mem = float(sys.argv[1])
except Exception:
    sys.exit(0)
if mem < 7.5:
    print(
        f"WARNING: Docker memory {mem:.2f} GiB < 8 GiB floor for full-model stack. "
        "Raise Docker Desktop/VPS RAM before `up` or expect ops-api/health thrash.",
        file=sys.stderr,
    )
PY
  fi
  echo "doctor: OK"
}

cmd_bootstrap() {
  compose build cognition-runtime
  VPS_GIT_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)" \
    compose --profile bootstrap run --rm vps-bootstrap
}

cmd_build() {
  compose build
}

cmd_up() {
  compose up -d --remove-orphans
}

cmd_down() {
  compose down --remove-orphans
}

cmd_restart() {
  compose restart
}

cmd_status() {
  compose ps
}

cmd_health() {
  local raw
  raw="$(compose ps --format json 2>/dev/null || true)"
  if [[ -z "$raw" ]]; then
    echo "ERROR: no services running" >&2
    compose ps || true
    return 1
  fi

  python3 - "$raw" "${REQUIRED_SERVICES[@]}" <<'PY'
import json, sys

raw = sys.argv[1]
required = sys.argv[2:]
items = []
try:
    data = json.loads(raw)
    items = data if isinstance(data, list) else [data]
except json.JSONDecodeError:
    for line in raw.splitlines():
        if line.strip():
            items.append(json.loads(line))

by_service = {}
for s in items:
    name = s.get("Service") or s.get("Name") or ""
    # strip project prefix if Name-only
    for key in (s.get("Service"), name.split("-")[-1] if name else None, name):
        if key:
            by_service[key] = s
    svc = s.get("Service")
    if svc:
        by_service[svc] = s

failed = []
print("service\tstate\thealth")
for svc in required:
    row = by_service.get(svc)
    if row is None:
        # fuzzy: Name contains service
        for s in items:
            nm = str(s.get("Service") or s.get("Name") or "")
            if nm == svc or nm.endswith(f"-{svc}") or f"_{svc}" in nm or svc in nm.split():
                row = s
                break
    if row is None:
        print(f"{svc}\tMISSING\t-")
        failed.append(svc)
        continue
    state = row.get("State") or row.get("Status") or "?"
    health = row.get("Health") or ""
    print(f"{svc}\t{state}\t{health or '-'}")
    state_l = str(state).lower()
    health_l = str(health).lower()
    if state_l not in {"running"}:
        failed.append(svc)
    elif health_l and health_l not in {"healthy", "starting", ""}:
        # Docker reports starting during start_period; treat unhealthy as fail
        if health_l == "unhealthy":
            failed.append(svc)

if failed:
    print(f"ERROR: unhealthy_or_missing={','.join(failed)}", file=sys.stderr)
    sys.exit(1)
print("health: OK (all required services present)")
PY
}

cmd_logs() {
  if [[ $# -gt 0 ]]; then
    compose logs -f --tail=200 "$@"
  else
    compose logs -f --tail=100
  fi
}

cmd_smoke() {
  export COMPOSE_PROJECT_NAME=btcml-vps-smoke
  export PROJECT=btcml-vps-smoke
  export VPS_VOLUME_NAME=btc_ml_data_vps_smoke
  export VOLUME_NAME=btc_ml_data_vps_smoke
  export OPS_API_HOST_PORT=18080
  export DASHBOARD_UI_HOST_PORT=15173
  export TRADE_CHART_HOST_PORT=18765
  local smoke_env
  smoke_env="$(mktemp)"
  {
    cat "$(resolve_env_file)"
    echo "COMPOSE_PROJECT_NAME=btcml-vps-smoke"
    echo "VPS_VOLUME_NAME=btc_ml_data_vps_smoke"
    echo "VPS_VISUAL_VOLUME_NAME=btc_ml_visual_public_vps_smoke"
    echo "OPS_API_HOST_PORT=18080"
    echo "DASHBOARD_UI_HOST_PORT=15173"
    echo "TRADE_CHART_HOST_PORT=18765"
  } >"$smoke_env"
  ENV_FILE="$smoke_env"
  echo "smoke: env=$smoke_env project=$PROJECT"
  echo "smoke: bootstrap + up + health (bounded operator run; no long build forced here)"
  cmd_doctor
  cmd_bootstrap
  cmd_up
  # Wait briefly then health
  sleep 20
  local rc=0
  cmd_health || rc=$?
  rm -f "$smoke_env"
  return "$rc"
}

main() {
  [[ $# -ge 1 ]] || { usage; exit 2; }
  local cmd="$1"
  shift
  case "$cmd" in
    bootstrap) cmd_bootstrap "$@" ;;
    build) cmd_build "$@" ;;
    up) cmd_up "$@" ;;
    down) cmd_down "$@" ;;
    restart) cmd_restart "$@" ;;
    status) cmd_status "$@" ;;
    health) cmd_health "$@" ;;
    logs) cmd_logs "$@" ;;
    smoke) cmd_smoke "$@" ;;
    doctor) cmd_doctor "$@" ;;
    -h|--help|help) usage ;;
    *) die "unknown command: $cmd" ;;
  esac
}

main "$@"
