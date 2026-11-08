# Architecture source / owner / IO index — 071126

Documentation revision08Nov2026. These are implemented routes, not a statement that current signals, S0/S1 or PAPER entry are qualified. Immutable backup manifest: `6f603ed5e9f68c8e9033a01e773509e684a884828577b1abf7443aa4587ec93f`.

## 1 — SYSTEM CONTEXT · C4 L1

PAPER is simulated execution. Market observation, technical health and entry permission are distinct.

| Block | Owner | Input → processing → output | Consumer | Source keys |
|---|---|---|---|---|
| spot / BINANCE SPOT · BTCUSDT | external exchange | Spot market → Distinct source domains → kline / aggTrade / bookTicker | 14 Docker services | feed, Spot transport, Intrabar Cognition |
| futures / BINANCE FUTURES · BTCUSDT | external exchange | Futures market → REST snapshots + execution WSS → trades / aggTrade / BBO | 14 Docker services | native-flow, paper-runner |
| system / BTC-ML · RELEASE 071126 | 14 Docker services | Spot + Futures; original source clocks → Ingest / Canonical / contexts / decisions / PAPER → Owned generations, commands, PAPER state | existing owners, dashboard-ui + ops-api, paper-manager, existing execution guard | canonical, Publisher, Paper engine |
| state / PERSISTED STATE | existing owners | RAW, features, context, decision, financial state → Original IDs, availability and provenance → Private volumes + bound R08 runtime | none current | Recorder storage, Journal V3, Financial authority |
| monitor / DASHBOARD + CHART / OPS API | dashboard-ui + ops-api | Owner publications and process status → Read-only projections; no fabricated trade → Operator observations | system owner | nginx, api, api-chart |
| paper / PAPER OUTPUTS | paper-manager | Admitted commands and genuine market prices → Risk / costs / positions / SL / TP / CLOSE → Books, receipts, outcomes, reasons | none current | Paper engine, Risk/economics, Financial authority |
| real / REAL EXECUTION DISABLED | existing execution guard | REAL_EXECUTION_ENABLED=false → No REAL route activated by this task → No live exchange orders | none current | own-inputs |
| operator / OPERATOR | system owner | Dashboard / Chart / technical API views → Read system and PAPER observations → Human observation; no automatic REAL route | none current | nginx, ui |

| Edge | From → to | Payload / transport / trigger | Source keys |
|---|---|---|---|
| 01E01 | spot → system | Spot observations / WSS native/combined JSON / source messages | feed, Spot transport, Intrabar Cognition |
| 01E02 | futures → system | Futures observations / REST JSON / WSS JSON / native polling / source messages | native-flow, paper-runner |
| 01E03 | system → state | Owner writes / durable RAW; Parquet / JSON / Journal V3 / native commit/publication | Recorder storage, Journal V3, Financial authority |
| 01E04 | system → monitor | Context and technical status / HTTP JSON + visual projection files / UI/API poll; visual input changes | nginx, api, Visual projection |
| 01E05 | system → paper | Existing PAPER decisions / CommandBus Parquet + financial commit / OPEN / HOLD / CLOSE / NO_ACTION | CommandBus, Paper engine |
| 01E06 | system → real | REAL remains forbidden / existing config + guard / all execution attempts | own-inputs |
| 01E07 | monitor → operator | Context / PAPER / technical views / browser HTTP / WS / JSON / operator read-only requests | nginx, ui |

## 2 — ALL 14 CONTAINERS · C4 L2

R08 is a Paper child, not a fifteenth service. Diagram arrows describe implemented IO, not current freshness.

| Block | Owner | Input → processing → output | Consumer | Source keys |
|---|---|---|---|---|
| spot / BINANCE SPOT · BTCUSDT | external exchange | Spot market → Distinct source domains → kline / aggTrade / bookTicker | collector-watchdog, cognition-runtime, paper-manager (one child) | feed, Spot transport, Intrabar Cognition |
| futures / BINANCE FUTURES · BTCUSDT | external exchange | Futures market → REST snapshots + execution WSS → trades / aggTrade / BBO | legacy-multi-exchange, paper-manager | native-flow, paper-runner |
| canonical-runtime / btcml-vps-smoke-canonical-runtime-1 | canonical-runtime | Watchdog feed и native Legacy outputs; после входной проверки dependency guard → Последовательный Stage1/Stage2 pipeline, run.py → runtime/pipeline.py → cognition/*.parquet, runtime_engine_state, availability/metadata | context-refresh-daemon | canonical, legacy-input, volume-response |
| context-refresh-daemon / btcml-vps-smoke-context-refresh-daemon-1 | context-refresh-daemon | Пригодные собственные native frames и Stage2 evidence; admission и source pins → Publisher Final/Lifecycle/Context Phase четырёх TF; один causal child → live/primary_context_publication.json, live/context_refresh_daemon_status.json; own-TF Final/Lifecycle, phase generations | cognition-runtime, timeframe-manager, context-refresher | Publisher, pub-daemon |
| context-refresher / btcml-vps-smoke-context-refresher-1 | context-refresher | Опубликованные Final/Lifecycle/trade/phase источники; /profile — диагностика → Подготовка read-only visual projections из owner outputs → visual public volume; /profile diagnostics | dashboard-ui | Visual projection |
| legacy-volume-memory / btcml-vps-smoke-legacy-volume-memory-1 | legacy-volume-memory | multi_exchange_flow + volume_clusters; own history → Native Memory/Regime pair под IO wrapper → /legacy native Memory/Regime parquet и /legacy/ops provenance | canonical-runtime | memory, regime |
| legacy-volume-reactions / btcml-vps-smoke-legacy-volume-reactions-1 | legacy-volume-reactions | Текущий multi_exchange_flow snapshot из /legacy → Native Reactions/Acceptance pair → /legacy native Reactions/Acceptance и /legacy/ops | canonical-runtime | reactions, acceptance |
| legacy-volume-clusters / btcml-vps-smoke-legacy-volume-clusters-1 | legacy-volume-clusters | /legacy multi_exchange_flow + проверенные native source pins → Native Clusters/Inventory pair с текущим pass-local snapshot reuse → /legacy native Clusters/Inventory + ops capture/published metadata | legacy-volume-memory, canonical-runtime | clusters, inventory |
| legacy-multi-exchange / btcml-vps-smoke-legacy-multi-exchange-1 | legacy-multi-exchange | Реальные соединения сборщика; точные endpoints в сохранённом source → Сборщик multi-exchange flow под IO runtime → /legacy multi_exchange_flow parquet, ops source evidence | legacy-volume-clusters, legacy-volume-memory, legacy-volume-reactions | native-flow |
| dashboard-ui / btcml-vps-smoke-dashboard-ui-1 | dashboard-ui | Статика image, /visual-data RO, /release/manifest.json RO, внутренний ops-api → Один nginx: Dashboard + встроенный Market Context/legacy Chart → 127.0.0.1:15173; :18765 только Chart static/GET projection | none current | nginx, ui |
| ops-api / btcml-vps-smoke-ops-api-1 | ops-api | Data/visual RO, release manifest RO, Docker socket RO и действующий socket GID → Read-only FastAPI/WS транспорт owner данных и bounded Docker GET telemetry → 127.0.0.1:18080; health/runtime/chart projections | dashboard-ui | api, api-chart |
| collector-watchdog / btcml-vps-smoke-collector-watchdog-1 | collector-watchdog | Сохранённая конфигурация collectors; в P0 фактически работал live_binance_feed_v2 child → Watchdog штатных required collectors → Feed parquet, collector heartbeats и штатные logs | canonical-runtime, context-refresh-daemon | registry, feed |
| cognition-runtime / btcml-vps-smoke-cognition-runtime-1 | cognition-runtime | Spot BTCUSDT aggTrade/bookTicker; нормализация source/session/receive metadata → LIVE1A Spot stream, архив raw_event_journal и provisional cognition → raw_market_events_v2; cognition/intrabar_context_events; runtime/intrabar_cognition_health.json | context-refresher, ops-api | Intrabar Cognition, Closed-bar bridge |
| paper-manager / btcml-vps-smoke-paper-manager-1 | paper-manager | Native books/epoch, историческая provenance + выбранный release pins, действительные bindings, свежие Futures и BBO → Единственный Paper writer; Futures receive, WAL/ACK, исполнение/сопровождение; штатный R08 child → Paper WAL/checkpoints/books/financial heads, health и owner projections; /r08 producer outputs | ops-api, paper-manager (one child) | paper-runner, Paper engine |
| timeframe-manager / btcml-vps-smoke-timeframe-manager-1 | timeframe-manager | Собственные M15/M30/H1/H4 контексты, phase/strength, Paper state и genuine source bindings → Четыре независимых TF decisions → CommandBus → trading/manager/*, timeframe_command_memory, timeframe_manager_latest/health | paper-manager | Manager daemon, own-inputs, state-adapter |
| intrabar-supervisor / btcml-vps-smoke-intrabar-supervisor-1 | intrabar-supervisor | Paper/Timeframe owner health, control/config и shared runtime state → Существующий supervisor/наблюдатель execution служб → runtime/intrabar_supervision_state.json и штатные журналы | paper-manager, timeframe-manager, cognition-runtime | supervisor |
| r08 / R08 CHILD · inside Paper | paper-manager (one child) | Spot aggTrade + own-TF kline close; Context/policy → Recorder ACK -> worker -> provider -> R08 → Prefix; frozen INIT; descriptor/source bindings | timeframe-manager | R08 child owner, Recorder, R08 adapter/handoff, Baseline provider |

| Edge | From → to | Payload / transport / trigger | Source keys |
|---|---|---|---|
| 02E01 | spot → collector-watchdog | Spot OHLCV / kline_15m WSS JSON / native updates | feed |
| 02E02 | spot → cognition-runtime | Spot event-time observations / combined aggTrade/bookTicker JSON / each received message | Intrabar Cognition |
| 02E03 | spot → r08 | Genuine Spot contributors + closes / combined WSS JSON / each original receive | Spot transport, R08 adapter/handoff |
| 02E04 | futures → legacy-multi-exchange | Futures trade snapshots / fapi REST JSON -> Parquet / native 5s save interval | native-flow |
| 02E05 | futures → paper-manager | Execution market / Futures aggTrade + bookTicker WSS / each received message | paper-runner |
| 02E06 | legacy-multi-exchange → legacy-volume-clusters | Native flow snapshot / /legacy/multi_exchange_flow.parquet / native pair loops | clusters, inventory |
| 02E07 | legacy-multi-exchange → legacy-volume-memory | Native flow snapshot / shared /legacy Parquet / native pair loops | memory, regime |
| 02E08 | legacy-multi-exchange → legacy-volume-reactions | Native flow snapshot / shared /legacy Parquet / native pair loops | reactions, acceptance |
| 02E09 | legacy-volume-clusters → legacy-volume-memory | Volume clusters / /legacy/volume_clusters.parquet / Memory native read | memory |
| 02E10 | collector-watchdog → canonical-runtime | Spot OHLCV history / data/live Parquet + partitions / dependency-ready engine pass | feed-paths, canonical |
| 02E11 | legacy-volume-reactions → canonical-runtime | Admitted native reactions / Legacy source adapter + receipt / input availability guard | legacy-input, volume-response |
| 02E12 | legacy-volume-clusters → canonical-runtime | Native Inventory publications / Legacy adapter / cognitive extension / native admitted snapshot | legacy-input, canonical |
| 02E13 | legacy-volume-memory → canonical-runtime | Regime publication; Memory remains native history / Legacy adapter / cognitive extension / native admitted snapshot | legacy-input, canonical |
| 02E14 | canonical-runtime → context-refresh-daemon | Candle/response/convergence/cognition inputs / seven INPUTS + frozen native snapshot / one daemon child; interval900s | Publisher, pub-daemon |
| 02E15 | collector-watchdog → context-refresh-daemon | Closed market inputs / live_market_feed.parquet / safe-close dependency | Publisher |
| 02E16 | context-refresh-daemon → cognition-runtime | Closed own-TF contexts / ClosedBarContextEventBridge / new admitted generation | Closed-bar bridge |
| 02E17 | context-refresh-daemon → timeframe-manager | Own Final / Lifecycle / Phase / Parquet + owner publications / manager configured60s cycle | own-inputs, state-adapter |
| 02E18 | context-refresh-daemon → context-refresher | Own-TF context generations / Final/Lifecycle Parquet / configured20s; skip unchanged | Visual projection |
| 02E19 | cognition-runtime → context-refresher | Provisional observation / intrabar_cognition_health.json / read-only projection | Visual projection |
| 02E20 | r08 → timeframe-manager | Committed source/evidence bindings / /r08 descriptor + JournalV3 / published INIT; reader refresh | own-inputs, R08 direct source |
| 02E21 | timeframe-manager → paper-manager | Own-TF commands / timeframe_command_memory.parquet / new command_id; own cursor | CommandBus, consumer |
| 02E22 | context-refresher → dashboard-ui | Visual/chart payloads / shared visual volume /visual-data / new projection; HTTP GET | nginx, Visual projection |
| 02E23 | ops-api → dashboard-ui | Read-only API / WS / health / nginx reverse proxy -> ops-api:8080 / browser/API requests | nginx, api |
| 02E24 | paper-manager → ops-api | Health, financial and position status / shared data; read-only API / owner committed output | api, Paper engine |
| 02E25 | cognition-runtime → ops-api | Cognition health / CTX journal / owner files; read-only API / API observation | api |
| 02E26 | paper-manager → r08 | Launch existing child / same process namespace; no new service / native bootstrap gates | R08 child owner |
| 02E27 | intrabar-supervisor → paper-manager | Observe Compose-owned role / health / PID / heartbeat / existing supervision loop | supervisor, api |
| 02E28 | intrabar-supervisor → timeframe-manager | Observe Compose-owned role / health / PID / heartbeat / existing supervision loop | supervisor, api |
| 02E29 | intrabar-supervisor → cognition-runtime | Observe Compose-owned role / health / PID / heartbeat / existing supervision loop | supervisor, api |

## 3 — STAGE1 · SOURCE AND DERIVATION DFD

Spot OHLCV proxies and native Futures flow remain separate. Canonical order is the actual 28-engine registry.

| Block | Owner | Input → processing → output | Consumer | Source keys |
|---|---|---|---|---|
| spot / BINANCE SPOT · BTCUSDT | external exchange | Spot market → Distinct source domains → kline / aggTrade / bookTicker | collector-watchdog | feed, Spot transport, Intrabar Cognition |
| futures / BINANCE FUTURES · BTCUSDT | external exchange | Futures market → REST snapshots + execution WSS → trades / aggTrade / BBO | legacy-multi-exchange | native-flow, paper-runner |
| flow / FUTURES NATIVE FLOW | legacy-multi-exchange | Futures REST trades → buy/sell/delta/count/efficiency snapshots → multi_exchange_flow.parquet | legacy-volume-clusters, legacy-volume-memory, legacy-volume-reactions | native-flow |
| clusters / CLUSTERS + INVENTORY | legacy-volume-clusters | flow snapshot + own history → Unchanged native engines; admitted IO → volume_clusters / inventory_states | legacy-volume-memory, canonical-runtime | clusters, inventory |
| memory / MEMORY + REGIME | legacy-volume-memory | flow + clusters + own history → Unchanged native engines; admitted IO → volume_memory / regime_history | canonical-runtime | memory, regime |
| react / REACTIONS + ACCEPTANCE | legacy-volume-reactions | flow snapshot + own history → Unchanged native engines; admitted IO → volume_reactions / acceptance_states | canonical-runtime | reactions, acceptance |
| feed / SPOT OHLCV INGRESS | collector-watchdog | Spot kline_15m updates → Canonical snapshot + daily partitions → data/live/live_market_feed.parquet | canonical-runtime | registry, feed, feed-paths |
| candle / CANDLE / LOCALIZATION / VOLUME | canonical-runtime | Spot OHLCV → Candle structure; geometry; localization; volume classification → candle_structure / volume_localization / volume_classification | canonical-runtime, canonical-runtime | canonical |
| guard / NATIVE SOURCE AVAILABILITY | canonical-runtime | Legacy publication + original metadata → read_consumer_source / read_available_source → Admitted snapshot or BLOCKED | canonical-runtime | legacy-input, volume-response |
| response / BEHAVIOR / RESPONSE / CONVERGENCE | canonical-runtime | Candle/localization + admitted reactions → Behavioral memory; volume response; climatic and auction convergence → volume_response_state; auction_convergence_memory | canonical-runtime | canonical, volume-response |
| synth / FLOW / LIQUIDITY / HTF / SYNTHESIS | canonical-runtime | Own Spot derived features + prior engine results → Live flow -> clusters -> interaction; HTF structure/context -> synthesis → auction_synthesis_memory + context-related outputs | canonical-runtime | canonical |
| out / CANONICAL OUTPUT GENERATIONS | canonical-runtime | Ordered successful engine results → Runtime guard + owner publication metadata → Stage2/cognition + MTF availability; Publisher inputs | none current | canonical |

| Edge | From → to | Payload / transport / trigger | Source keys |
|---|---|---|---|
| 03E01 | futures → flow | Futures trades / REST JSON / native poll | native-flow |
| 03E02 | flow → clusters | Flow snapshot / Parquet + native publication / native30/60s loops | clusters, inventory |
| 03E03 | flow → memory | Flow snapshot / Parquet + native publication / native30/60s loops | memory, regime |
| 03E04 | flow → react | Flow snapshot / Parquet + native publication / native30/60s loops | reactions, acceptance |
| 03E05 | clusters → memory | Cluster profile / volume_clusters.parquet / native Memory read | memory |
| 03E06 | clusters → guard | Inventory generation / Parquet + receipt/availability metadata / consumer evaluation cutoff | legacy-input |
| 03E07 | memory → guard | Regime generation; Memory stays native history / Parquet + receipt/availability metadata / consumer evaluation cutoff | legacy-input |
| 03E08 | react → guard | Reactions / Acceptance generation / Parquet + receipt/availability metadata / consumer evaluation cutoff | legacy-input |
| 03E09 | spot → feed | Spot candle updates / kline_15m WSS JSON / source update | feed |
| 03E10 | feed → candle | OHLCV history / Parquet / partitions / dependency-ready pass | feed-paths, canonical |
| 03E11 | candle → response | Own derived measurements / canonical Parquet outputs / pipeline order | canonical |
| 03E12 | guard → response | Admitted reactions / behavioral inputs / source-bound reader / not future/backdated | volume-response, legacy-input |
| 03E13 | candle → synth | Own localization / flow / HTF inputs / canonical Parquet / registered producer order | canonical |
| 03E14 | response → synth | Response and convergence / canonical memory files / registered producer order | canonical |
| 03E15 | synth → out | Synthesis then registered cognition stages / owner generations / native sequential guard | canonical |

## 4 — STAGE2 / CONTEXT / R08 / ADMISSION

Intrabar observations do not replace closed-bar S4.1 entry authority. R08 is evidence, never an artificial trading signal.

| Block | Owner | Input → processing → output | Consumer | Source keys |
|---|---|---|---|---|
| canon / CANONICAL STAGE2 / COGNITION | canonical-runtime | Stage1 derived features → Registered Stage2/runtime/intermediate/meta-cognition → cognition and availability generations | context-refresh-daemon | canonical |
| freeze / PUBLISHER SOURCE SNAPSHOT | context-refresh-daemon | Seven market/cognition INPUTS + native frames → Stage/freeze/pin before classifiers → Immutable per-pass inputs + source pins | context-refresh-daemon | Publisher, native-stage2 |
| auction / NATIVE AUCTION / OWN CONTEXT BUILD | context-refresh-daemon | Pinned closed-bar inputs → Native Auction; own Cognitive; own Final → Auction/Cognitive/Final generations | context-refresh-daemon, context-refresh-daemon | Publisher, m15-boundary, higher-tf |
| shadow / PRIVATE SEPTEMBER BOUNDARY | context-refresh-daemon | Existing M15 Auction history + prior boundary → Private shadow reconstruction; not published old history → New causal suffix, with original provenance | context-refresh-daemon | m15-boundary |
| life / LIFECYCLE + STAGE2 CONCLUSIONS | context-refresh-daemon | Own Final; admitted predecision Stage2 evidence → Own process continuity and episode transitions → Lifecycle + stage2 consumption evidence | context-refresh-daemon | Lifecycle, native-stage2, m15-boundary |
| phase / CONTEXT PHASE / OWNER RELEASE | context-refresh-daemon | Own Lifecycle/native history + predecision evidence → Publish own-TF generation after required checks → Final / Lifecycle / Context Phase publications | cognition-runtime, Paper child / existing reducers, timeframe-manager | Context Phase, Publisher, higher-tf |
| intrabar / INTRABAR COGNITION (PARALLEL) | cognition-runtime | Independent Spot aggTrade/BBO; admitted closed contexts → Event-time bars; provisional synthesis/lifecycle → CTX events + provisional health | none current | Intrabar Cognition, Cognition Pipeline, Closed-bar bridge |
| r08 / R08 + DRA / R2 | Paper child / existing reducers | Genuine Spot; frozen300s baseline; Context; predecessor → Existing A/B/R -> economic evidence -> C_E/C_P projections → Committed source/evidence; qualification remains explicit | timeframe-manager | R08 ResearchSystem, R08 evidence, Journal V3 |
| trend / TREND / LIVING PROCESS INTEGRATION | timeframe-manager | Own Final/Lifecycle process_strength + Phase + R08 metadata → Read existing numeric strength; bind own lineage → Separate metadata; no new numeric formula or permission | Timeframe Manager + Paper | Trend Strength integration, own-inputs |
| gate / EXISTING DECISION / OPEN GUARDS | Timeframe Manager + Paper | Source/descriptor/policy; market freshness; qualification → Missing technical input = BLOCKED; valid market wait = NO_ACTION → Only existing conditions can permit PAPER OPEN | none current | Entry conditions, Timeframe Manager, Paper engine |

| Edge | From → to | Payload / transport / trigger | Source keys |
|---|---|---|---|
| 04E01 | canon → freeze | Candle/response/convergence/cognition / seven frozen INPUTS / Publisher native pass | Publisher |
| 04E02 | freeze → auction | Pinned source frames / NativeSourcePass + exact SHA / before classification | Publisher, native-stage2 |
| 04E03 | auction → shadow | M15 causal boundary work / private staging tree / own M15 build | m15-boundary |
| 04E04 | auction → life | Own Final and admitted conclusions / Parquet + stage2 predecision reader / own generation | Lifecycle, m15-boundary |
| 04E05 | shadow → life | New M15 suffix; legacy prefix frozen / same original classifiers / boundary-preserving append | m15-boundary |
| 04E06 | life → phase | Own process evidence / source-bound publications / complete own TF | Publisher, Context Phase |
| 04E07 | phase → intrabar | Closed contexts / ClosedBarContextEventBridge / new admitted closed bar | Closed-bar bridge |
| 04E08 | phase → r08 | Real own-TF Context references / existing Context/source binding / available before required initiative | R08 child owner, R08 evidence |
| 04E09 | phase → trend | Own strength / phase / published Final/Lifecycle/Phase / manager read | Trend Strength integration, own-inputs |
| 04E10 | r08 → trend | Committed DRA/R2 lineage metadata / JournalV3 + descriptor / direct reader / source refresh | R08 direct source, own-inputs |
| 04E11 | trend → gate | Separate trend metadata / existing controller input / existing decision evaluation | Trend Strength integration, Timeframe Manager |

## 5 — FOUR INDEPENDENT TIMEFRAME CONTEXTS

Higher bars may resample closed M15 OHLCV; M15 Final/Lifecycle is never substituted for a higher-TF classification. CTX ID is not trade ID.

| Block | Owner | Input → processing → output | Consumer | Source keys |
|---|---|---|---|---|
| market / CLOSED MARKET + NATIVE INPUTS | existing owners | Spot OHLCV + admitted source generations → Own cutoff / availability → Own-TF classifier inputs | M15 classifier owner, M30 classifier owner, H1 classifier owner, H4 classifier owner | Publisher, higher-tf |
| manager / TIMEFRAME MANAGER | timeframe-manager | Own Final/Lifecycle/Phase + source metadata → Independent M15 / M30 / H1 / H4 evaluation → Commands, not fills or positions | none current | own-inputs, state-adapter, Timeframe Manager |
| m15bar / M15 · OWN CLOSED BAR | M15 classifier owner | Own market range and source cutoff → 900s bar; real boundaries → Own completed-bar generation | context-refresh-daemon | higher-tf, Publisher |
| m15final / M15 · FINAL | context-refresh-daemon | Own Auction/Cognitive inputs → Original Final classifier → Own final_market_context_memory.parquet | context-refresh-daemon | Final Context, higher-tf |
| m15life / M15 · LIFECYCLE | context-refresh-daemon | Own consecutive Final + Stage2 conclusions → Original process and episode reducer → Own lifecycle, episode, strength | own publication / integration | Lifecycle, higher-tf |
| m15phase / M15 · TREND / PHASE | own publication / integration | Own Lifecycle process_strength + native evidence → Existing numeric strength + qualified Phase → Own-TF publication + availability | timeframe-manager | Context Phase, Trend Strength integration |
| m30bar / M30 · OWN CLOSED BAR | M30 classifier owner | Own market range and source cutoff → 1800s bar; real boundaries → Own completed-bar generation | context-refresh-daemon | higher-tf, Publisher |
| m30final / M30 · FINAL | context-refresh-daemon | Own Auction/Cognitive inputs → Original Final classifier → Own final_market_context_memory.parquet | context-refresh-daemon | Final Context, higher-tf |
| m30life / M30 · LIFECYCLE | context-refresh-daemon | Own consecutive Final + Stage2 conclusions → Original process and episode reducer → Own lifecycle, episode, strength | own publication / integration | Lifecycle, higher-tf |
| m30phase / M30 · TREND / PHASE | own publication / integration | Own Lifecycle process_strength + native evidence → Existing numeric strength + qualified Phase → Own-TF publication + availability | timeframe-manager | Context Phase, Trend Strength integration |
| h1bar / H1 · OWN CLOSED BAR | H1 classifier owner | Own market range and source cutoff → 3600s bar; real boundaries → Own completed-bar generation | context-refresh-daemon | higher-tf, Publisher |
| h1final / H1 · FINAL | context-refresh-daemon | Own Auction/Cognitive inputs → Original Final classifier → Own final_market_context_memory.parquet | context-refresh-daemon | Final Context, higher-tf |
| h1life / H1 · LIFECYCLE | context-refresh-daemon | Own consecutive Final + Stage2 conclusions → Original process and episode reducer → Own lifecycle, episode, strength | own publication / integration | Lifecycle, higher-tf |
| h1phase / H1 · TREND / PHASE | own publication / integration | Own Lifecycle process_strength + native evidence → Existing numeric strength + qualified Phase → Own-TF publication + availability | timeframe-manager | Context Phase, Trend Strength integration |
| h4bar / H4 · OWN CLOSED BAR | H4 classifier owner | Own market range and source cutoff → 14400s bar; real boundaries → Own completed-bar generation | context-refresh-daemon | higher-tf, Publisher |
| h4final / H4 · FINAL | context-refresh-daemon | Own Auction/Cognitive inputs → Original Final classifier → Own final_market_context_memory.parquet | context-refresh-daemon | Final Context, higher-tf |
| h4life / H4 · LIFECYCLE | context-refresh-daemon | Own consecutive Final + Stage2 conclusions → Original process and episode reducer → Own lifecycle, episode, strength | own publication / integration | Lifecycle, higher-tf |
| h4phase / H4 · TREND / PHASE | own publication / integration | Own Lifecycle process_strength + native evidence → Existing numeric strength + qualified Phase → Own-TF publication + availability | timeframe-manager | Context Phase, Trend Strength integration |
| close / SPOT KLINE CLOSE · FOUR OWN TF | Binance Spot / Paper transport | Exact15m /30m /1h /4h stream → Original k.x=true and receive receipt; no D1 → Native close message, not trade q | Paper adapter / ResearchSystem | Spot transport, R08 adapter/handoff |
| seal / R08 OWN-TF COVERAGE SEAL | Paper adapter / ResearchSystem | Exact closed bar + actual local session coverage → Match TF/bar; partial initial bar is not sealed → Committed own-TF watermark or WAITING_FOR_COVERAGE | timeframe-manager | R08 adapter/handoff, R08 ResearchSystem |

| Edge | From → to | Payload / transport / trigger | Source keys |
|---|---|---|---|
| 05E01 | market → m15bar | Own-TF bars / closed OHLCV / admitted source frames / new own close | higher-tf, Publisher |
| 05E02 | m15bar → m15final | Own completed input / own-TF classifier input / own generation | higher-tf, Final Context |
| 05E03 | m15final → m15life | Own context rows / own TF Parquet / new accepted Final | Lifecycle, higher-tf |
| 05E04 | m15life → m15phase | Own process/evidence / Lifecycle + phase publication / native owner release | Context Phase |
| 05E05 | m15phase → manager | Own-TF context lineage / M15 root / higher data/cognition/timeframes/TF / configured60s reader; original availability | own-inputs, state-adapter |
| 05E06 | market → m30bar | Own-TF bars / closed OHLCV / admitted source frames / new own close | higher-tf, Publisher |
| 05E07 | m30bar → m30final | Own completed input / own-TF classifier input / own generation | higher-tf, Final Context |
| 05E08 | m30final → m30life | Own context rows / own TF Parquet / new accepted Final | Lifecycle, higher-tf |
| 05E09 | m30life → m30phase | Own process/evidence / Lifecycle + phase publication / native owner release | Context Phase |
| 05E10 | m30phase → manager | Own-TF context lineage / M15 root / higher data/cognition/timeframes/TF / configured60s reader; original availability | own-inputs, state-adapter |
| 05E11 | market → h1bar | Own-TF bars / closed OHLCV / admitted source frames / new own close | higher-tf, Publisher |
| 05E12 | h1bar → h1final | Own completed input / own-TF classifier input / own generation | higher-tf, Final Context |
| 05E13 | h1final → h1life | Own context rows / own TF Parquet / new accepted Final | Lifecycle, higher-tf |
| 05E14 | h1life → h1phase | Own process/evidence / Lifecycle + phase publication / native owner release | Context Phase |
| 05E15 | h1phase → manager | Own-TF context lineage / M15 root / higher data/cognition/timeframes/TF / configured60s reader; original availability | own-inputs, state-adapter |
| 05E16 | market → h4bar | Own-TF bars / closed OHLCV / admitted source frames / new own close | higher-tf, Publisher |
| 05E17 | h4bar → h4final | Own completed input / own-TF classifier input / own generation | higher-tf, Final Context |
| 05E18 | h4final → h4life | Own context rows / own TF Parquet / new accepted Final | Lifecycle, higher-tf |
| 05E19 | h4life → h4phase | Own process/evidence / Lifecycle + phase publication / native owner release | Context Phase |
| 05E20 | h4phase → manager | Own-TF context lineage / M15 root / higher data/cognition/timeframes/TF / configured60s reader; original availability | own-inputs, state-adapter |
| 05E21 | close → seal | Actual matching close + receive receipt / Spot WSS kline JSON + existing coverage / when both close and required coverage available | R08 adapter/handoff |
| 05E22 | seal → manager | Committed own-TF trend lineage only / existing Journal / descriptor reader / native refresh; never a fake permission | own-inputs, R08 direct source |

## 6 — TRADING DECISION / COMMAND / PAPER EXECUTION

Context != signal != position != execution. Intrabar Supervisor observes Compose-owned processes; Paper owns fills and protection.

| Block | Owner | Input → processing → output | Consumer | Source keys |
|---|---|---|---|---|
| context / OWN CONTEXT OWNERS | Publisher / existing readers | Own Final/Lifecycle/Phase + availability → Closed-bar S4.1 inputs; no provisional replacement → Own M15/M30/H1/H4 context state | timeframe-manager | own-inputs, state-adapter |
| gate / ADMISSION / READINESS | existing guards | Descriptor/source/permission; release pins; fresh market → Keep BLOCKED / STALE separate from market OBSERVE → Existing entry permission or exact reason | timeframe-manager | Admission release/provenance, Entry conditions, own-inputs |
| manager / TIMEFRAME MANAGER | timeframe-manager | Own context + positions/risk + trend metadata → Original OPEN/HOLD/CLOSE/NO_ACTION rules → Deterministic own-TF command_id | timeframe-manager | Timeframe Manager, Manager daemon |
| bus / COMMANDBUS | timeframe-manager | New commands → Immutable logical prefix; deterministic ID dedupe → timeframe_command_memory.parquet | Paper child / single writer | CommandBus |
| consume / OWN-TF COMMAND CONSUMER | Paper child / single writer | CommandBus + own cursor + TTL/source/risk contracts → Reject stale/duplicate/unowned commands → Exactly-once effect path; cursor checkpoint | paper-manager | consumer, Paper engine |
| market / FUTURES EXECUTION MARKET | Paper transport/WAL | Futures aggTrade + BBO → Durable WAL and current fresh-price guards → Original market events / BBO / gaps state | paper-manager | paper-runner, Execution WAL, Execution checkpoint |
| paper / PAPER ENGINE / POSITION MANAGEMENT | paper-manager | Valid command + original market + existing position → Risk sizing; fees/slippage; SL/TP; intrabar HOLD/CLOSE → Committed PAPER positions/trades/reasons | existing financial authority, intrabar-supervisor + OPS/UI | Paper engine, Risk/economics, Financial authority |
| financial / FINANCIAL COMMIT / BOOKS | existing financial authority | Paper effect + costs + position identity → Original generation/receipt/order and accounting → Position/trade books; financial generation | S41CommandConsumer, timeframe-manager, intrabar-supervisor + OPS/UI | Financial authority |
| ack / COMMAND CURSOR / ACK | S41CommandConsumer | Committed effect / native disposition → Do not repeat command effects → s41_command_cursor.json and native receipts | none current | consumer |
| observe / INTRABAR SUPERVISOR / DASHBOARD | intrabar-supervisor + OPS/UI | Process heartbeat and owner outputs → Compose-owned observation; no second writer → Technical status / read-only views | none current | supervisor, api, nginx |

| Edge | From → to | Payload / transport / trigger | Source keys |
|---|---|---|---|
| 06E01 | context → manager | Own context state / own-TF Parquet / publication / configured60s evaluation | own-inputs, Manager daemon |
| 06E02 | gate → manager | Existing readiness/entry decision / explicit configured bindings / before applicable OPEN | own-inputs, Timeframe Manager |
| 06E03 | manager → bus | OPEN_LONG / OPEN_SHORT / HOLD / CLOSE / NO_ACTION / atomic Parquet command rows / new deterministic command_id | CommandBus, Manager daemon |
| 06E04 | bus → consume | Own-TF commands / CommandBus Parquet / consumer polling; own cursor | consumer |
| 06E05 | consume → paper | Validated command / apply_s41_manager_command / one effect per admitted command | consumer, Paper engine |
| 06E06 | market → paper | Current executable market observations / Futures WAL / BBO / continuous protective handling | Paper engine, paper-runner |
| 06E07 | paper → financial | Effect + costs + CLOSE accounting / native financial transaction / existing durability order | Financial authority, Paper engine |
| 06E08 | financial → ack | Effect already committed / native consumer checkpoint/disposition / commit before acknowledgement | consumer, Financial authority |
| 06E09 | financial → manager | Current position/risk view / existing authoritative books / manager evaluation | Timeframe Manager, Financial authority |
| 06E10 | financial → observe | Committed outcome/position state / read-only owner publications / API snapshot | api, Paper engine |
| 06E11 | paper → observe | Health and process state / heartbeat / PID / health JSON / native supervision | supervisor, api |

## 7 — PERSISTENCE / HISTORY / TRAINING

Historical masters are separate worlds. There is NO demonstrated automatic live PAPER -> canonical Master bridge; no time/price identity joins.

| Block | Owner | Input → processing → output | Consumer | Source keys |
|---|---|---|---|---|
| raw / ORIGINAL MARKET EVIDENCE | Recorder / feed / Paper WAL | Source messages + original receive/source clocks → Durable publication; original receipts → RAW/ACK; OHLCV partitions; Futures WAL | Canonical / native Legacy | Recorder storage, feed-paths, Execution WAL |
| derived / DERIVED FEATURES | Canonical / native Legacy | Admitted market and preceding state → Original feature calculations / generation metadata → Canonical/native Parquet history | Publisher / Cognition | canonical, legacy-input |
| contexts / OWN CONTEXT HISTORY | Publisher / Cognition | Derived inputs + original availability → Own Final/Lifecycle/Phase; separate CTX events → Context/episode/source IDs, not trade IDs | Manager / CommandBus | Publisher, Intrabar Cognition |
| decisions / DECISION / COMMAND HISTORY | Manager / CommandBus | Context + source/permission + positions → Existing decision conditions → decision_id / command_id / TF / lineage | Paper financial authority | CommandBus, Timeframe Manager |
| outcomes / CURRENT PAPER OUTCOMES | Paper financial authority | Committed commands and genuine execution market → Original position/order/fill/trade association → PAPER books / receipts / costs / outcomes | none current | Financial authority, Paper engine |
| history / HISTORICAL RECONSTRUCTION INPUTS | preserved research scripts | Causal bars/states; baseline/counterfactual candidates; worlds → Original research build, not this task → Exact source/run/availability registries | historical run_stage_09.py, preserved dataset owners | master, master-worlds |
| master / CANONICAL MASTER BOOKS | historical run_stage_09.py | Explicit bar/candidate/outcome keys and worlds → Separate BAR / STATE / CANDIDATE / OUTCOME → 17409 candidates;39035 MULTI_WORLD outcomes (snapshot) | preserved dataset owners | master, master-worlds, master-links |
| training / TRAINING / CALIBRATION LOCATORS | preserved dataset owners | Explicit candidate IDs + CI03 causal X; labels separate → Original split/feature/label/provenance manifests → Existing datasets; no new fit or labels | none current | training-core, training-order |
| future / FUTURE SYNTHETIC CORPUS | NOT IMPLEMENTED / NO CURRENT WRITER | No runtime input asserted → Requested future boundary only → No current dataset or automatic bridge | none current | NOT IMPLEMENTED future boundary |

| Edge | From → to | Payload / transport / trigger | Source keys |
|---|---|---|---|
| 07E01 | raw → derived | Admitted source data / native readers / Parquet / source availability at evaluation | canonical, legacy-input |
| 07E02 | derived → contexts | Owned classifier inputs / source-bound generations / own closed bar / event-time update | Publisher, Intrabar Cognition |
| 07E03 | contexts → decisions | Own closed-context lineage / Parquet + explicit bindings / manager evaluation | own-inputs, CommandBus |
| 07E04 | decisions → outcomes | Command -> position/order/fill/trade / native committed associations / existing execution conditions | consumer, Financial authority |
| 07E05 | history → master | Explicit world/run and identity links / historical original Parquet + manifests / original research build only | master, master-links |
| 07E06 | master → training | Candidate identity / original provenance / exact candidate_id/TF/side/close comparison / saved historical research build | training-core, master-links |
| 07E07 | history → training | CI03 admitted causal X + original label sources / saved field/split/availability contracts / saved historical dataset build; no automatic run | training-core, training-order |

## 8 — STARTUP / READINESS / FAILURE DEPENDENCIES

This is a data/readiness DAG, not invented Compose depends_on. RUNNING != fresh != source-qualified != PAPER OPEN permitted.

| Block | Owner | Input → processing → output | Consumer | Source keys |
|---|---|---|---|---|
| base / RESTORED STORAGE / CONFIG / IMAGES | operator / existing restore tooling | Exact14 roles; existing data volumes and bind mappings → Restore artifacts first; preserve state and identity → Readable owned roots + accepted code/config | Watchdog + Legacy collector + Cognition, paper-manager | Admission release/provenance, own-inputs, supervisor |
| ingress / INDEPENDENT MARKET OWNERS | Watchdog + Legacy collector + Cognition | Their existing exchange endpoints → Receive / native store / original timestamping → Real inputs; missing/freshness states remain explicit | native Legacy + Canonical, read-only owners | registry, native-flow, Intrabar Cognition |
| native / NATIVE PAIRS / CANONICAL | native Legacy + Canonical | Flow, Clusters, Spot OHLCV, source receipts → Availability guards before consumers; original order → Admitted source generations or BLOCKED | context-refresh-daemon, read-only owners | memory, legacy-input, canonical |
| publisher / PUBLISHER / FOUR OWN CONTEXTS | context-refresh-daemon | Closed inputs; frozen source pins; own history → One daemon child; source checks; own-TF publication → Final/Lifecycle/Phase, with actual timestamps | Paper child, timeframe-manager, read-only owners | Publisher, Context Phase, higher-tf |
| paper / PAPER NATIVE STARTUP | paper-manager | Existing financial descriptor, provenance, release pins, policy → Check before writer; current Futures stream; REAL off → Native books + market health + existing writer | Paper child, timeframe-manager, read-only owners | Admission release/provenance, paper-runner, own-inputs |
| r08 / R08 OBSERVER BOOTSTRAP | Paper child | Native startup gate + genuine new Spot; real own Context → Receive prefix -> fix300s baseline/INIT -> handoff → Descriptor/source binding only when actually produced | timeframe-manager | R08 child owner, Baseline provider, R08 adapter/handoff |
| manager / TIMEFRAME MANAGER READER | timeframe-manager | Financial environment + own context + source bindings → Missing technical input remains BLOCKED; no fabricated permission → Cycles/commands; valid market wait may be NO_ACTION | read-only owners | Manager daemon, own-inputs, Entry conditions |
| monitor / API / VISUAL / UI / SUPERVISION | read-only owners | Actual heartbeat and owner publications → Separate process health, stale data and market observation → Observable degraded/missing/current state | none current | api, Visual projection, nginx, supervisor |

| Edge | From → to | Payload / transport / trigger | Source keys |
|---|---|---|---|
| 08E01 | base → ingress | Writable existing roots and config / existing mounts / images / before normal process startup | registry, native-flow, Intrabar Cognition |
| 08E02 | ingress → native | Real available source generations / native snapshots / OHLCV / dependency-ready guards | legacy-input, canonical |
| 08E03 | native → publisher | Closed admitted inputs / seven INPUTS + native source snapshots / safe-close; one native child | Publisher |
| 08E04 | base → paper | Exact financial environment / existing historical provenance + current release manifest / before writer creation | Admission release/provenance, own-inputs |
| 08E05 | paper → r08 | Existing observer child launcher / same Paper container / native startup admission; no S0 fabricated | R08 child owner |
| 08E06 | publisher → r08 | Real own Context / Phase references / existing source binding inputs / existing causal availability rules | R08 child owner, R08 evidence |
| 08E07 | paper → manager | Valid financial environment / positions / shared authoritative runtime / native startup/readiness | own-inputs, Timeframe Manager |
| 08E08 | publisher → manager | Own admitted context / Final/Lifecycle/Phase publications / existing input availability | own-inputs, state-adapter |
| 08E09 | r08 → manager | Actually published source/descriptor / /r08 committed bindings / no pre-created fake INIT/permission | own-inputs, R08 direct source |
| 08E10 | ingress → monitor | Actual status / owner output / read-only files / Docker GET / native status/poll | api, Visual projection, supervisor |
| 08E11 | native → monitor | Actual status / owner output / read-only files / Docker GET / native status/poll | api, Visual projection, supervisor |
| 08E12 | publisher → monitor | Actual status / owner output / read-only files / Docker GET / native status/poll | api, Visual projection, supervisor |
| 08E13 | paper → monitor | Actual status / owner output / read-only files / Docker GET / native status/poll | api, Visual projection, supervisor |
| 08E14 | manager → monitor | Actual status / owner output / read-only files / Docker GET / native status/poll | api, Visual projection, supervisor |

## Exact source references

### feed

- Owner: collector-watchdog; SHA256: `254f476ece94003a328514507797f98ed6bf1a8b5c719b2433b940b66a0a87e9`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/collector-watchdog/app/live_binance_feed_v2.py` (538 lines); anchors: [91].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/collector-watchdog/app/live_binance_feed_v2.py).

### Spot transport

- Owner: paper-manager; SHA256: `425de2114eb00c34cb79d621cf72e609062c0c808d1d49f0839e092b135850c3`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/r08-forward/src/transport.py` (17 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/r08-forward/src/transport.py).

### Intrabar Cognition

- Owner: cognition-runtime; SHA256: `04e6289278da244333a57f6376bc4293158583844a627d7803953b64445d0919`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/cognition-runtime/app/scripts/live/run_intrabar_cognition_service.py` (418 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/cognition-runtime/app/scripts/live/run_intrabar_cognition_service.py).

### native-flow

- Owner: legacy-multi-exchange; SHA256: `3d9ed919be3a1dc15e1f10270696dc7745db3664d4218fa2578d180f995f4659`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/legacy-multi-exchange/opt/btcml-legacy-original/multi_exchange_collector.py` (636 lines); anchors: [236].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/legacy-multi-exchange/opt/btcml-legacy-original/multi_exchange_collector.py).

### paper-runner

- Owner: paper-manager; SHA256: `9298e6b37b126caf9bd53f11a835da3b2c841af5f796e75e3fb1d87bc9561c50`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/scripts/live/run_intrabar_paper_manager.py` (482 lines); anchors: [35, 217, 424].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/scripts/live/run_intrabar_paper_manager.py).

### canonical

- Owner: canonical-runtime; SHA256: `68a355cad3db783af9741d70bf8e76aaffe7f7ef601d9800f08cc4edd025764c`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/canonical-runtime/app/src/btc_ml/runtime/pipeline.py` (437 lines); anchors: [31, 69, 115, 180, 181, 185, 186, 198, 199, 200, 258].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/canonical-runtime/app/src/btc_ml/runtime/pipeline.py).

### Publisher

- Owner: context-refresh-daemon; SHA256: `7755359e9e71cd5fd9fde30e3390d47649793b328fd8b31e46f7fc428d95f890`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/context-refresh-daemon/app/scripts/live/run_causal_context_chain_candidate.py` (260 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/context-refresh-daemon/app/scripts/live/run_causal_context_chain_candidate.py).

### Paper engine

- Owner: paper-manager; SHA256: `2910e6edb811d7f4de76886a9cc842bbe95126c663500e890c149b8da2423bb3`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/engine.py` (1778 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/engine.py).

### Recorder storage

- Owner: paper-manager; SHA256: `2e28a8e6e5ca16a7bba76e9c0c65f68a06734acce49dc3f24eb1a374d04b9dfb`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/r08-forward/src/storage.py` (237 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/r08-forward/src/storage.py).

### Journal V3

- Owner: paper-manager; SHA256: `6d593ef982638f14078a4b26755c7da41a290a11a37b4450e677d47ccd807193`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trend/trend_journal.py` (480 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trend/trend_journal.py).

### Financial authority

- Owner: paper-manager; SHA256: `c316c2ee388835e8ebf64d24fcbf27ab8b23e7bf899d1be8db32822e8bad733b`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/unified_financial_authority.py` (195 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/unified_financial_authority.py).

### nginx

- Owner: sealed-config; SHA256: `319519f2fa754fc1eebe6c54ba712313f5c9334a994200973648a31ac7e68468`.
- File: `BTCML_BACKUP_071126/CONFIG/nginx.actual.conf` (53 lines); anchors: [20, 29, 34, 50].

### api

- Owner: ops-api; SHA256: `3a1ea3dd0b7336112b7c1c676ac65b6917f4d256d83146efb7d60aa014ae6e80`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/ops-api/app/dashboard/backend/app/services/runtime_observation.py` (263 lines); anchors: [148].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/ops-api/app/dashboard/backend/app/services/runtime_observation.py).

### api-chart

- Owner: ops-api; SHA256: `cd3937e29776d5e3e3be24b4061736dd4809cf238ee5fc55d879a6e0dd17bc45`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/ops-api/app/dashboard/backend/app/services/chart_presentation.py` (107 lines); anchors: [43].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/ops-api/app/dashboard/backend/app/services/chart_presentation.py).

### Risk/economics

- Owner: paper-manager; SHA256: `806a0cd667c0e0792247c217259f54dad1a4ca6a8274b39ac48b10c071e18693`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/economics.py` (235 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/economics.py).

### own-inputs

- Owner: timeframe-manager; SHA256: `ac9effdcc9875dd304adf67840f4bf883c3c4d7fe91acbe2ccba2c86671b6e34`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/timeframe-manager/app/src/btc_ml/runtime/financial_trend_environment.py` (362 lines); anchors: [74].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/timeframe-manager/app/src/btc_ml/runtime/financial_trend_environment.py).

### ui

- Owner: release; SHA256: `aa04db74b4a86a172d00f96e978e9f434b3cf4f267d2977c231ffb521a5d1cd7`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/presentation-build-source/dashboard/frontend/src/App.tsx` (97 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/presentation-build-source/dashboard/frontend/src/App.tsx).

### Visual projection

- Owner: context-refresher; SHA256: `868ef2c374efdff93f16332453414fe68afd406190d628bd94b879ff8bb5b702`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/context-refresher/app/apps/context_visualizer/generate_lifecycle_context_data.py` (890 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/context-refresher/app/apps/context_visualizer/generate_lifecycle_context_data.py).

### CommandBus

- Owner: paper-manager; SHA256: `91b89eb9b21bd691d7842ab43c559ca16229bacd2b2e3492e346a53b5c02f951`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trading/command_bus.py` (249 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trading/command_bus.py).

### legacy-input

- Owner: canonical-runtime; SHA256: `2b32f618f39b05b2e28517c4b4de47b56ba31e54571c56eaea520a1c2584d471`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/canonical-runtime/app/legacy_source_inputs.py` (117 lines); anchors: [113].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/canonical-runtime/app/legacy_source_inputs.py).

### volume-response

- Owner: canonical-runtime; SHA256: `e0c81860799891bea8c128bc6440a41a8aa8911bce99a6446a30d91e582d912f`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/canonical-runtime/app/volume_response_engine_v1.py` (511 lines); anchors: [87, 90].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/canonical-runtime/app/volume_response_engine_v1.py).

### pub-daemon

- Owner: context-refresh-daemon; SHA256: `2f1933a07d94dba968e199c16c70c7dbffa65caf9a901b46df575591d32dc92b`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/context-refresh-daemon/app/scripts/live/run_context_refresh_daemon.py` (845 lines); anchors: [10, 129, 130, 140, 149, 150, 151, 154, 157, 159, 160, 166, 173, 174, 175, 446, 644, 685, 756, 776, 778, 779, 815, 833].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/context-refresh-daemon/app/scripts/live/run_context_refresh_daemon.py).

### memory

- Owner: legacy-volume-memory; SHA256: `12d4a6e00130b2df187cdcf78da794074135211cd47c849b6ff02ab0e29d375e`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/legacy-volume-memory/opt/btcml-legacy-original/engines/volume_memory_engine.py` (314 lines); anchors: [27].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/legacy-volume-memory/opt/btcml-legacy-original/engines/volume_memory_engine.py).

### regime

- Owner: legacy-volume-memory; SHA256: `a14e7fffcd940dc53cb141852972be91839721b7893dacccb6f12318bd9029f8`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/legacy-volume-memory/opt/btcml-legacy-original/engines/regime_engine.py` (226 lines); anchors: [27].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/legacy-volume-memory/opt/btcml-legacy-original/engines/regime_engine.py).

### reactions

- Owner: legacy-volume-reactions; SHA256: `54ead2e050a0e33a90743a46ad7881e0e77b1a0afb89d087b32316c6e6886408`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/legacy-volume-reactions/opt/btcml-legacy-original/engines/volume_reaction_engine.py` (373 lines); anchors: [27].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/legacy-volume-reactions/opt/btcml-legacy-original/engines/volume_reaction_engine.py).

### acceptance

- Owner: legacy-volume-reactions; SHA256: `10c73c7f04aabac75da3fac8f94f92811763a2696cb77a13ffbda7aff6ee9374`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/legacy-volume-reactions/opt/btcml-legacy-original/engines/acceptance_engine.py` (381 lines); anchors: [27].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/legacy-volume-reactions/opt/btcml-legacy-original/engines/acceptance_engine.py).

### clusters

- Owner: legacy-volume-clusters; SHA256: `8f7d592165115516791f4cb607245a3cf2678e187d728b5522d9744857167639`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/legacy-volume-clusters/opt/btcml-legacy-original/engines/volume_cluster_engine.py` (311 lines); anchors: [27].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/legacy-volume-clusters/opt/btcml-legacy-original/engines/volume_cluster_engine.py).

### inventory

- Owner: legacy-volume-clusters; SHA256: `0f029ac1ae68180c24b65a9ac3a634c2ef23637f79e0162b3b100d41b4ebe615`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/legacy-volume-clusters/opt/btcml-legacy-original/engines/inventory_engine.py` (363 lines); anchors: [27].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/legacy-volume-clusters/opt/btcml-legacy-original/engines/inventory_engine.py).

### registry

- Owner: collector-watchdog; SHA256: `6bc4a79fcc9e4d7ffd9e66c56c098f19b8f598d27371bed61ed02a63ff494fff`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/collector-watchdog/app/collector_registry.py` (52 lines); anchors: [11].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/collector-watchdog/app/collector_registry.py).

### Closed-bar bridge

- Owner: cognition-runtime; SHA256: `6d4bb2fbd87e4ffc719eca294c6c3d87cfbf3ec172c0edff86a097358fa1f3aa`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/cognition-runtime/app/src/btc_ml/live/intrabar/closed_bar_event_bridge.py` (1182 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/cognition-runtime/app/src/btc_ml/live/intrabar/closed_bar_event_bridge.py).

### Manager daemon

- Owner: timeframe-manager; SHA256: `1b804e3e17008d4f2d291bc6a03c0b5df5c04931fb084c9a5f9edd8edf61014b`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/timeframe-manager/app/scripts/live/timeframe_manager_daemon.py` (234 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/timeframe-manager/app/scripts/live/timeframe_manager_daemon.py).

### state-adapter

- Owner: timeframe-manager; SHA256: `9615e6f6c4fd6548f74459b8ea7fb5b6eefc7ae70ea8f35a188d2723dae9211c`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/timeframe-manager/app/src/btc_ml/trading/timeframe_state_adapter.py` (805 lines); anchors: [112, 463].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/timeframe-manager/app/src/btc_ml/trading/timeframe_state_adapter.py).

### supervisor

- Owner: intrabar-supervisor; SHA256: `2aafe6d9f34a34c09e9fa3578df6c06d4a7eb167498280fe43f443c3c7112d70`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/intrabar-supervisor/app/deploy/vps/entrypoints/intrabar_supervisor.sh` (24 lines); anchors: [24].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/intrabar-supervisor/app/deploy/vps/entrypoints/intrabar_supervisor.sh).

### R08 child owner

- Owner: paper-manager; SHA256: `5824fd71a9fd899e484d576911c61d63169741105a13f3e66f894909d5ab5189`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/runtime/r08_live_source.py` (227 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/runtime/r08_live_source.py).

### Recorder

- Owner: paper-manager; SHA256: `3455c430dbcb5e91bad7a9c36e8d011aa7577574818143c331e42b0dc458162f`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/r08-forward/src/recorder.py` (205 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/r08-forward/src/recorder.py).

### R08 adapter/handoff

- Owner: paper-manager; SHA256: `2472660653f564b614ca42facc20b6afa3fe1cddc45b0f918c73246347fa51ac`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trend/recorder_live_adapter.py` (290 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trend/recorder_live_adapter.py).

### Baseline provider

- Owner: paper-manager; SHA256: `07822ab196c5375c17747afa77ceee9ee56098c18bdf36b3bfef609b9016d98a`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trend/r08_baseline_provider.py` (174 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trend/r08_baseline_provider.py).

### feed-paths

- Owner: collector-watchdog; SHA256: `4c3d7a855d381a00caeba678286eee85a388145341de8d2b48c644b4e0259032`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/collector-watchdog/app/live_feed_paths.py` (99 lines); anchors: [27, 79].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/collector-watchdog/app/live_feed_paths.py).

### R08 direct source

- Owner: paper-manager; SHA256: `5396e771fc382617bf3c6765ae5d4027b97a5f26176a37d7cc758514a3f0ad0d`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trend/live_direct_source.py` (53 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trend/live_direct_source.py).

### consumer

- Owner: paper-manager; SHA256: `003e66f5bf27ce5300722d8732e954664a7a5784ba6ccd9a720ee9e52f9e04fd`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/s41_command_consumer.py` (440 lines); anchors: [99].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/s41_command_consumer.py).

### native-stage2

- Owner: context-refresh-daemon; SHA256: `bbaa2a2a6651cc416fc6ec0ed68ad30a7de13194ae75103460ca855fe1ac9d9e`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/context-refresh-daemon/app/src/btc_ml/external_traders/context_stage2_evidence.py` (1067 lines); anchors: [132, 339, 472].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/context-refresh-daemon/app/src/btc_ml/external_traders/context_stage2_evidence.py).

### m15-boundary

- Owner: context-refresh-daemon; SHA256: `3922af460a603d755319e4a78350fe811b402b1a0b4b53bf79eda0b727512930`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/context-refresh-daemon/app/src/btc_ml/external_traders/m15_september_boundary.py` (144 lines); anchors: [45].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/context-refresh-daemon/app/src/btc_ml/external_traders/m15_september_boundary.py).

### higher-tf

- Owner: context-refresh-daemon; SHA256: `0af53e58f56ca720513c9ddb164e626f933eac7d8c33cb0203a2e10e128af45f`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/context-refresh-daemon/app/src/btc_ml/external_traders/independent_context_publication.py` (253 lines); anchors: [161].
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/context-refresh-daemon/app/src/btc_ml/external_traders/independent_context_publication.py).

### Lifecycle

- Owner: context-refresh-daemon; SHA256: `681eda7351b7a08e9590c0ff312e2ebca6dd9573e13c644629494dbfdea97ca3`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/context-refresh-daemon/app/scripts/independent_timeframes/build_market_context_lifecycle_memory.py` (1372 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/context-refresh-daemon/app/scripts/independent_timeframes/build_market_context_lifecycle_memory.py).

### Context Phase

- Owner: context-refresh-daemon; SHA256: `0ccda9bc38d95ff5ce5d7d8f52927e078afc1433427afeb1ed6d02b41ecb7c72`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/context-refresh-daemon/app/src/btc_ml/external_traders/context_phase_publication.py` (717 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/context-refresh-daemon/app/src/btc_ml/external_traders/context_phase_publication.py).

### Cognition Pipeline

- Owner: cognition-runtime; SHA256: `d2210e8f2e6b651699fe79f504f87ddf159f2d9618983605b493f9255068d206`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/cognition-runtime/app/src/btc_ml/live/intrabar/cognition_pipeline.py` (269 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/cognition-runtime/app/src/btc_ml/live/intrabar/cognition_pipeline.py).

### R08 ResearchSystem

- Owner: paper-manager; SHA256: `d1f04ffbe71511e52f0f389362db6ebc4692b925603859bc343e645769fd0413`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trend/trend_research_system.py` (527 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trend/trend_research_system.py).

### R08 evidence

- Owner: paper-manager; SHA256: `50c8e7b5164e17f35040e5d87b12bee031f60682b9a9fcf7dff73d91917e612f`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trend/trend_evidence.py` (81 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trend/trend_evidence.py).

### Trend Strength integration

- Owner: paper-manager; SHA256: `028a3be3fd6df7e076507eee6d179c8a8a5ff4239bc73d7b5f82d0e87ebd6c2c`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trend/context_trend_integration.py` (423 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trend/context_trend_integration.py).

### Entry conditions

- Owner: paper-manager; SHA256: `de51d662fe63f3dd8bd7ee083c3cdcd88be7581d5017b5021c75a0cb8ec8791c`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/entry_eligibility.py` (132 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/entry_eligibility.py).

### Timeframe Manager

- Owner: timeframe-manager; SHA256: `3e0813838cbca5321a533aff74f405cd15334b8eb2407f28f38bca77885a13af`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/timeframe-manager/app/src/btc_ml/trading/timeframe_manager.py` (1674 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/timeframe-manager/app/src/btc_ml/trading/timeframe_manager.py).

### Final Context

- Owner: context-refresh-daemon; SHA256: `dd63f3c2725e4819688117f791252ef2936b9a43d256279e24ba5338d9314a17`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/context-refresh-daemon/app/scripts/independent_timeframes/build_final_market_context_memory.py` (307 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/context-refresh-daemon/app/scripts/independent_timeframes/build_final_market_context_memory.py).

### Admission release/provenance

- Owner: paper-manager; SHA256: `9207ac125cbbdd9f439539e0becb4104f859497c9c11c03c1b402165d8b1aa4b`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/working_admission.py` (104 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/working_admission.py).

### Execution WAL

- Owner: paper-manager; SHA256: `f096d750185752d6f6864a04159271db906c66af92c7d3d933502adc254e036b`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/execution_market_wal.py` (591 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/execution_market_wal.py).

### Execution checkpoint

- Owner: paper-manager; SHA256: `8ed5b958c6fb7f5f99675e8674361839580baecf5e0c76ed33617a0af6a3e6f8`.
- File: `BTCML_RELEASE_PUBLICATION_071126/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/execution_market_checkpoint.py` (133 lines); anchors: whole module / entry symbols in JSON index.
- [Fixed accepted-source commit](https://github.com/maxim134vl/btc-microstructure-engine/blob/8f45e0260929ba87ccaca1d8fe6e08949cc1d94a/releases/071126/components/paper-manager/app/src/btc_ml/trading/intrabar_paper/execution_market_checkpoint.py).

### master

- Owner: historical; SHA256: `d577d7c7c5c4e0452d6f8de685f14f72efa378e0db31560b4bad6c2eb641603d`.
- File: `btc-ml/research/canonical_system_reconstruction_v1/09_CANONICAL_MASTERS/run_stage_09.py` (669 lines); anchors: whole module / entry symbols in JSON index.

### master-worlds

- Owner: historical; SHA256: `5abd2301f81241de4df27d4999b618b47729936b7bc416889ad328bc2090829f`.
- File: `btc-ml/research/canonical_system_reconstruction_v1/09_CANONICAL_MASTERS/WORLD_NAMESPACE_CONTRACT.md` (5 lines); anchors: whole module / entry symbols in JSON index.

### master-links

- Owner: historical; SHA256: `309459f12dd6257537cd31ce759afbb2789aeb66f114c9c19f4d2c756dd22aed`.
- File: `btc-ml/research/canonical_system_reconstruction_v1/09_CANONICAL_MASTERS/MASTER_LINKAGE_CONTRACT.md` (9 lines); anchors: whole module / entry symbols in JSON index.

### training-core

- Owner: historical; SHA256: `b06e2ccb5787c0a19de0654856032348906a50b37d93c9cb3743b3e4fb94a30e`.
- File: `btc-ml/research/canonical_system_reconstruction_v1/MASTER_TRAINING_DATASET_V1/scripts/build_core.py` (96 lines); anchors: [19].

### training-order

- Owner: historical; SHA256: `293372dd1de165c6741d199b85e0b8526efffa0e4a8b97dcbececdd00776501d`.
- File: `btc-ml/research/canonical_system_reconstruction_v1/MASTER_TRAINING_DATASET_V1/BUILD_ORDER.md` (15 lines); anchors: whole module / entry symbols in JSON index.
