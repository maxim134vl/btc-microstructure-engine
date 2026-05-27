#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Build linux/amd64 images for the full BTC stack (engine + observability),
# tag them for the private Fonte registry, and push.
#
# Versioning:
#   * The "current" version lives in monitoring/VERSION (semver MAJOR.MINOR.PATCH).
#   * By default each invocation bumps PATCH, writes the new version back to
#     the file, and uses it as the tag.
#   * BUMP=minor / BUMP=major bumps the other components instead.
#   * TAG=1.5.7 forces an explicit tag and skips the file bump entirely
#     (useful for hotfixes / re-pushing an old version).
#
# Examples:
#   ./scripts/build-and-push.sh                     # 1.0.0 -> 1.0.1, push
#   BUMP=minor ./scripts/build-and-push.sh          # 1.0.4 -> 1.1.0, push
#   BUMP=major ./scripts/build-and-push.sh          # 1.7.2 -> 2.0.0, push
#   TAG=1.0.7  ./scripts/build-and-push.sh          # push 1.0.7 verbatim
#   ONLY=btc-health-api ./scripts/build-and-push.sh # push just one image
# -----------------------------------------------------------------------------

set -euo pipefail

REGISTRY="${REGISTRY:-registry.fonte.kaz}"
PLATFORM="${PLATFORM:-linux/amd64}"
BUMP="${BUMP:-patch}"
ONLY="${ONLY:-}"

# Resolve paths.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MON_DIR="$( cd "${SCRIPT_DIR}/.." && pwd )"
REPO_ROOT="$( cd "${MON_DIR}/.." && pwd )"
VERSION_FILE="${MON_DIR}/VERSION"

# -----------------------------------------------------------------------------
# Resolve the tag.
# -----------------------------------------------------------------------------
TAG="${TAG:-}"
if [[ -z "${TAG}" ]]; then
    if [[ ! -f "${VERSION_FILE}" ]]; then
        echo "1.0.0" > "${VERSION_FILE}"
    fi
    current="$(tr -d '[:space:]' < "${VERSION_FILE}")"
    if [[ ! "${current}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "ERROR: ${VERSION_FILE} is not semver: ${current}" >&2
        exit 1
    fi
    IFS='.' read -r major minor patch <<<"${current}"
    case "${BUMP}" in
        patch) patch=$((patch + 1)) ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        major) major=$((major + 1)); minor=0; patch=0 ;;
        *) echo "ERROR: BUMP must be patch|minor|major (got '${BUMP}')" >&2; exit 1 ;;
    esac
    TAG="${major}.${minor}.${patch}"
    echo ">>> auto-bump (${BUMP}): ${current} → ${TAG}"
    PERSIST_VERSION=1
else
    # validate forced tag too
    if [[ ! "${TAG}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "WARN: TAG '${TAG}' is not semver — using verbatim, not persisting" >&2
    fi
    echo ">>> explicit TAG=${TAG} (VERSION file untouched)"
    PERSIST_VERSION=0
fi

cd "${REPO_ROOT}"

# Format: "<image_name>:<build_context>"  (contexts relative to REPO_ROOT)
SERVICES=(
  "btc-engine:."
  "btc-metrics-exporter:monitoring/services/metrics-exporter"
  "btc-alert-engine:monitoring/services/alert-engine"
  "btc-watchdog:monitoring/services/watchdog"
  "btc-health-api:monitoring/services/health-api"
)

echo ">>> login to ${REGISTRY}"
docker login "http://${REGISTRY}"

pushed=0
for svc in "${SERVICES[@]}"; do
    name="${svc%%:*}"
    ctx="${svc#*:}"

    if [[ -n "${ONLY}" && "${ONLY}" != "${name}" ]]; then
        continue
    fi

    echo
    echo "=========================================================="
    echo ">>> build  ${name}:${TAG}  (context=${ctx}, platform=${PLATFORM})"
    docker build --platform="${PLATFORM}" -t "${name}:${TAG}" "${ctx}"

    echo ">>> tag    ${REGISTRY}/${name}:${TAG}"
    docker tag "${name}:${TAG}" "${REGISTRY}/${name}:${TAG}"

    echo ">>> push   ${REGISTRY}/${name}:${TAG}"
    docker push "${REGISTRY}/${name}:${TAG}"

    pushed=$((pushed + 1))
done

echo
if [[ ${pushed} -eq 0 ]]; then
    echo ">>> WARN: ONLY=${ONLY} matched nothing"
    exit 1
fi

# Persist the new VERSION only when (a) we bumped it and (b) ALL images were
# pushed in this invocation (partial pushes via ONLY=... don't bump the file).
if [[ "${PERSIST_VERSION}" -eq 1 && -z "${ONLY}" ]]; then
    echo "${TAG}" > "${VERSION_FILE}"
    echo ">>> wrote ${VERSION_FILE} = ${TAG}"
elif [[ "${PERSIST_VERSION}" -eq 1 && -n "${ONLY}" ]]; then
    echo ">>> NOTE: ONLY=${ONLY} pushed; ${VERSION_FILE} NOT updated (partial publish)"
fi

echo ">>> done: pushed ${pushed} image(s) at tag ${TAG} to ${REGISTRY}"
