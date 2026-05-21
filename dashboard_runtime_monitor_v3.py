import os
import time
from datetime import datetime

import pandas as pd
import psutil
import streamlit as st

# =========================================
# CONFIG
# =========================================

REFRESH_SECONDS = 10

DATASET_GROUPS = {

    "LIVE_FEEDS": {

        "threshold_minutes": 2,

        "datasets": [

            "orderbook.parquet",
            "bybit_flow.parquet",
            "hyperliquid_flow.parquet",
            "multi_exchange_flow.parquet",
            "live_market_feed.parquet"

        ]

    },

    "CORE_MARKET": {

        "threshold_minutes": 30,

        "datasets": [

            "btc_15m.parquet",
            "btc_5m.parquet",
            "btc_oi.parquet",
            "btc_funding.parquet"

        ]

    },

    "RUNTIME_MEMORY": {

        "threshold_minutes": 60,

        "datasets": [

            "initiative_memory.parquet",
            "event_chains_memory.parquet",
            "contextual_memory_state.parquet",
            "market_context_memory.parquet",
            "adaptive_meta_cognition_state.parquet",
            "live_recursive_beliefs.parquet",
            "auction_convergence_memory.parquet"

        ]

    },

    "RESEARCH": {

        "threshold_minutes": None,

        "datasets": [

            "btc_15m_train.parquet",
            "btc_15m_validation.parquet",
            "btc_15m_test.parquet",
            "wf_window_1_train.parquet",
            "wf_window_1_validation.parquet",
            "wf_window_2_train.parquet",
            "wf_window_2_validation.parquet",
            "wf_window_3_train.parquet",
            "wf_window_3_validation.parquet"

        ]

    }

}

# =========================================
# PAGE CONFIG
# =========================================

st.set_page_config(
    page_title="BTC Runtime Monitor V3",
    layout="wide"
)

st.title("BTC Microstructure Engine")
st.subheader("Operational Runtime Monitoring")

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
# DATASET TOPOLOGY
# =========================================

alerts = []

for group_name, config in DATASET_GROUPS.items():

    st.header(group_name)

    rows = []

    threshold = config["threshold_minutes"]

    for file in config["datasets"]:

        row = {

            "dataset": file,
            "status": "UNKNOWN",
            "minutes_since_update": None,
            "size_mb": None,
            "rows": None,
            "columns": None,
            "nan_count": None

        }

        if not os.path.exists(file):

            row["status"] = "MISSING"

            alerts.append(
                f"MISSING: {file}"
            )

            rows.append(row)

            continue

        try:

            modified = os.path.getmtime(file)

            age_minutes = (
                time.time() - modified
            ) / 60

            size_mb = (
                os.path.getsize(file)
                / 1024
                / 1024
            )

            row["minutes_since_update"] = round(
                age_minutes,
                2
            )

            row["size_mb"] = round(
                size_mb,
                2
            )

            if threshold is None:

                row["status"] = "STATIC"

            else:

                if age_minutes > threshold:

                    row["status"] = "STALE"

                    alerts.append(
                        f"STALE: {file}"
                    )

                else:

                    row["status"] = "RUNNING"

            # =========================
            # LIGHTWEIGHT VALIDATION
            # =========================

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

        except Exception:

            row["status"] = "CORRUPTED"

            alerts.append(
                f"CORRUPTED: {file}"
            )

        rows.append(row)

    df_status = pd.DataFrame(rows)

    st.dataframe(
        df_status,
        use_container_width=True
    )

# =========================================
# REGIME HEALTH
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

            st.subheader(
                "Regime Distribution"
            )

            regime_counts = (
                regime_df["regime"]
                .value_counts()
            )

            st.bar_chart(regime_counts)

except Exception:

    st.warning(
        "Could not load regime data"
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
