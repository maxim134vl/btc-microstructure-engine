#!/usr/bin/env bash
# =============================================================================
# smoke-test.sh — quick end-to-end probe of the running stack.
# =============================================================================
set -uo pipefail
BASE_URL="${BASE_URL:-http://localhost:8080}"

c_red(){ printf "\033[31m%s\033[0m" "$*"; }
c_grn(){ printf "\033[32m%s\033[0m" "$*"; }
FAILED=0

probe() {
  local label="$1" url="$2" expect="${3:-200}"
  local code
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "$url" || echo 000)"
  if [[ "$code" == "$expect" ]]; then
    printf "  %s %-32s %s\n" "$(c_grn ✓)" "$label" "$code"
  else
    printf "  %s %-32s %s (expected %s)\n" "$(c_red ✗)" "$label" "$code" "$expect"
    FAILED=$((FAILED+1))
  fi
}

echo "==> probing endpoints at $BASE_URL"
probe "health-api /healthz"     "$BASE_URL/healthz"            200
probe "health-api /readyz"      "$BASE_URL/readyz"             200
probe "health-api UI"           "$BASE_URL/"                   200
probe "api/health"              "$BASE_URL/api/health"         200
probe "api/services"            "$BASE_URL/api/services"       200
probe "api/parquets"            "$BASE_URL/api/parquets"       200
probe "api/system"              "$BASE_URL/api/system"         200
probe "api/alerts/active"       "$BASE_URL/api/alerts/active"  200

# direct (dev-only port mappings)
probe "metrics-exporter snap"   "http://localhost:9101/api/snapshot"      200
probe "alert-engine active"     "http://localhost:9102/api/alerts/active" 200
probe "watchdog audit"          "http://localhost:9103/api/audit"         200

echo
if [[ $FAILED -eq 0 ]]; then
  echo "$(c_grn 'all probes passed.')"
  exit 0
fi
echo "$(c_red "$FAILED probe(s) failed.")"
exit 1
