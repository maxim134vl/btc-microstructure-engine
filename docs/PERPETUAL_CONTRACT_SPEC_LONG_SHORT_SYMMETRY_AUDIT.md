# Perpetual Contract Spec + LONG/SHORT Symmetry Audit

## 1. Executive summary

- Status: `PERPETUAL_CONTRACT_SPEC_AND_LONG_SHORT_SYMMETRY_PASS_WITH_LIMITATIONS`
- Instrument: `BTCUSDT_PERPETUAL`
- Contract type: `PERPETUAL`
- Risk gate symmetric: `True`
- Cost/TCA symmetric: `True`
- Next step: `BUILD_PAPER_TRADE_SIMULATION_DRY_RUN_NO_LEDGER_WRITE`

This audit corrects the contract specification and validates LONG/SHORT symmetry for paper simulation. It does not write to paper ledgers, does not create orders, does not create positions, does not create trades, does not start paper trading, does not enable execution, and does not call any exchange API.

## 2. Scope

Correct BTCUSDT perpetual contract wording and validate LONG/SHORT symmetry across
signal mapping, risk gate, TCA/cost, and order preview. JSON outputs only.

## 3. Why wording correction was required

- Old wording: `USDⓈ-M Futures`
- Corrected wording: `BTCUSDT USDT-margined perpetual contract`
- Reason: `USDⓈ-M is product family; perpetual is the actual contract type used for funding/TCA/order simulation`

## 4. BTCUSDT perpetual contract spec

| Field | Value |
| --- | --- |
| venue | `BINANCE_FUTURES` |
| product_family | `USDⓈ-M` |
| instrument | `BTCUSDT_PERPETUAL` |
| symbol | `BTCUSDT` |
| contract_type | `PERPETUAL` |
| margin_asset | `USDT` |
| settlement_asset | `USDT` |
| long_supported | `True` |
| short_supported | `True` |
| funding_model_status | `DEFERRED_SEPARATE_LAYER` |

## 5. LONG/SHORT signal mapping audit

| Field | Value |
| --- | --- |
| long_context_mapping | `ENTER_EARLIER/PROMOTE_CONTEXT -> INTENT_OPEN_LONG` |
| short_context_mapping | `ENTER_EARLIER/PROMOTE_CONTEXT -> INTENT_OPEN_SHORT` |
| observe_mapping | `NO_TRADE` |
| downgrade_volume_mapping | `NO_TRADE_VOLUME_RULE_BLOCK` |
| suppress_context_mapping | `NO_TRADE_SUPPRESS` |
| mapping_symmetric | `True` |

## 6. LONG/SHORT risk gate symmetry audit

| Field | Value |
| --- | --- |
| total_cases | `10` |
| clean_long_passed | `True` |
| clean_short_passed | `True` |
| low_confidence_block_symmetric | `True` |
| edge_below_cost_block_symmetric | `True` |
| stale_context_block_symmetric | `True` |
| spread_block_symmetric | `True` |
| no_artificial_short_block | `True` |
| risk_gate_symmetric | `True` |

## 7. LONG/SHORT cost/TCA symmetry audit

| Field | Value |
| --- | --- |
| long_entry_cost_usd | `7.5` |
| short_entry_cost_usd | `7.5` |
| long_shortfall_bps | `5.0` |
| short_shortfall_bps | `5.0` |
| cost_tca_symmetric | `True` |
| funding_separate_for_both | `True` |

## 8. LONG/SHORT order preview symmetry audit

| Field | Value |
| --- | --- |
| long_order_side | `BUY` |
| short_order_side | `SELL` |
| long_position_intent | `OPEN_LONG` |
| short_position_intent | `OPEN_SHORT` |
| no_order_created | `True` |
| no_paper_order_id_created | `True` |
| order_preview_symmetric | `True` |

## 9. Safety validation

| Check | Value |
| --- | --- |
| paper_ledgers_unchanged | `True` |
| paper_order_created | `False` |
| position_created | `False` |
| trade_created | `False` |
| ledger_writes_performed | `False` |
| exchange_api_order_call_used | `False` |
| production_parquet_mutated | `False` |

## 10. Remaining limitations

- funding still deferred
- live decision sample still too small
- no paper trading loop approved
- trade simulation still pending

## 11. Next recommended step

**`BUILD_PAPER_TRADE_SIMULATION_DRY_RUN_NO_LEDGER_WRITE`**
