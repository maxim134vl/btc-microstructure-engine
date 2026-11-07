"""Transport settings. Deliberately independent of pipeline/analytics config."""
import os
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
for p in (REPO_ROOT, REPO_ROOT/"src"):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
POLL_INTERVAL_S = float(os.environ.get("DASHBOARD_POLL_INTERVAL", "2.0"))
API_PREFIX = "/api/v1"
CORS_ORIGINS = [x.strip() for x in os.environ.get("DASHBOARD_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173").split(",") if x.strip()]
HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))
PUBLICATION_ROOT = Path(os.environ.get("OPS_PUBLICATION_ROOT", str(REPO_ROOT/"data/runtime/ops")))
