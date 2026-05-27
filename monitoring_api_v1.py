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
        "status": "running"
    }

# =====================================
# START
# =====================================

if __name__ == "__main__":

    uvicorn.run(

        app,

        host="0.0.0.0",

        port=8000

    )
