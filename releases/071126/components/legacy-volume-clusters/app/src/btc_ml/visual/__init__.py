"""Visual read-models derived from canonical runtime truth.

Everything in this package is read-only with respect to trading state: it maps
already-settled ledger rows into render-ready views and never recomputes trade
economics.
"""

from btc_ml.visual.canonical_trade_view import (  # noqa: F401
    CANONICAL_VISUAL_TRADE_SCHEMA_VERSION,
    ECONOMICS_VERSION,
    LEGACY_TIMEFRAME,
    build_canonical_visual_trades,
    write_canonical_visual_trades,
)
