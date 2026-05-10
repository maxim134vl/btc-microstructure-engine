import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# =================================
# PAGE
# =================================

st.set_page_config(
    page_title="BTC Research Lab",
    layout="wide"
)

st.title("BTC MICROSTRUCTURE RESEARCH LAB")

# =================================
# LOAD DATA
# =================================

@st.cache_data(ttl=30)

def load_data():

    flow = pd.read_parquet(
        "intraday_flow.parquet"
    )

    oi = pd.read_parquet(
        "oi_history.parquet"
    )

    book = pd.read_parquet(
        "orderbook.parquet"
    )

    events = pd.read_parquet(
        "market_events.parquet"
    )

    return flow, oi, book, events

flow, oi, book, events = load_data()

# =================================
# ALIGN
# =================================

min_len = min(

    len(flow),

    len(oi),

    len(book)
)

flow = flow.tail(min_len)

oi = oi.tail(min_len)

book = book.tail(min_len)

# =================================
# FEATURES
# =================================

flow['delta_smooth'] = (

    flow['delta']
    .rolling(50)
    .mean()
)

returns = (

    flow['avg_price']
    .pct_change()
)

flow['volatility'] = (

    returns
    .rolling(50)
    .std()
)

oi['oi_change'] = (

    oi['open_interest']
    .diff()
)

book['imbalance_smooth'] = (

    book['imbalance']
    .rolling(50)
    .mean()
)

# =================================
# OI Z-SCORE
# =================================

WINDOW = 200

oi['oi_z'] = (

    (
        oi['oi_change']
        -
        oi['oi_change']
        .rolling(WINDOW)
        .mean()
    )

    /

    oi['oi_change']
    .rolling(WINDOW)
    .std()
)

# =================================
# LATEST VALUES
# =================================

latest_price = (
    flow.iloc[-1]['avg_price']
)

latest_delta = (
    flow.iloc[-1]['delta_smooth']
)

latest_vol = (
    flow.iloc[-1]['volatility']
)

latest_oi_z = abs(
    oi.iloc[-1]['oi_z']
)

latest_imbalance = (
    book.iloc[-1]['imbalance_smooth']
)

# =================================
# REGIME
# =================================

market_state = "UNDEFINED"

if (

    latest_vol < 0.00001

    and

    abs(latest_delta) < 10
):

    market_state = (
        "QUIET_COMPRESSION"
    )

elif (

    latest_vol < 0.00001

    and

    abs(latest_imbalance) > 0.1
):

    market_state = (
        "PASSIVE_IMBALANCE"
    )

elif (

    latest_oi_z > 5

    and

    latest_vol < 0.00005
):

    market_state = (
        "LEVERAGE_BUILDUP"
    )

elif (

    latest_vol > 0.00005

    and

    abs(latest_delta) > 50
):

    market_state = (
        "VOLATILITY_EXPANSION"
    )

# =================================
# METRICS
# =================================

col1, col2, col3, col4, col5 = st.columns(5)

col1.metric(
    "BTC PRICE",
    round(latest_price, 2)
)

col2.metric(
    "DELTA",
    round(latest_delta, 2)
)

col3.metric(
    "VOLATILITY",
    round(latest_vol, 8)
)

col4.metric(
    "OI Z-SCORE",
    round(latest_oi_z, 2)
)

col5.metric(
    "IMBALANCE",
    round(latest_imbalance, 4)
)

# =================================
# STATE
# =================================

st.subheader("CURRENT MARKET REGIME")

st.success(market_state)

# =================================
# PRICE CHART
# =================================

st.subheader("BTC PRICE")

fig = go.Figure()

fig.add_trace(

    go.Scatter(

        x=flow.index,

        y=flow['avg_price'],

        mode='lines',

        name='BTC'
    )
)

st.plotly_chart(
    fig,
    use_container_width=True
)

# =================================
# DELTA
# =================================

st.subheader("DELTA PRESSURE")

fig2 = go.Figure()

fig2.add_trace(

    go.Scatter(

        x=flow.index,

        y=flow['delta_smooth'],

        mode='lines',

        name='Delta'
    )
)

st.plotly_chart(
    fig2,
    use_container_width=True
)

# =================================
# OI Z SCORE
# =================================

st.subheader("OI ANOMALY")

fig3 = go.Figure()

fig3.add_trace(

    go.Scatter(

        x=oi.index,

        y=oi['oi_z'],

        mode='lines',

        name='OI Z'
    )
)

st.plotly_chart(
    fig3,
    use_container_width=True
)

# =================================
# IMBALANCE
# =================================

st.subheader("ORDERBOOK IMBALANCE")

fig4 = go.Figure()

fig4.add_trace(

    go.Scatter(

        x=book.index,

        y=book['imbalance_smooth'],

        mode='lines',

        name='Imbalance'
    )
)

st.plotly_chart(
    fig4,
    use_container_width=True
)

# =================================
# EVENTS
# =================================

st.subheader("EVENT DISTRIBUTION")

st.dataframe(

    events['event']
    .value_counts()
)

# =================================
# INTERPRETATION
# =================================

st.subheader("INTERPRETATION")

if latest_vol < 0.00001:

    st.write(
        "• Low volatility regime"
    )

if abs(latest_imbalance) > 0.2:

    st.write(
        "• Persistent liquidity imbalance"
    )

if latest_oi_z > 5:

    st.write(
        "• Extreme leverage anomaly"
    )

if abs(latest_delta) > 50:

    st.write(
        "• Aggressive directional pressure"
    )
