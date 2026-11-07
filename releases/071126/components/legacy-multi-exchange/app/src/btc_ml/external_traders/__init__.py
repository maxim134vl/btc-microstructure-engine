"""External trader trade normalization (ETLL import layer).

Raw broker/report CSVs → canonical fills + positions.
Offline / research only — does not touch live paper or cognition.
"""

from btc_ml.external_traders.build import build_canonical_external_trades

__all__ = ["build_canonical_external_trades"]
