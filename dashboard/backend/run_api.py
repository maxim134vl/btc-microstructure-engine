from __future__ import annotations

# OPS_JSON_NAN_SAFE_PATCH
# Prevent dashboard API from crashing when runtime snapshots contain NaN/Infinity.
import json as _ops_json
import math as _ops_math
from starlette.responses import JSONResponse as _OpsJSONResponse

def _ops_json_safe_value(value):
    if isinstance(value, float):
        if _ops_math.isnan(value) or _ops_math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(k): _ops_json_safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_ops_json_safe_value(v) for v in value]
    return value

def _ops_json_response_render(self, content):
    return _ops_json.dumps(
        _ops_json_safe_value(content),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")

_OpsJSONResponse.render = _ops_json_response_render
# /OPS_JSON_NAN_SAFE_PATCH

#!/usr/bin/env python3
"""Launch runtime operations monitor API."""


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
