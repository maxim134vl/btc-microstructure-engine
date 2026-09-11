"""ARCHIVED 2026-09-11. Do not import. Do not wire back.

This was the hurried S4.1 anti-saw: min-hold N bars before a flip CLOSE,
then cooldown N bars before the next OPEN. M15 4/4 = 60 minutes of lag
on every flip, with no test of whether the market is in a saw.

It is not a saw detector. Keep it here only as a corpse.

The surviving saw signal is auction path-density / balance_support
(net displacement vs path, two-sided effort, range expansion) in
`btc_ml.trading.shadow_auction.features`. That stays a trade filter
candidate. It must not be mixed into context START/END/FLIP.
"""

raise ImportError(
    "anti_saw_bar_count_rails is archived. Do not import. "
    "Bar-count min-hold/cooldown is not a saw detector."
)


ANTI_SAW_MIN_HOLD_BARS = {"M15": 4, "M30": 3, "H1": 2, "H4": 1}
ANTI_SAW_ENTRY_COOLDOWN_BARS = {"M15": 4, "M30": 3, "H1": 2, "H4": 1}


def _anti_saw_block_context_close(*_args, **_kwargs):
    return False, None


def _anti_saw_block_entry(*_args, **_kwargs):
    return False, None
