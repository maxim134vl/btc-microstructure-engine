import os
import time
from datetime import datetime

import pandas as pd
import psutil
import streamlit as st

# =========================================
# CONFIG
# =========================================

STALE_MINUTES = 15

REFRESH_SECONDS = 10

PARQUET_FILES = [

    "btc_15m.parquet",
    "orderbook.parquet",
    "regime_history.parquet",
    "market_context_memory.parquet",
    "initiative_memory.parquet",
    "event_chains_memory.parquet",
    "volume_events.parquet",
    "market_events.parquet",
    "acceptance_states.parquet"

]

# =========================================
# PAGE CONFIG
# =========================================

st.set_page_config(
    page_title="BTC Runtime Monitor",
    layout="wide"
)

st.title("BTC Microstructure Engine")
st.subheader("Operational Monitoring Dashboard")

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
    round(cpu, 2)
)

col2.metric(
    "RAM %",
    round(ram.percent, 2)
)

col3.metric(
    "Disk %",
    round(disk.percent, 2)
)

# =========================================
# PARQUET STATUS
# =========================================

st.header("Pipeline / Dataset Status")

status_rows = []

alerts = []

now = time.time()

for file in PARQUET_FILES:

    row = {

        "file": file,
        "status": "UNKNOWN",
        "last_update_minutes": None,
        "size_mb": None,
        "rows": None,
        "columns": None,
        "nan_count": None

    }

    if not os.path.exists(file):

        row["status"] = "MISSING"

        alerts.append(
            f"MISSING DATASET: {file}"
        )

        status_rows.append(row)

        continue

    try:

        modified = os.path.getmtime(file)

        age_minutes = (
            now - modified
        ) / 60

        size_mb = (
            os.path.getsize(file)
            / 1024
            / 1024
        )

        row["last_update_minutes"] = round(
            age_minutes,
            2
        )

        row["size_mb"] = round(
            size_mb,
            2
        )

        if age_minutes > STALE_MINUTES:

            row["status"] = "STALE"

            alerts.append(
                f"STALE DATASET: {file}"
            )

        else:

            row["status"] = "RUNNING"

        # ==============================
        # LIGHTWEIGHT DATA VALIDATION
        # ==============================

        df = pd.read_parquet(file)

        row["rows"] = len(df)

        row["columns"] = len(df.columns)

        nan_count = int(
            df.isna().sum().sum()
        )

        row["nan_count"] = nan_count

        if len(df) == 0:

            alerts.append(
                f"EMPTY DATAFRAME: {file}"
            )

        if nan_count > 0:

            alerts.append(
                f"NAN DETECTED: {file}"
            )

        if size_mb > 1000:

            alerts.append(
                f"LARGE FILE > 1GB: {file}"
            )

    except Exception as e:

        row["status"] = "CORRUPTED"

        alerts.append(
            f"CORRUPTED PARQUET: {file}"
        )

    status_rows.append(row)

status_df = pd.DataFrame(status_rows)

st.dataframe(
    status_df,
    use_container_width=True
)

# =========================================
# RESEARCH HEALTH
# =========================================

st.header("Research / Model Health")

try:

    if os.path.exists(
        "regime_history.parquet"
    ):

        regime_df = pd.read_parquet(
            "regime_history.parquet"
        )

        if "regime" in regime_df.columns:

            regime_counts = (
                regime_df["regime"]
                .value_counts()
            )

            st.subheader(
                "Regime Distribution"
            )

            st.bar_chart(regime_counts)

except Exception:

    st.warning(
        "Could not load regime distribution"
    )

# =========================================
# ALERTS
# =========================================

st.header("Critical Alerts")

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

st.caption(
    f"Refresh interval: {REFRESH_SECONDS} sec"
)

# =========================================
# AUTO REFRESH
# =========================================

time.sleep(REFRESH_SECONDS)

st.rerun()
