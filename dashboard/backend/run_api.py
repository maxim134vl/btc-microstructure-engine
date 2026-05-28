#!/usr/bin/env python3
"""Launch runtime operations monitor API."""

from __future__ import annotations

import os
import sys

import uvicorn

from app.config import HOST, PORT, REPO_ROOT
from app.main import app, log_registered_routes

if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    log_registered_routes(app)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
