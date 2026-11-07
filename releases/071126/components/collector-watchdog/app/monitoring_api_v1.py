from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import pandas as pd
import uvicorn

app = FastAPI()

# =====================================
# CORS
# =====================================

app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"]

)

# =====================================
# RUNTIME STATUS
# =====================================

@app.get("/runtime")

def runtime_status():

    try:

        df = pd.read_parquet(
            "runtime_engine_state.parquet"
        )

        return (
            df.tail(25)
            .to_dict(
                orient="records"
            )
        )

    except Exception as e:

        return {
            "error": str(e)
        }

# =====================================
# DEPENDENCY STATUS
# =====================================

@app.get("/dependencies")

def dependency_status():

    try:

        df = pd.read_parquet(
            "runtime_dependency_state.parquet"
        )

        return (
            df.tail(25)
            .to_dict(
                orient="records"
            )
        )

    except Exception as e:

        return {
            "error": str(e)
        }

# =====================================
# HEALTH
# =====================================

@app.get("/health")

def health():

    return {
        "status": "running",
        "deprecated": True,
        "use": "dashboard/backend/run_api.py",
    }


def _mount_ops_routes() -> None:
    """Forward-compat ops routes when legacy entrypoint is used by mistake."""

    import os
    import sys

    root = os.path.dirname(os.path.abspath(__file__))
    backend = os.path.join(root, "dashboard", "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from app.services.ops_monitor import build_ops_snapshot
    except Exception:
        return

    @app.get("/api/v1/ops/snapshot")
    async def ops_snapshot():
        return await build_ops_snapshot()

    @app.get("/api/v1/snapshot")
    async def snapshot_alias():
        return await build_ops_snapshot()


_mount_ops_routes()

# =====================================
# START
# =====================================

if __name__ == "__main__":

    uvicorn.run(

        app,

        host="0.0.0.0",

        port=8000

    )
