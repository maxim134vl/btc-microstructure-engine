# BTC-ML — local orchestration targets (no engine/runtime logic changes)
#
# Historical local pieces:
#   ./scripts/start_collectors.sh
#   ./run.sh  /  run.py [--with-collectors]
#   dashboard/scripts/start_dashboard.sh
# Docker (when deploy/ is present): make up / down / ps

.DEFAULT_GOAL := help

.PHONY: help runtime-stack runtime-stack-start runtime-stack-stop runtime-stack-status runtime-stack-restart context-decision-log-once live-context-refresh-once decision-latency-audit decision-no-repaint-audit live-refresh-stability-audit live-refresh-catch-up-investigation confirmation-delay-deep-dive result-outcome-quality-deep-dive trigger-trace-deep-dive termination-timing-deep-dive termination-root-cause-investigation lifecycle-termination-rules-deeper lifecycle-calibration-follow-up missed-context-deep-dive volume-climax-deep-dive volume-climax-root-cause-investigation live-postfactum-limitation-audit decision-log-snapshot-archive context-economic-efficiency-audit economic-qa-toxic-box-inventory training-dataset-plan prepare-retraining-candidate run-retraining-candidate old-vs-new-context-replay-audit candidate-replay-consistency-reweighting-plan prepare-retraining-candidate-v2-reweighted run-retraining-candidate-v2-reweighted candidate-v2-old-vs-new-replay-audit prepare-retraining-candidate-v3-balanced run-retraining-candidate-v3-balanced candidate-v3-old-vs-new-replay-audit paper-simulator-design-readiness paper-simulator-schema-ledger literature-aligned-paper-simulator-spec paper-risk-gate-scientific paper-signal-adapter-dry-run paper-short-policy-for-futures paper-one-shot-dry-run-no-ledger-write one-shot-paper-ledger-event-write one-shot-paper-ledger-write-qa paper-fill-simulation-dry-run-no-ledger-write one-shot-paper-fill-event-write one-shot-paper-fill-event-write-qa paper-order-simulation-dry-run-no-ledger-write one-shot-paper-order-ledger-record-write one-shot-paper-order-ledger-write-qa perpetual-long-short-symmetry-audit paper-trade-simulation-dry-run-no-ledger-write one-shot-paper-trade-ledger-record-write one-shot-paper-trade-ledger-write-qa perpetual-long-short-cashflow-semantics-audit paper-position-simulation-dry-run-no-ledger-write one-shot-paper-position-ledger-record-write one-shot-paper-position-ledger-write-qa full-long-one-shot-paper-chain-dry-run-no-ledger-write full-long-one-shot-ledger-chain-write full-long-one-shot-ledger-chain-write-qa long-short-ledger-parity-readiness-audit paper-equity-pnl-simulation-dry-run-no-ledger-write one-shot-equity-pnl-ledger-write one-shot-equity-pnl-ledger-write-qa paper-risk-block-simulation-dry-run-no-ledger-write risk-block-ledger-write-skip-decision minimal-paper-loop-controller-dry-run-no-ledger-write minimal-paper-loop-controller-dry-run-qa live-decision-to-paper-signal-adapter-dry-run-no-ledger-write live-decision-to-paper-signal-adapter-dry-run-qa live-decision-signal-readiness-gap-audit live-decision-log-signal-fields-dry-run-no-live-log-write live-decision-log-signal-fields-patch-additive live-decision-log-signal-fields-patch-qa confidence-expected-edge-source-readiness-audit confidence-expected-edge-source-design-dry-run-no-live-log-write context-edge-calibration-dataset-dry-run-no-model-fit context-edge-calibration-dataset-qa-audit lagged-context-edge-lookup-dry-run-no-live-log-write lagged-context-edge-lookup-qa-audit edge-semantics-correction-dry-run-no-live-log-write edge-semantics-correction-qa-audit corrected-lagged-context-edge-lookup-snapshot-dry-run-no-live-log-write corrected-lagged-context-edge-lookup-snapshot-qa-audit logger-lookup-integration-dry-run-no-live-log-write logger-lookup-integration-dry-run-qa-audit logger-lookup-integration-patch-additive logger-lookup-integration-patch-qa-audit rerun-live-decision-paper-signal-adapter-dry-run-no-ledger-write rerun-live-decision-paper-signal-adapter-qa-audit live-decision-log-freshness-cadence-readiness-audit single-live-refresh-decision-log-append-no-paper-signal single-live-refresh-append-qa-audit rerun-live-decision-adapter-after-single-append-dry-run-no-ledger-write rerun-after-single-append-adapter-qa-audit next-single-live-refresh-decision-log-append-no-paper-signal bounded-live-decision-candidate-watcher-dry-run context-trade-anatomy-dataset context-trade-anatomy-dataset-qa-audit context-trade-economics-calibration-report context-trade-economics-calibration-report-qa-audit bar-path-replay-stop-take-policy-dry-run bar-path-replay-stop-take-policy-qa-audit walk-forward-stop-take-policy-validation-dry-run walk-forward-stop-take-policy-validation-qa-audit paper-policy-engine-implementation-dry-run paper-policy-engine-implementation-qa-audit policy-engine-to-paper-signal-adapter-integration-dry-run policy-engine-to-paper-signal-adapter-qa-audit live-policy-signal-candidate-cycle-dry-run-no-write live-policy-signal-candidate-cycle-qa-audit live-policy-signal-candidate-cycle-qa-latest live-candidate-preview-price-source-correction-dry-run-no-write live-candidate-preview-price-source-correction-qa-audit live-candidate-visual-panel-from-preview-dry-run-no-write live-candidate-visual-panel-qa-audit paper-signal-preview-write-no-ledger-no-execution paper-signal-preview-write-qa-audit paper-order-dry-run-write-no-trade-no-position-no-execution paper-order-dry-run-write-qa-audit paper-trade-position-equity-one-shot-no-execution paper-trade-position-equity-one-shot-qa-audit paper-position-monitor-dry-run-no-execution-no-ledger-write paper-position-monitor-dry-run-qa-audit bounded-live-policy-signal-watcher-no-write bounded-live-policy-signal-watcher-qa-audit trade-visualization-dry-run-from-replay-or-fixture trade-visualization-qa-audit trade-visualization-price-math-correction-dry-run trade-visualization-price-math-correction-qa-audit visual-trade-panel-design-dry-run-no-server visual-trade-panel-qa-audit single-live-context-refresh-append-qa-audit context-visual-stack-start context-visual-stack-stop context-visual-stack-restart context-visual-stack-status context-visual-stack-tail

help: ## Show orchestration targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

runtime-stack: runtime-stack-start ## Start full local stack (alias)

runtime-stack-start: ## Start watchdog + run.py + dashboard + context visual refresher
	./scripts/runtime_stack.sh start

runtime-stack-stop: ## Stop full local stack
	./scripts/runtime_stack.sh stop

runtime-stack-status: ## Status of stack processes / ports / feed
	./scripts/runtime_stack.sh status

runtime-stack-restart: ## Restart full local stack
	./scripts/runtime_stack.sh restart

context-decision-log-once: ## Append one shadow-only context decision row (no execution)
	venv/bin/python scripts/live/append_context_decision_log.py

live-context-refresh-once: ## Manual once refresh: rebuild shadow chain if stale, then decision log
	venv/bin/python scripts/live/run_live_context_refresh_once.py

decision-latency-audit: ## Read-only decision latency audit (no execution, no mutation)
	venv/bin/python scripts/research/audit_decision_latency.py

decision-no-repaint-audit: ## Read-only decision no-repaint / immutability audit (no execution, no mutation)
	venv/bin/python scripts/research/audit_decision_no_repaint.py

live-refresh-stability-audit: ## Read-only live context refresh once-mode stability audit
	venv/bin/python scripts/research/audit_live_refresh_stability.py

live-refresh-catch-up-investigation: ## Read-only investigate catch-up failure vs once-mode cadence gap
	venv/bin/python scripts/research/investigate_live_refresh_catch_up_failure.py

confirmation-delay-deep-dive: ## Read-only confirmation delay deep dive (model vs technical lag)
	venv/bin/python scripts/research/audit_confirmation_delay_deep_dive.py

result-outcome-quality-deep-dive: ## Read-only result/outcome quality deep dive for LONG/SHORT contexts
	venv/bin/python scripts/research/audit_result_outcome_quality_deep_dive.py

trigger-trace-deep-dive: ## Read-only trigger signature deep dive for LONG/SHORT contexts
	venv/bin/python scripts/research/audit_trigger_trace_deep_dive.py

termination-timing-deep-dive: ## Read-only termination timing deep dive for LONG/SHORT contexts
	venv/bin/python scripts/research/audit_termination_timing_deep_dive.py

termination-root-cause-investigation: ## Read-only termination root cause investigation
	venv/bin/python scripts/research/investigate_termination_root_cause.py

lifecycle-termination-rules-deeper: ## Read-only deeper lifecycle termination rules investigation
	venv/bin/python scripts/research/investigate_lifecycle_termination_rules_deeper.py

lifecycle-calibration-follow-up: ## Read-only lifecycle calibration follow-up (in-memory proxy only)
	venv/bin/python scripts/research/audit_lifecycle_calibration_follow_up.py

missed-context-deep-dive: ## Read-only missed context deep dive (non-active material moves)
	venv/bin/python scripts/research/audit_missed_context_deep_dive.py

volume-climax-deep-dive: ## Read-only volume/climax predictive value deep dive
	venv/bin/python scripts/research/audit_volume_climax_deep_dive.py

volume-climax-root-cause-investigation: ## Read-only volume climax root cause investigation
	venv/bin/python scripts/research/investigate_volume_climax_root_cause.py

live-postfactum-limitation-audit: ## Read-only live vs postfactum limitation audit
	venv/bin/python scripts/research/audit_live_postfactum_limitation.py

decision-log-snapshot-archive: ## Archive immutable decision-log snapshot (no execution, no mutation of source)
	venv/bin/python scripts/live/archive_context_decision_log_snapshot.py --once

context-economic-efficiency-audit: ## Read-only context economic efficiency audit (no execution, no mutation)
	venv/bin/python scripts/research/audit_context_economic_efficiency.py

economic-qa-toxic-box-inventory: ## Research-only economic QA + toxic box inventory (no retrain, no execution)
	venv/bin/python scripts/research/build_economic_qa_toxic_box_inventory.py

training-dataset-plan: ## Research-only training dataset plan from Economic QA / Toxic Box (no retrain)
	venv/bin/python scripts/research/prepare_training_dataset_plan.py

prepare-retraining-candidate: ## Research-only retraining candidate scaffold (dry-run only, no fit)
	venv/bin/python scripts/research/prepare_retraining_candidate.py

run-retraining-candidate: ## Research-only retraining candidate fit under data/research (no production replace)
	venv/bin/python scripts/research/run_retraining_candidate.py --research-only

old-vs-new-context-replay-audit: ## Research-only old vs new context replay audit for retraining candidate
	venv/bin/python scripts/research/audit_old_vs_new_context_replay.py --run-dir data/research/retraining_candidate/runs/context_retraining_candidate_v1_20260719T182153Z

candidate-replay-consistency-reweighting-plan: ## Read-only replay consistency check + v2 reweighting plan (no fit)
	venv/bin/python scripts/research/audit_candidate_replay_consistency_reweighting_plan.py --run-dir data/research/retraining_candidate/runs/context_retraining_candidate_v1_20260719T182153Z

prepare-retraining-candidate-v2-reweighted: ## Prepare candidate v2 reweighted dataset/config (no training)
	venv/bin/python scripts/research/prepare_retraining_candidate_v2_reweighted.py

run-retraining-candidate-v2-reweighted: ## Research-only train candidate v2 reweighted (no production/exec/paper)
	venv/bin/python scripts/research/run_retraining_candidate_v2_reweighted.py --research-only

candidate-v2-old-vs-new-replay-audit: ## Research-only v2 old vs new replay audit (no fit)
	venv/bin/python scripts/research/audit_candidate_v2_old_vs_new_replay.py --run-dir data/research/retraining_candidate/v2_reweighted/runs/context_retraining_candidate_v2_reweighted_20260719T185059Z

prepare-retraining-candidate-v3-balanced: ## Prepare candidate v3 balanced dataset/config (no training)
	venv/bin/python scripts/research/prepare_retraining_candidate_v3_balanced.py

run-retraining-candidate-v3-balanced: ## Research-only train candidate v3 balanced (no production/exec/paper)
	venv/bin/python scripts/research/run_retraining_candidate_v3_balanced.py --research-only

candidate-v3-old-vs-new-replay-audit: ## Research-only v3 old vs new replay audit (no fit)
	venv/bin/python scripts/research/audit_candidate_v3_old_vs_new_replay.py --run-dir data/research/retraining_candidate/v3_balanced/runs/context_retraining_candidate_v3_balanced_20260719T193548Z

paper-simulator-design-readiness: ## Research-only paper simulator design readiness (no paper trading)
	venv/bin/python scripts/research/audit_paper_simulator_design_readiness.py

paper-simulator-schema-ledger: ## Research-only empty paper simulator schema + isolated ledger
	venv/bin/python scripts/research/build_paper_simulator_schema_ledger.py

literature-aligned-paper-simulator-spec: ## Research-only literature-aligned paper simulator scientific spec
	venv/bin/python scripts/research/build_literature_aligned_paper_simulator_spec.py

paper-risk-gate-scientific: ## Research-only paper risk gate scientific (no paper trading/orders)
	venv/bin/python scripts/research/build_paper_risk_gate_scientific.py

paper-signal-adapter-dry-run: ## Research-only paper signal adapter dry-run (no orders/ledger writes)
	venv/bin/python scripts/research/build_paper_signal_adapter_dry_run.py

paper-short-policy-for-futures: ## Research-only patch short policy for USDⓈ-M Futures (no orders/ledgers)
	venv/bin/python scripts/research/review_paper_short_policy_for_futures.py

paper-one-shot-dry-run-no-ledger-write: ## Research-only one-shot paper dry-run (no orders/ledger writes)
	venv/bin/python scripts/research/build_paper_one_shot_dry_run_no_ledger_write.py

one-shot-paper-ledger-event-write: ## Research-only one-shot paper_events write (requires approval flags)
	venv/bin/python scripts/research/write_one_shot_paper_ledger_event.py --research-only --approved-one-shot-ledger-write

one-shot-paper-ledger-write-qa: ## Research-only QA audit of one-shot paper ledger write (read-only ledgers)
	venv/bin/python scripts/research/audit_one_shot_paper_ledger_write_qa.py

paper-fill-simulation-dry-run-no-ledger-write: ## Research-only fill simulation dry-run (no orders/ledgers)
	venv/bin/python scripts/research/build_paper_fill_simulation_dry_run_no_ledger_write.py

one-shot-paper-fill-event-write: ## Research-only one-shot fill event write (requires approval flags)
	venv/bin/python scripts/research/write_one_shot_paper_fill_event.py --research-only --approved-one-shot-fill-ledger-write

one-shot-paper-fill-event-write-qa: ## Research-only QA audit of one-shot fill event write (read-only ledgers)
	venv/bin/python scripts/research/audit_one_shot_paper_fill_event_write_qa.py

paper-order-simulation-dry-run-no-ledger-write: ## Research-only paper order simulation dry-run (no ledger write)
	venv/bin/python scripts/research/build_paper_order_simulation_dry_run_no_ledger_write.py

one-shot-paper-order-ledger-record-write: ## Research-only one-shot paper order ledger write (requires approval flags)
	venv/bin/python scripts/research/write_one_shot_paper_order_ledger_record.py --research-only --approved-one-shot-order-ledger-write

one-shot-paper-order-ledger-write-qa: ## Research-only QA audit of one-shot paper order ledger write (read-only ledgers)
	venv/bin/python scripts/research/audit_one_shot_paper_order_ledger_write_qa.py

perpetual-long-short-symmetry-audit: ## Research-only perpetual contract + LONG/SHORT symmetry audit (no ledger write)
	venv/bin/python scripts/research/audit_perpetual_contract_spec_long_short_symmetry.py

paper-trade-simulation-dry-run-no-ledger-write: ## Research-only paper trade simulation dry-run (no ledger write)
	venv/bin/python scripts/research/build_paper_trade_simulation_dry_run_no_ledger_write.py

one-shot-paper-trade-ledger-record-write: ## Research-only one-shot paper trade ledger write (requires approval flags)
	venv/bin/python scripts/research/write_one_shot_paper_trade_ledger_record.py --research-only --approved-one-shot-trade-ledger-write

one-shot-paper-trade-ledger-write-qa: ## Research-only QA audit of one-shot paper trade ledger write (read-only ledgers)
	venv/bin/python scripts/research/audit_one_shot_paper_trade_ledger_write_qa.py

perpetual-long-short-cashflow-semantics-audit: ## Research-only perpetual LONG/SHORT cashflow semantics audit (no ledger write)
	venv/bin/python scripts/research/audit_perpetual_long_short_cashflow_semantics.py

paper-position-simulation-dry-run-no-ledger-write: ## Research-only paper position simulation dry-run (no ledger write)
	venv/bin/python scripts/research/build_paper_position_simulation_dry_run_no_ledger_write.py

one-shot-paper-position-ledger-record-write: ## Research-only one-shot paper position ledger write (requires approval flags)
	venv/bin/python scripts/research/write_one_shot_paper_position_ledger_record.py --research-only --approved-one-shot-position-ledger-write

one-shot-paper-position-ledger-write-qa: ## Research-only QA audit of one-shot paper position ledger write (read-only ledgers)
	venv/bin/python scripts/research/audit_one_shot_paper_position_ledger_write_qa.py

full-long-one-shot-paper-chain-dry-run-no-ledger-write: ## Research-only full LONG one-shot paper chain dry-run (no ledger write)
	venv/bin/python scripts/research/build_full_long_one_shot_paper_chain_dry_run_no_ledger_write.py

full-long-one-shot-ledger-chain-write: ## Research-only full LONG one-shot ledger chain write (requires approval flags)
	venv/bin/python scripts/research/write_full_long_one_shot_ledger_chain.py --research-only --approved-full-long-one-shot-ledger-writes

full-long-one-shot-ledger-chain-write-qa: ## Research-only QA audit of full LONG one-shot ledger chain write (read-only ledgers)
	venv/bin/python scripts/research/audit_full_long_one_shot_ledger_chain_write_qa.py

long-short-ledger-parity-readiness-audit: ## Research-only LONG/SHORT ledger parity readiness audit (read-only ledgers)
	venv/bin/python scripts/research/build_long_short_ledger_parity_readiness_audit.py

paper-equity-pnl-simulation-dry-run-no-ledger-write: ## Research-only paper equity/PnL simulation dry-run (no ledger write)
	venv/bin/python scripts/research/build_paper_equity_pnl_simulation_dry_run_no_ledger_write.py

one-shot-equity-pnl-ledger-write: ## Research-only one-shot equity/PnL ledger write (requires approval flags)
	venv/bin/python scripts/research/write_one_shot_equity_pnl_ledger_records.py --research-only --approved-one-shot-equity-pnl-ledger-write

one-shot-equity-pnl-ledger-write-qa: ## Research-only QA audit of one-shot equity/PnL ledger write (read-only ledgers)
	venv/bin/python scripts/research/audit_one_shot_equity_pnl_ledger_write_qa.py

paper-risk-block-simulation-dry-run-no-ledger-write: ## Research-only paper risk block simulation dry-run (no ledger write)
	venv/bin/python scripts/research/build_paper_risk_block_simulation_dry_run_no_ledger_write.py

risk-block-ledger-write-skip-decision: ## Research-only risk block ledger write skip decision audit (read-only ledgers)
	venv/bin/python scripts/research/audit_risk_block_ledger_write_skip_decision.py

minimal-paper-loop-controller-dry-run-no-ledger-write: ## Research-only minimal paper loop controller dry-run (no ledger write / no loop)
	venv/bin/python scripts/research/build_minimal_paper_loop_controller_dry_run_no_ledger_write.py

minimal-paper-loop-controller-dry-run-qa: ## Research-only QA audit of minimal paper loop controller dry-run (read-only ledgers)
	venv/bin/python scripts/research/audit_minimal_paper_loop_controller_dry_run_qa.py

live-decision-to-paper-signal-adapter-dry-run-no-ledger-write: ## Research-only live decision to paper signal adapter dry-run (no ledger write)
	venv/bin/python scripts/research/build_live_decision_to_paper_signal_adapter_dry_run_no_ledger_write.py

live-decision-to-paper-signal-adapter-dry-run-qa: ## Research-only QA audit of live decision to paper signal adapter dry-run (read-only)
	venv/bin/python scripts/research/audit_live_decision_to_paper_signal_adapter_dry_run_qa.py

live-decision-signal-readiness-gap-audit: ## Research-only live decision signal readiness gap audit (read-only)
	venv/bin/python scripts/research/audit_live_decision_signal_readiness_gap.py

live-decision-log-signal-fields-dry-run-no-live-log-write: ## Research-only live decision log signal fields dry-run (no live log write)
	venv/bin/python scripts/research/build_live_decision_log_signal_fields_dry_run_no_live_log_write.py

live-decision-log-signal-fields-patch-additive: ## Research-only additive live decision log signal fields patch (explicit approval required)
	venv/bin/python scripts/research/patch_live_decision_log_signal_fields_additive.py --research-only --approved-additive-signal-fields-patch

live-decision-log-signal-fields-patch-qa: ## Read-only QA audit for live decision log signal fields patch
	venv/bin/python scripts/research/audit_live_decision_log_signal_fields_patch_qa.py

confidence-expected-edge-source-readiness-audit: ## Read-only confidence/expected-edge source readiness audit
	venv/bin/python scripts/research/audit_confidence_expected_edge_source_readiness.py

confidence-expected-edge-source-design-dry-run-no-live-log-write: ## Design dry-run for confidence/expected-edge sources (no live log write)
	venv/bin/python scripts/research/build_confidence_expected_edge_source_design_dry_run_no_live_log_write.py

context-edge-calibration-dataset-dry-run-no-model-fit: ## Research-only context edge calibration dataset dry-run (no model fit)
	venv/bin/python scripts/research/build_context_edge_calibration_dataset_dry_run_no_model_fit.py

context-edge-calibration-dataset-qa-audit: ## Read-only QA audit for context edge calibration dataset candidate
	venv/bin/python scripts/research/audit_context_edge_calibration_dataset_qa.py

lagged-context-edge-lookup-dry-run-no-live-log-write: ## Research-only lagged context edge lookup dry-run (no live log write / no model fit)
	venv/bin/python scripts/research/build_lagged_context_edge_lookup_dry_run_no_live_log_write.py

lagged-context-edge-lookup-qa-audit: ## Read-only QA audit for lagged context edge lookup (edge semantics review)
	venv/bin/python scripts/research/audit_lagged_context_edge_lookup_qa.py

edge-semantics-correction-dry-run-no-live-log-write: ## Research-only edge semantics correction dry-run (no live log write)
	venv/bin/python scripts/research/build_edge_semantics_correction_dry_run_no_live_log_write.py

edge-semantics-correction-qa-audit: ## Read-only QA audit for edge semantics correction preview
	venv/bin/python scripts/research/audit_edge_semantics_correction_qa.py

corrected-lagged-context-edge-lookup-snapshot-dry-run-no-live-log-write: ## Research-only corrected lagged context edge lookup snapshot dry-run
	venv/bin/python scripts/research/build_corrected_lagged_context_edge_lookup_snapshot_dry_run_no_live_log_write.py

corrected-lagged-context-edge-lookup-snapshot-qa-audit: ## Read-only QA audit for corrected lagged context edge lookup snapshot
	venv/bin/python scripts/research/audit_corrected_lagged_context_edge_lookup_snapshot_qa.py

logger-lookup-integration-dry-run-no-live-log-write: ## Research-only logger lookup integration dry-run (no live log write / no logger patch)
	venv/bin/python scripts/research/build_logger_lookup_integration_dry_run_no_live_log_write.py

logger-lookup-integration-dry-run-qa-audit: ## Read-only QA audit for logger lookup integration dry-run
	venv/bin/python scripts/research/audit_logger_lookup_integration_dry_run_qa.py

logger-lookup-integration-patch-additive: ## Research-only additive logger lookup integration patch (explicit approval required)
	venv/bin/python scripts/research/patch_logger_lookup_integration_additive.py --research-only --approved-logger-lookup-integration-patch

logger-lookup-integration-patch-qa-audit: ## Read-only QA audit for logger lookup integration patch
	venv/bin/python scripts/research/audit_logger_lookup_integration_patch_qa.py

rerun-live-decision-paper-signal-adapter-dry-run-no-ledger-write: ## Research-only rerun live decision→paper signal adapter dry-run after logger lookup patch (no ledger write)
	venv/bin/python scripts/research/rerun_live_decision_to_paper_signal_adapter_dry_run_no_ledger_write.py

rerun-live-decision-paper-signal-adapter-qa-audit: ## Read-only QA audit for rerun live decision→paper signal adapter dry-run
	venv/bin/python scripts/research/audit_rerun_live_decision_to_paper_signal_adapter_qa.py

live-decision-log-freshness-cadence-readiness-audit: ## Read-only live decision log freshness/cadence readiness audit (no live log write)
	venv/bin/python scripts/research/audit_live_decision_log_freshness_cadence_readiness.py

single-live-refresh-decision-log-append-no-paper-signal: ## Approved one-shot live context refresh + single decision log append (no paper signal)
	venv/bin/python scripts/live/single_live_context_refresh_and_decision_log_append_no_paper_signal.py --approved-single-live-refresh-append --no-paper-signal --one-shot

single-live-refresh-append-qa-audit: ## Read-only QA audit for approved single live context refresh append
	venv/bin/python scripts/research/audit_single_live_context_refresh_append_qa.py

single-live-refresh-append-before-next-monitor-safety: ## Safety audit after refresh append before next monitor (no ledger write)
	venv/bin/python scripts/research/audit_single_live_context_refresh_append_before_next_monitor_safety.py

rerun-live-decision-adapter-after-single-append-dry-run-no-ledger-write: ## Research-only rerun adapter dry-run after single append (no ledger write)
	venv/bin/python scripts/research/rerun_live_decision_adapter_after_single_append_dry_run_no_ledger_write.py

rerun-after-single-append-adapter-qa-audit: ## Read-only QA audit for rerun adapter after single append dry-run
	venv/bin/python scripts/research/audit_rerun_after_single_append_adapter_qa.py

next-single-live-refresh-decision-log-append-no-paper-signal: ## Approved next one-shot live context refresh + single decision log append (no paper signal)
	venv/bin/python scripts/live/next_single_live_context_refresh_and_decision_log_append_no_paper_signal.py --approved-next-single-live-refresh-append --no-paper-signal --one-shot

bounded-live-decision-candidate-watcher-dry-run: ## Dry-run design for bounded live decision candidate watcher (no live run)
	venv/bin/python scripts/live/bounded_live_decision_candidate_watcher.py --dry-run-design-only

context-trade-anatomy-dataset: ## Build historical LONG/SHORT context trade anatomy dataset (calibration only)
	venv/bin/python scripts/research/build_context_trade_anatomy_dataset.py

context-trade-anatomy-dataset-qa-audit: ## Read-only QA audit for context trade anatomy dataset
	venv/bin/python scripts/research/audit_context_trade_anatomy_dataset_qa.py

context-trade-economics-calibration-report: ## Build context trade economics calibration report (no ledger write)
	venv/bin/python scripts/research/build_context_trade_economics_calibration_report.py

context-trade-economics-calibration-report-qa-audit: ## Read-only QA audit for context trade economics calibration report
	venv/bin/python scripts/research/audit_context_trade_economics_calibration_report_qa.py

bar-path-replay-stop-take-policy-dry-run: ## Bar-path replay stop/take policy dry-run (no ledger write)
	venv/bin/python scripts/research/build_bar_path_replay_stop_take_policy_dry_run.py

bar-path-replay-stop-take-policy-qa-audit: ## Read-only QA audit for bar-path replay stop/take policy dry-run
	venv/bin/python scripts/research/audit_bar_path_replay_stop_take_policy_qa.py

walk-forward-stop-take-policy-validation-dry-run: ## Walk-forward stop/take policy validation dry-run (no ledger write)
	venv/bin/python scripts/research/build_walk_forward_stop_take_policy_validation_dry_run.py

walk-forward-stop-take-policy-validation-qa-audit: ## Read-only QA audit for walk-forward stop/take policy validation
	venv/bin/python scripts/research/audit_walk_forward_stop_take_policy_validation_qa.py

paper-policy-engine-implementation-dry-run: ## Paper policy engine implementation dry-run (no ledger write)
	venv/bin/python scripts/research/build_paper_policy_engine_implementation_dry_run.py

paper-policy-engine-implementation-qa-audit: ## Read-only QA audit for paper policy engine implementation
	venv/bin/python scripts/research/audit_paper_policy_engine_implementation_qa.py

policy-engine-to-paper-signal-adapter-integration-dry-run: ## Policy engine → paper signal adapter dry-run (no ledger write)
	venv/bin/python scripts/research/build_policy_engine_to_paper_signal_adapter_integration_dry_run.py

policy-engine-to-paper-signal-adapter-qa-audit: ## Read-only QA audit for policy engine → paper signal adapter
	venv/bin/python scripts/research/audit_policy_engine_to_paper_signal_adapter_qa.py

live-policy-signal-candidate-cycle-dry-run-no-write: ## Live policy signal candidate cycle dry-run (no write)
	venv/bin/python scripts/research/build_live_policy_signal_candidate_cycle_dry_run_no_write.py

live-policy-signal-candidate-cycle-qa-audit: ## Read-only QA audit for live policy signal candidate cycle
	venv/bin/python scripts/research/audit_live_policy_signal_candidate_cycle_qa.py

live-policy-signal-candidate-cycle-qa-latest: ## Read-only QA for latest candidate cycle (price-source check)
	venv/bin/python scripts/research/audit_live_policy_signal_candidate_cycle_qa_latest.py

live-candidate-preview-price-source-correction-dry-run-no-write: ## Correct live candidate preview prices from live_market_feed (no write)
	venv/bin/python scripts/research/correct_live_candidate_preview_price_source_dry_run_no_write.py

live-candidate-preview-price-source-correction-qa-audit: ## Read-only QA for live candidate preview price source correction
	venv/bin/python scripts/research/audit_live_candidate_preview_price_source_correction_qa.py

bounded-live-policy-signal-watcher-no-write: ## Approved bounded live policy signal watcher (no write; requires approval flags)
	venv/bin/python scripts/live/bounded_live_policy_signal_watcher_no_write.py \
		--approved-bounded-live-policy-signal-watcher \
		--no-paper-signal-write \
		--no-paper-ledger-write \
		--no-execution \
		--max-checks 96 \
		--interval-minutes 15 \
		--max-duration-hours 24 \
		--stop-on-directional-signal-preview

bounded-live-policy-signal-watcher-qa-audit: ## Read-only QA audit for bounded live policy signal watcher
	venv/bin/python scripts/research/audit_bounded_live_policy_signal_watcher_qa.py

trade-visualization-dry-run-from-replay-or-fixture: ## Research trade visualization from replay/fixture (no live write)
	venv/bin/python scripts/research/build_trade_visualization_dry_run_from_replay_or_fixture.py

trade-visualization-qa-audit: ## Read-only QA audit for trade visualization dry-run
	venv/bin/python scripts/research/audit_trade_visualization_qa.py

trade-visualization-price-math-correction-dry-run: ## Correct trade visualization MFE/MAE price math (no live write)
	venv/bin/python scripts/research/correct_trade_visualization_price_math_dry_run_no_write.py

trade-visualization-price-math-correction-qa-audit: ## Read-only QA audit for corrected trade visualization price math
	venv/bin/python scripts/research/audit_trade_visualization_price_math_correction_qa.py

visual-trade-panel-design-dry-run-no-server: ## Build static Visual Trade Panel (no server / no write)
	venv/bin/python scripts/research/build_visual_trade_panel_design_dry_run_no_server.py

live-candidate-visual-panel-from-preview-dry-run-no-write: ## Live candidate visual panel from corrected preview (no write)
	venv/bin/python scripts/research/build_live_candidate_visual_panel_from_preview_dry_run_no_write.py

live-candidate-visual-panel-qa-audit: ## Read-only QA for live candidate visual panel
	venv/bin/python scripts/research/audit_live_candidate_visual_panel_qa.py

paper-signal-preview-write-no-ledger-no-execution: ## Approved one-shot paper signal preview write (no ledger / no execution)
	venv/bin/python scripts/live/write_paper_signal_preview_only_no_ledger_no_execution.py \
		--approved-paper-signal-preview-only \
		--no-ledger \
		--no-execution \
		--one-shot

paper-signal-preview-write-qa-audit: ## Read-only QA for paper signal preview-only write
	venv/bin/python scripts/research/audit_paper_signal_preview_write_qa.py

paper-order-dry-run-write-no-trade-no-position-no-execution: ## Approved one-shot paper order dry-run write (no trade / no position / no execution)
	venv/bin/python scripts/live/write_paper_order_dry_run_no_trade_no_position_no_execution.py \
		--approved-paper-order-dry-run \
		--no-trade \
		--no-position \
		--no-execution \
		--one-shot

paper-order-dry-run-write-qa-audit: ## Read-only QA for paper order dry-run write
	venv/bin/python scripts/research/audit_paper_order_dry_run_write_qa.py

paper-trade-position-equity-one-shot-no-execution: ## Approved one-shot paper trade/position/equity write (no execution)
	venv/bin/python scripts/live/write_paper_trade_position_equity_one_shot_no_execution.py \
		--approved-paper-trade-position-equity-one-shot \
		--no-execution \
		--one-shot

paper-trade-position-equity-one-shot-qa-audit: ## Read-only QA for paper trade/position/equity one-shot
	venv/bin/python scripts/research/audit_paper_trade_position_equity_one_shot_qa.py

paper-position-monitor-dry-run-no-execution-no-ledger-write: ## Approved paper position monitor dry-run (no execution / no ledger write)
	venv/bin/python scripts/live/paper_position_monitor_dry_run_no_execution_no_ledger_write.py \
		--approved-paper-position-monitor-dry-run \
		--no-execution \
		--no-ledger-write \
		--one-shot

paper-position-monitor-dry-run-qa-audit: ## Read-only QA for paper position monitor dry-run
	venv/bin/python scripts/research/audit_paper_position_monitor_dry_run_qa.py

paper-position-monitor-after-refresh-qa-audit: ## Read-only QA for monitor after refresh dry-run
	venv/bin/python scripts/research/audit_paper_position_monitor_after_refresh_qa.py

bounded-paper-controller-auto-ledger-start: ## Start bounded paper trading controller (paper-only auto ledger)
	bash scripts/bounded_paper_trading_controller_ctl.sh start

bounded-paper-controller-auto-ledger-status: ## Show bounded paper controller status
	bash scripts/bounded_paper_trading_controller_ctl.sh status

bounded-paper-controller-auto-ledger-tail: ## Tail bounded paper controller log
	bash scripts/bounded_paper_trading_controller_ctl.sh tail

bounded-paper-controller-auto-ledger-stop: ## Stop bounded paper trading controller
	bash scripts/bounded_paper_trading_controller_ctl.sh stop

intrabar-feed-start: ## Start paper-only Binance intrabar/minute feed (does not touch M15 canonical feed)
	bash scripts/intrabar_feed_ctl.sh start

intrabar-feed-stop: ## Stop paper-only intrabar feed
	bash scripts/intrabar_feed_ctl.sh stop

intrabar-feed-status: ## Status of paper-only intrabar feed
	bash scripts/intrabar_feed_ctl.sh status

intrabar-feed-tail: ## Tail paper-only intrabar feed log
	bash scripts/intrabar_feed_ctl.sh tail

intrabar-feed-healthcheck: ## Pass/fail freshness+process health for paper-only intrabar feed
	bash scripts/intrabar_feed_ctl.sh healthcheck

intrabar-feed-restart: ## Stop then start intrabar feed; print status (exactly one process)
	bash scripts/intrabar_feed_ctl.sh restart

intrabar-feed-supervisor-start: ## Start paper-only intrabar feed supervisor (does not touch controller)
	bash scripts/intrabar_feed_supervisor_ctl.sh start

intrabar-feed-supervisor-stop: ## Stop paper-only intrabar feed supervisor
	bash scripts/intrabar_feed_supervisor_ctl.sh stop

intrabar-feed-supervisor-status: ## Status of paper-only intrabar feed supervisor
	bash scripts/intrabar_feed_supervisor_ctl.sh status

intrabar-feed-supervisor-restart: ## Restart paper-only intrabar feed supervisor
	bash scripts/intrabar_feed_supervisor_ctl.sh restart

bounded-paper-controller-auto-ledger-repair-duplicates: ## Terminate orphan/duplicate controller PIDs; keep canonical
	bash scripts/bounded_paper_trading_controller_ctl.sh repair-duplicates

bounded-paper-controller-duplicate-process-repair-qa: ## QA after duplicate process repair (no ledger write)
	venv/bin/python scripts/research/audit_bounded_paper_controller_duplicate_process_repair_qa.py

bounded-paper-controller-runtime-stability-qa: ## Read-only runtime stability QA (no stop/restart)
	venv/bin/python scripts/research/audit_bounded_paper_controller_runtime_stability_qa.py

context-visual-stack-start: ## Start visual viewer :8765 + visual-only refresher (no controller touch)
	bash scripts/context_visual_stack_ctl.sh start

context-visual-stack-stop: ## Stop visual viewer + refresher only (controller untouched)
	bash scripts/context_visual_stack_ctl.sh stop

context-visual-stack-restart: ## Restart visual stack only (no paper controller / no ledger write)
	bash scripts/context_visual_stack_ctl.sh restart

context-visual-stack-status: ## Status of visual viewer + refresher
	bash scripts/context_visual_stack_ctl.sh status

context-visual-stack-tail: ## Tail visual refresher / viewer logs
	bash scripts/context_visual_stack_ctl.sh tail

visual-trade-panel-qa-audit: ## Read-only QA audit for Visual Trade Panel design dry-run
	venv/bin/python scripts/research/audit_visual_trade_panel_qa.py

single-live-context-refresh-append-qa-audit: ## Read-only QA for approved single live refresh+append
	venv/bin/python scripts/research/audit_single_live_context_refresh_append_qa.py
