# Canonical Paper Trading Policy Reconfirmation

- validation_status: PASS
- entry_source_of_truth: canonical_policy_context_episodes.start_time produced by context start event policy
- exit_source_of_truth: canonical_policy_context_episodes.end_time produced by directional context end/invalidation policy
- entry_price_policy: CONTEXT_START_BAR_POLICY_PRICE
- exit_price_policy: CONTEXT_END_BAR_POLICY_PRICE
- trade_side_source: PAPER_POLICY_ACTION
- stop_take_role: visual/risk template from paper_pnl_engine; not execution logic in this research export
- ambiguous_policy_fields: []
