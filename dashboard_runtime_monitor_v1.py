import os
import time
from datetime import datetime

import pandas as pd
import psutil
import streamlit as st

# =========================================
# CONFIG
# =========================================

STALE_MINUTES = 10

PARQUET_FILES = [

    "btc_15m.parquet",
    "orderbook.parquet",
    "liquidations.parquet",
    "regime_history.parquet",
    "market_context_memory.parquet",
    "initiative_memory.parquet",
    "event_chains_memory.parquet"

]

# =========================================
# PAGE
# =========================================

st.set_page_config(
    page_title="BTC Runtime Monitor",
    layout="wide"
)

st.title("BTC Microstructure Engine")
st.subheader("Runtime Monitoring Dashboard")

# =========================================
# SYSTEM HEALTH
# =========================================

st.header("System Health")

cpu = psutil.cpu_percent()

ram = psutil.virtual_memory()

disk = psutil.disk_usage("/")

col1, col2, col3 = st.columns(3)

col1.metric(
    "CPU %",
    f"{cpu}%"
)

col2.metric(
    "RAM %",
    f"{ram.percent}%"
)

col3.metric(
    "Disk %",
    f"{disk.percent}%"
)

# =========================================
# PARQUET STATUS
# =========================================

st.header("Parquet Status")

status_rows = []

now = time.time()

for file in PARQUET_FILES:

    if os.path.exists(file):

        modified = os.path.getmtime(file)

        age_minutes = (now - modified) / 60

        size_mb = os.path.getsize(file) / 1024 / 1024

        if age_minutes > STALE_MINUTES:
            status = "STALE"
        else:
            status = "RUNNING"

        status_rows.append({

            "file": file,
            "status": status,
            "last_update_minutes_ago": round(
                age_minutes,
                2
            ),
            "size_mb": round(
                size_mb,
                2
            )

        })

    else:

        status_rows.append({

            "file": file,
            "status": "MISSING",
            "last_update_minutes_ago": None,
            "size_mb": None

        })

df = pd.DataFrame(status_rows)

st.dataframe(
    df,
    use_container_width=True
)

# =========================================
# ALERTS
# =========================================

st.header("Critical Alerts")

alerts = []

for row in status_rows:

    if row["status"] == "MISSING":

        alerts.append(
            f"MISSING FILE: {row['file']}"
        )

    elif row["status"] == "STALE":

        alerts.append(
            f"STALE FILE: {row['file']}"
        )

    if row["size_mb"]:

        if row["size_mb"] > 1000:

            alerts.append(
                f"LARGE FILE > 1GB: {row['file']}"
            )

if len(alerts) == 0:

    st.success(
        "No critical alerts"
    )

else:

    for alert in alerts:

        st.error(alert)

# =========================================
# FOOTER
# =========================================

st.caption(
    f"Last refresh: {datetime.now()}"
)
