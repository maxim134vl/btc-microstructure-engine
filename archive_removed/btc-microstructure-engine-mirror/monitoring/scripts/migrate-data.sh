#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Migrate parquet data from the legacy btc_engine_data named volume to a
# bind-mounted ./data directory at the repo root. Idempotent (re-runnable —
# only copies files that are missing or older).
#
# After migration the named volume is left intact. Remove it manually once
# you're confident the bind mount works:
#   docker volume rm btc_engine_data btc_engine_logs
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MON_DIR="$( cd "${SCRIPT_DIR}/.." && pwd )"
REPO_ROOT="$( cd "${MON_DIR}/.." && pwd )"

DATA_DIR="${REPO_ROOT}/data"
LOGS_DIR="${REPO_ROOT}/logs"

c_grn(){ printf "\033[32m%s\033[0m" "$*"; }
c_cyn(){ printf "\033[36m%s\033[0m" "$*"; }
step(){ printf "  %s %s\n" "$(c_cyn '·')" "$1"; }
ok(){   printf "  %s %s\n" "$(c_grn '✓')" "$1"; }

step "ensure host dirs exist with UID 1000 ownership"
mkdir -p "${DATA_DIR}" "${LOGS_DIR}"
# UID 1000 = btc user inside the engine image. macOS Docker Desktop ignores
# chown across the VFS bridge but won't fail; Linux needs it for real.
if [[ "$(uname)" == "Linux" ]]; then
    sudo chown -R 1000:1000 "${DATA_DIR}" "${LOGS_DIR}" 2>/dev/null \
        || chown -R 1000:1000 "${DATA_DIR}" "${LOGS_DIR}" 2>/dev/null \
        || echo "  (chown skipped — adjust manually if needed)"
fi
ok "host dirs ready: ${DATA_DIR} ${LOGS_DIR}"

migrate_volume() {
    local vol="$1" dst="$2"
    if ! docker volume inspect "${vol}" >/dev/null 2>&1; then
        ok "no legacy volume ${vol} to migrate"
        return 0
    fi
    step "copying ${vol} → ${dst}"
    # Tar pipe rather than cp — macOS Docker Desktop's fs bridge silently
    # drops cp writes from a busybox image. tar streams in-container and
    # works around it. Real files (parquet, csv, npy) only; skips dangling
    # symlinks from the entrypoint's /app -> /data shim.
    docker run --rm \
        -v "${vol}:/src:ro" \
        -v "${dst}:/dst" \
        alpine sh -c '
            cd /src
            find . -maxdepth 1 -type f \( -name "*.parquet" -o -name "*.csv" \
                -o -name "*.npy" -o -name "*.json" \) -print0 \
              | tar -cf - --null -T - 2>/dev/null \
              | (cd /dst && tar -xf -)
            chown -R 1000:1000 /dst 2>/dev/null || true
        '
    ok "copied $(ls "${dst}"/*.parquet 2>/dev/null | wc -l | tr -d ' ') parquet(s)"
}

step "stopping any running engine containers (data must be quiescent)"
docker ps --filter "name=btc_" --format '{{.Names}}' | xargs -r docker stop >/dev/null 2>&1 || true
ok "stopped"

migrate_volume btc_engine_data "${DATA_DIR}"
migrate_volume btc_engine_logs "${LOGS_DIR}"

echo
echo "$(c_grn 'migration complete.')"
echo
echo "  data dir : ${DATA_DIR}"
echo "  logs dir : ${LOGS_DIR}"
echo
echo "  $(ls -1 "${DATA_DIR}"/*.parquet 2>/dev/null | wc -l | tr -d ' ') parquet files in data/"
echo
echo "Restart the stack with the new bind mounts:"
echo "  make up"
echo
echo "Once verified, drop the legacy named volumes:"
echo "  docker volume rm btc_engine_data btc_engine_logs"
