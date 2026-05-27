#!/usr/bin/env bash
# =====================================================================
# deploy.sh — build & run the BTC microstructure engine in containers.
#
# Usage:
#   ./deploy.sh build           # build the shared image only
#   ./deploy.sh up              # build (if needed) and start all services
#   ./deploy.sh down            # stop & remove containers (KEEPS data)
#   ./deploy.sh nuke            # stop & remove containers + DELETE volumes
#   ./deploy.sh logs [service]  # tail logs (all or a single service)
#   ./deploy.sh ps              # show service status
#   ./deploy.sh backup [path]   # tar the data volume to path (default ./backups)
#   ./deploy.sh restore <file>  # restore a tarball into the data volume
#
# Volumes:
#   btc_engine_data  -> /data inside containers (all parquet output)
#   btc_engine_logs  -> /logs inside containers
#
# `down` does NOT delete volumes; only `nuke` does.
# =====================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DATA_VOLUME="btc_engine_data"
LOGS_VOLUME="btc_engine_logs"

# pick the right compose CLI (v2 plugin or legacy v1)
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "ERROR: neither 'docker compose' nor 'docker-compose' is available." >&2
    exit 1
fi

cmd="${1:-up}"
shift || true

case "$cmd" in

    build)
        echo ">> building btc-engine image"
        $COMPOSE build
        ;;

    up)
        # Build first so the local btc-engine:latest tag exists before
        # any service is started. Without this, compose may try to pull
        # the image from a registry for services other than the one
        # that owns the `build:` block (in older compose versions).
        echo ">> building btc-engine:latest locally"
        $COMPOSE build
        echo
        echo ">> starting all services"
        $COMPOSE up -d --no-build
        echo
        echo ">> services running:"
        $COMPOSE ps
        echo
        echo ">> dashboard: http://localhost:8501"
        echo ">> data volume: ${DATA_VOLUME} (survives 'down', removed only by 'nuke')"
        ;;

    down)
        echo ">> stopping & removing containers (data volume KEPT)"
        $COMPOSE down
        echo
        echo ">> data still in volume: ${DATA_VOLUME}"
        ;;

    nuke)
        echo ">> WARNING: this will DELETE all parquet data in ${DATA_VOLUME}"
        read -r -p "type 'yes' to confirm: " confirm
        if [ "$confirm" = "yes" ]; then
            $COMPOSE down -v
            echo ">> volumes removed."
        else
            echo ">> aborted."
            exit 1
        fi
        ;;

    logs)
        if [ $# -ge 1 ]; then
            $COMPOSE logs -f --tail=200 "$@"
        else
            $COMPOSE logs -f --tail=100
        fi
        ;;

    ps)
        $COMPOSE ps
        ;;

    backup)
        target_dir="${1:-./backups}"
        mkdir -p "$target_dir"
        stamp="$(date -u +%Y%m%dT%H%M%SZ)"
        out="${target_dir}/${DATA_VOLUME}_${stamp}.tgz"
        echo ">> backing up volume ${DATA_VOLUME} -> ${out}"
        docker run --rm \
            -v "${DATA_VOLUME}:/data:ro" \
            -v "$(cd "$target_dir" && pwd):/backup" \
            alpine \
            tar czf "/backup/$(basename "$out")" -C /data .
        echo ">> done: ${out}"
        ;;

    restore)
        archive="${1:-}"
        if [ -z "$archive" ] || [ ! -f "$archive" ]; then
            echo "ERROR: provide a path to a .tgz produced by 'backup'." >&2
            exit 1
        fi
        echo ">> WARNING: this will overwrite contents of ${DATA_VOLUME}"
        read -r -p "type 'yes' to confirm: " confirm
        [ "$confirm" = "yes" ] || { echo "aborted."; exit 1; }
        abs="$(cd "$(dirname "$archive")" && pwd)/$(basename "$archive")"
        docker run --rm \
            -v "${DATA_VOLUME}:/data" \
            -v "$(dirname "$abs"):/backup:ro" \
            alpine \
            sh -c "cd /data && tar xzf /backup/$(basename "$abs")"
        echo ">> restored."
        ;;

    *)
        echo "Unknown command: $cmd" >&2
        echo "Usage: $0 {build|up|down|nuke|logs|ps|backup|restore}" >&2
        exit 1
        ;;

esac
