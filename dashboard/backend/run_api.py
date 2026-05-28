#!/usr/bin/env python3
"""Launch cognition control center API."""

from __future__ import annotations

import os

import uvicorn

from app.config import HOST, PORT, REPO_ROOT
from app.main import app

if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
