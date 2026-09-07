#!/bin/sh
# Usage: check_http.sh URL
set -eu
URL="${1:?url required}"
curl -fsS --max-time 5 "$URL" >/dev/null
