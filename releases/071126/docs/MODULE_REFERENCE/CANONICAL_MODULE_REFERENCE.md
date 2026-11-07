# Canonical modules — exact installed pipeline

28 configured engines (including conditional accepted producers), exact source/archive/SHA. Economic purpose and actual reader/transform/writer calls are recorded separately. These are source expressions, not recomputed outputs. Procedural scripts may define no Python function; this does not imply an empty method. Runtime environment/path registry retains precedence over source defaults.

## candle_structure_engine_v1.py

**PURPOSE**: Собрать баровую структуру из фактического feed. OHLC/объём описывают, где прошла цена и сколько активности было, до вывода о принятии движения.

**SOURCE**: /app/candle_structure_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: eba4aabd4157dd66f2b9617cc29beb0491cae7859f04768855ebc100a87e71dd

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: Ordered pipeline dependency guard + reader calls below; no claim of absent dependency

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `read_live_feed_history()`
- `ohlc["spread"] .rolling(20) .mean()`
- `ohlc["spread"] .rolling(20) .std()`
- `ohlc["spread"] .rolling(20)`

**METHOD EXPRESSIONS**:

- `pd.to_datetime(feed["timestamp"])`
- `feed.sort_values("timestamp").drop_duplicates(subset=["timestamp"])`
- `ohlc["spread"] .rolling(20) .mean()`
- `ohlc["spread"] .rolling(20) .std()`
- `ohlc["volume"] .rolling(10) .mean()`
- `ohlc["volume"] .rolling(10) .std()`
- `(ohlc["volume"] - ohlc["buy_volume"]).clip(lower=0)`
- `( (ohlc["close"] - ohlc["open"]).abs() / (ohlc["high"] - ohlc["low"] + 0.000001) ).clip(0, 1)`
- `ohlc["spread"] .rolling(20)`
- `ohlc["volume"] .rolling(10)`

**OUTPUTS**:

- `atomic_parquet_write( ohlc, resolve_write("candle_structure_memory.parquet"), validate=True, timestamp_col="timestamp", enforce_timestamp_integrity=True, )`
- `resolve_write("candle_structure_memory.parquet")`

## volume_localization_engine_v1.py

**PURPOSE**: Локализовать объём внутри ценового диапазона, сохранив lineage. Концентрация объёма — evidence местоположения усилия, не автоматический LONG/SHORT.

**SOURCE**: /app/volume_localization_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 45601b389cffd59c4d3a63bfdbcb2ddfa62069efbcc303cbfa4a5597a3bc9e5c

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: Ordered pipeline dependency guard + reader calls below; no claim of absent dependency

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `_SPEC.loader.exec_module(_MOD)`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

## candle_geometry_engine_v2.py

**PURPOSE**: Описать геометрию тела/теней и положения закрытия. Это результат движения внутри бара, который сопоставляется с усилием.

**SOURCE**: /app/candle_geometry_engine_v2.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 0f5e9855a81c0467707c001669423f7c113001505f3d3c3d7d5c32c2c77d22c9

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('live_market_feed.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("live_market_feed.parquet") )`
- `df["spread"] .rolling(20) .mean()`
- `df["spread"] .rolling(20) .std()`
- `resolve_read("live_market_feed.parquet")`
- `df["spread"] .rolling(20)`

**METHOD EXPRESSIONS**:

- `df["spread"] .rolling(20) .mean()`
- `df["spread"] .rolling(20) .std()`
- `df["spread"] .rolling(20)`

**OUTPUTS**:

- `atomic_parquet_write( df, "candle_geometry_v2_memory.parquet" )`

## volume_localization_engine_v2.py

**PURPOSE**: Сохранить принятую вторую ось локализации/геометрии объёма в её собственном контракте, без подмены первой версии.

**SOURCE**: /app/volume_localization_engine_v2.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: e0c238d9eeb64c84af7111ba94b5d6fee77c923aeb3bcd3f683052ef91744343

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('candle_geometry_v2_memory.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("candle_geometry_v2_memory.parquet") )`
- `resolve_read("candle_geometry_v2_memory.parquet")`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

- `atomic_parquet_write( zones_df, "volume_localization_v2_memory.parquet" )`

## volume_classification_engine_v1.py

**PURPOSE**: Классифицировать наблюдённую объёмную активность существующей формулой и её референсами.

**SOURCE**: /app/volume_classification_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 717d757d30c41ef19d622f9eb4ee6433c9cda875435954800101d2c18940cd4c

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('candle_structure_memory.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("candle_structure_memory.parquet") )`
- `resolve_read("candle_structure_memory.parquet")`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

- `df.to_parquet( resolve_write("volume_classification_memory.parquet") )`
- `resolve_write("volume_classification_memory.parquet")`

## schema_validation_engine_v1.py

**PURPOSE**: Проверить структуру/совместимость входного evidence, не создавать направление из отсутствующих полей.

**SOURCE**: /app/schema_validation_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 85ff5503e3c2fce4a7b7f665b5c438040dac59584872696475d3fea7f3c73369

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: Ordered pipeline dependency guard + reader calls below; no claim of absent dependency

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

## behavioral_sequence_memory_v1.py

**PURPOSE**: Сохранить последовательность поведения: отдельный бар читается в контексте предыдущих наблюдений.

**SOURCE**: /app/behavioral_sequence_memory_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 5eae8189df3365c2256bb31ea21434131aead9d4800b9103368475f243487f44

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: Ordered pipeline dependency guard + reader calls below; no claim of absent dependency

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `load_parquet_cached( "temporal_context_memory.parquet" )`
- `load_parquet_cached( "volume_localization_v2_memory.parquet" )`
- `read_consumer_source('volume_reactions.parquet', _legacy_available_at, consumer='behavioral_sequence_memory_v1', original_loader=load_parquet_cached)`
- `load_parquet_cached( "behavioral_events_memory.parquet" )`
- `load_parquet_cached( MEMORY_FILE )`

**METHOD EXPRESSIONS**:

- `combined.drop_duplicates( subset=["timestamp"] )`

**OUTPUTS**:

- `combined.to_parquet( temp_file, index=False )`
- `resolve_write(MEMORY_FILE)`

## behavioral_volume_observer_v1.py

**PURPOSE**: Связать объёмные наблюдения с поведением цены без искусственного дополнения пропущенного потока.

**SOURCE**: /app/behavioral_volume_observer_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 882cd395d878a887489e2ee15a0877a42b7550b69fafb00749429012260d7f61

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet('adaptive_behavioral_weights.parquet'), pd.read_parquet('behavioral_events_memory.parquet'), pd.read_parquet('behavioral_sequence_memory.parquet'), pd.read_parquet('contextual_memory_state.parquet'), pd.read_parquet('temporal_context_memory.parquet'), pd.read_parquet('volume_localization_v2_memory.parquet')

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( "contextual_memory_state.parquet" )`
- `pd.read_parquet( "temporal_context_memory.parquet" )`
- `pd.read_parquet( "volume_localization_v2_memory.parquet" )`
- `read_consumer_source('volume_reactions.parquet', _legacy_available_at, consumer='behavioral_volume_observer_v1', original_loader=pd.read_parquet)`
- `pd.read_parquet( "behavioral_events_memory.parquet" )`
- `pd.read_parquet( "behavioral_sequence_memory.parquet" )`
- `pd.read_parquet( "adaptive_behavioral_weights.parquet" )`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

- `observer_state.to_parquet( "behavioral_observer_state.parquet" )`

## microstructure_candle_engine_v1.py

**PURPOSE**: Добавить предусмотренную native microstructure характеристику к собственной баровой памяти.

**SOURCE**: /app/microstructure_candle_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 8182acdaddb07d1e9b7b00cc3006478431c22a814e828f7d5b71af6d38a5b154

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('live_market_feed.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("live_market_feed.parquet") )`
- `resolve_read("live_market_feed.parquet")`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

- `row.to_parquet( resolve_write("microstructure_candle_memory.parquet") )`
- `resolve_write("microstructure_candle_memory.parquet")`

## volume_response_engine_v1.py

**PURPOSE**: Сопоставить усилие и ценовой результат. Большой объём при слабом продвижении отличается от принятого направленного движения.

**SOURCE**: /app/volume_response_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: e0c81860799891bea8c128bc6440a41a8aa8911bce99a6446a30d91e582d912f

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: safe_read_parquet('candle_geometry_v2_memory.parquet'), safe_read_parquet('candle_structure_memory.parquet'), safe_read_parquet('volume_classification_memory.parquet'), safe_read_parquet('volume_reactions.parquet'), safe_read_parquet(_localization_source)

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `_load_timestamp_identity()`
- `safe_read_parquet( "volume_classification_memory.parquet" )`
- `safe_read_parquet( "candle_structure_memory.parquet" )`
- `safe_read_parquet( "candle_geometry_v2_memory.parquet" )`
- `safe_read_parquet( _localization_source )`
- `geometry[ "spread" ] .tail(50)`
- `spec.loader.exec_module(mod)`
- `read_available_source("volume_reactions.parquet", _input_available_at, consumer="volume_response_engine_v1")`
- `safe_read_parquet("volume_reactions.parquet")`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

## climactic_behavior_engine_v1.py

**PURPOSE**: Выделить climactic evidence и stopping/response признаки. Одно такое наблюдение ещё не является торговым разрешением.

**SOURCE**: /app/climactic_behavior_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: e6cdc577bc61bfb647f0b6bf470d004fcbb5727c47a954a79d3051ee9d9285ed

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('climactic_behavior_memory.parquet')), pd.read_parquet(resolve_read('volume_response_state.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("volume_response_state.parquet") )`
- `resolve_read("volume_response_state.parquet")`
- `pd.read_parquet( resolve_read("climactic_behavior_memory.parquet") )`
- `resolve_read("climactic_behavior_memory.parquet")`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

- `row.to_parquet( resolve_write("climactic_behavior_memory.parquet"), index=False )`
- `resolve_write("climactic_behavior_memory.parquet")`

## auction_convergence_engine_v1.py

**PURPOSE**: Согласовать существующие аукционные evidence; противоречия не заменяются безусловной стороной.

**SOURCE**: /app/auction_convergence_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 7e7768b4b34cfb9c790f9a2a1a32817bb8d9ec52c74d05038ec605613615a2df

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: safe_read_parquet('auction_convergence_memory.parquet'), safe_read_parquet('volume_response_state.parquet')

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `safe_read_parquet( "volume_response_state.parquet" )`
- `safe_read_parquet( "auction_convergence_memory.parquet" )`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

## live_volume_flow_engine_v1.py

**PURPOSE**: Сформировать предусмотренный volume-flow evidence текущих входов.

**SOURCE**: /app/live_volume_flow_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 9611f38d00c733acfb122978ef8806f91757e06375badd78742d3b73a3fac39a

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('live_market_feed.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("live_market_feed.parquet") )`
- `df["spread"] .rolling(20) .mean()`
- `resolve_read("live_market_feed.parquet")`
- `df["spread"] .rolling(20)`

**METHOD EXPRESSIONS**:

- `df["volume"] .rolling(20) .mean()`
- `df["spread"] .rolling(20) .mean()`
- `df["volume"] .rolling(20)`
- `df["spread"] .rolling(20)`

**OUTPUTS**:

- `memory.to_parquet( resolve_write("live_volume_flow_memory.parquet"), index=False )`
- `resolve_write("live_volume_flow_memory.parquet")`

## liquidity_cluster_engine_v1.py

**PURPOSE**: Сформировать evidence локализации ликвидности из доступных native источников.

**SOURCE**: /app/liquidity_cluster_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 4776c45ce2f1824c37cc9d95640fef8b9124984fe03e383d8c5328249913bdb5

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('volume_localization_memory.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("volume_localization_memory.parquet") )`
- `resolve_read("volume_localization_memory.parquet")`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

- `cluster_df.to_parquet( resolve_write("liquidity_clusters_memory.parquet") )`
- `resolve_write("liquidity_clusters_memory.parquet")`

## flow_liquidity_interaction_engine_v3.py

**PURPOSE**: Связать поток с ликвидностью после обоих upstream producers.

**SOURCE**: /app/flow_liquidity_interaction_engine_v3.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 1db690a4ddd26dc20b845b25d0923c9a61aa144a920b6b3e454599b239ca7562

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('liquidity_clusters_memory.parquet')), pd.read_parquet(resolve_read('live_market_feed.parquet')), pd.read_parquet(resolve_read('live_volume_flow_memory.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("live_volume_flow_memory.parquet") )`
- `pd.read_parquet( resolve_read("liquidity_clusters_memory.parquet") )`
- `pd.read_parquet( resolve_read("live_market_feed.parquet") )`
- `resolve_read("live_volume_flow_memory.parquet")`
- `resolve_read("liquidity_clusters_memory.parquet")`
- `resolve_read("live_market_feed.parquet")`

**METHOD EXPRESSIONS**:

- `feed.drop_duplicates( subset=["timestamp"], keep="last" )`

**OUTPUTS**:

- `interaction_df.to_parquet( resolve_write("flow_liquidity_interaction_memory.parquet"), index=False )`
- `resolve_write("flow_liquidity_interaction_memory.parquet")`

## htf_structure_engine_v1.py

**PURPOSE**: Построить собственную старшую структуру, сохранив source/TF границы.

**SOURCE**: /app/htf_structure_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: aa597681536833ddea7da29dc569124c0f81056697e0923f7b6189478a339f16

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('live_market_feed.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("live_market_feed.parquet") )`
- `resolve_read("live_market_feed.parquet")`

**METHOD EXPRESSIONS**:

- `feed.drop_duplicates( subset=["timestamp"], keep="last" )`

**OUTPUTS**:

- `htf_df.to_parquet( resolve_write("htf_structure_memory.parquet"), index=False )`
- `resolve_write("htf_structure_memory.parquet")`

## htf_ltf_context_engine_v1.py

**PURPOSE**: Согласовать предусмотренные HTF/LTF признаки до synthesis; descriptive hierarchy не равна произвольному veto независимого trader.

**SOURCE**: /app/htf_ltf_context_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 9c663e3ea4e52189ed2c63bc74e8af21318e3c65f1803a353834b2417063031b

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(resolve_read('flow_liquidity_interaction_memory.parquet')), pd.read_parquet(resolve_read('htf_structure_memory.parquet')), pd.read_parquet(resolve_read('live_volume_flow_memory.parquet'))

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet( resolve_read("live_volume_flow_memory.parquet") )`
- `pd.read_parquet( resolve_read("flow_liquidity_interaction_memory.parquet") )`
- `pd.read_parquet( resolve_read("htf_structure_memory.parquet") )`
- `resolve_read("live_volume_flow_memory.parquet")`
- `resolve_read("flow_liquidity_interaction_memory.parquet")`
- `resolve_read("htf_structure_memory.parquet")`

**METHOD EXPRESSIONS**:

- `flow.drop_duplicates( subset=["timestamp"], keep="last" )`
- `interactions.drop_duplicates( subset=["timestamp"], keep="last" )`
- `htf.drop_duplicates( subset=["timestamp"], keep="last" )`

**OUTPUTS**:

- `context_df.to_parquet( resolve_write("htf_ltf_context_memory.parquet"), index=False )`
- `resolve_write("htf_ltf_context_memory.parquet")`

## auction_synthesis_engine_v1.py

**PURPOSE**: Синтезировать аукционный контекст после нужных upstream компонентов, сохранив действующие веса/условия.

**SOURCE**: /app/auction_synthesis_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 3dd231562a3ac3612b4533b7de5fc47d5f96bf33249dc3385204b9cce087a5e8

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: safe_read_parquet('auction_convergence_memory.parquet'), safe_read_parquet('htf_ltf_context_memory.parquet'), safe_read_parquet('htf_structure_memory.parquet'), safe_read_parquet('volume_response_state.parquet')

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `safe_read_parquet( "volume_response_state.parquet" )`
- `safe_read_parquet( "auction_convergence_memory.parquet" )`
- `safe_read_parquet( "htf_structure_memory.parquet" )`
- `safe_read_parquet( "htf_ltf_context_memory.parquet" )`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

## stage2_cognition_runtime_v1.py

**PURPOSE**: Сформировать Stage2/MTF когнитивную память из доступного Stage1 evidence.

**SOURCE**: /app/stage2_cognition_runtime_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 71ea175d892e7afce12a9ca53e9d22da0e397cc4b120821d2f7a6656c759c02d

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(path), pd.read_parquet(target), safe_read_parquet(AUCTION_SYNTHESIS_SOURCE)

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `pd.read_parquet(target)`
- `safe_read_parquet(AUCTION_SYNTHESIS_SOURCE)`
- `path.read_bytes()`
- `json.loads(raw)`
- `json.loads(version_path.read_bytes())`
- `json.loads(current_path.read_bytes())`
- `read.get('status')`
- `read.get('frame_sha256')`
- `version_path.read_bytes()`
- `current_path.read_bytes()`
- `Path(__file__).read_bytes()`
- `pd.read_parquet(path)`
- `read.get('artifact_sha256')`
- `read.get('artifact_absolute_path')`
- `read.get('decoded_at')`
- `hashlib.sha256(__import__('pathlib').Path(__file__).read_bytes()).hexdigest()`
- `__import__('pathlib').Path(__file__).read_bytes()`

**METHOD EXPRESSIONS**:

- `aggregate_behavioral_timeframe( base_dataset.copy(), "M30", )`
- `aggregate_behavioral_timeframe( base_dataset.copy(), "H1", )`
- `aggregate_behavioral_timeframe( base_dataset.copy(), "H4", )`
- `pd.to_datetime(frame["timestamp"], utc=True)`
- `pd.to_datetime(mtf["timestamp"], utc=True)`
- `eval_frame.dropna(subset=["timestamp"]) .drop_duplicates(subset=["timestamp"]) .sort_values("timestamp") .reset_index(drop=True)`
- `pd.merge_asof( eval_frame, mtf_for_asof, left_on="timestamp", right_on="mtf_event_timestamp", direction="backward", )`
- `merged.dropna(subset=["synthesis_state"]).reset_index(drop=True)`
- `merged[ [ "mtf_event_timestamp", "timestamp", "synthesis_state", "trigger_event", "persistence", "persistence_score", "structural_rank", "alignment_score", "location_bias", "auction_state", "auction_event_timestamp", ] ].copy()`
- `pd.to_datetime(old["timestamp"], utc=True)`
- `pd.to_datetime(evaluation_timestamps, utc=True).to_numpy()`
- `pd.to_datetime(base_dataset.timestamp, utc=True)`
- `merged["timestamp"].dt.as_unit("ns")`
- `pd.merge_asof( merged, auction, left_on="timestamp", right_on="auction_event_timestamp", direction="backward", )`
- `merged["timestamp"].dt.as_unit(evaluation_unit)`
- `merged["auction_event_timestamp"].dt.as_unit(auction_unit)`
- `merged["timestamp"].max()`
- `pd.to_datetime(base_dataset.timestamp,utc=True).max()`
- `pd.to_datetime(components['base'].timestamp,utc=True)`
- `pd.to_datetime(candle_structure["timestamp"], utc=True)`
- `eval_frame.dropna(subset=["timestamp"]) .drop_duplicates(subset=["timestamp"]) .sort_values("timestamp")`
- `merged.dropna(subset=["synthesis_state"])`
- `pd.to_datetime(evaluation_timestamps, utc=True)`
- `pd.to_datetime(dataset.timestamp,utc=True).max()`
- `pd.to_datetime(dataset.timestamp,utc=True)`
- `pd.to_datetime(base_dataset.timestamp,utc=True)`
- `aggregate_behavioral_timeframe(base.copy(), tf)`
- `pd.to_datetime(dataset.timestamp, utc=True)`
- `eval_frame.dropna(subset=["timestamp"]) .drop_duplicates(subset=["timestamp"])`
- `pd.to_datetime(history.timestamp,utc=True)`
- `pd.to_datetime(m15_synthesis.timestamp,utc=True)`
- `pd.to_datetime(frame.timestamp,utc=True)`

**OUTPUTS**:

- `publish_atomic_frame(combined, path, producer=__file__, writer=atomic_parquet_write)`
- `_publish_new_observations( synthesis_output, SYNTHESIS_OUTPUT_PATH, )`
- `_publish_new_observations( domain, RUNTIME_COGNITION_MEMORY_PATH, )`
- `publish_atomic_frame(frame, path, producer=__file__, writer=atomic_parquet_write)`
- `publish_tf_native_results(tf_frames)`
- `H.publish_atomic_frame(frame,name,producer=__file__,writer=atomic_parquet_write)`
- `publish_tf_native_results(build_tf_native_results( base_dataset,market_cutoff=market_cutoff,components=tf_components))`

## runtime_cognition_engine_v1.py

**PURPOSE**: Прочитать/распространить текущую когнитивную память в runtime STATE.

**SOURCE**: /app/runtime_cognition_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: c251d1e09c42cd88397540e8ed37b159f30f193f8b59054cfb2456969f4207ee

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: safe_read_parquet(COGNITION_PATH), safe_read_parquet(SYNTHESIS_PATH)

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `safe_read_parquet(COGNITION_PATH)`
- `safe_read_parquet(SYNTHESIS_PATH)`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

## intermediate_cognition_engine_v1.py

**PURPOSE**: Сформировать предусмотренный промежуточный уровень когнитивного evidence, не перепрыгивая Final/Lifecycle ownership.

**SOURCE**: /app/intermediate_cognition_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 4978d945ec5e1ac61bf9be44677811cfa97aff1aadd0ec9c75f2f25c44f749b9

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: safe_read_parquet(CANDLE_SOURCE), safe_read_parquet(MEMORY_PATH), safe_read_parquet(RUNTIME_COGNITION_SOURCE), safe_read_parquet(VOLUME_CLASS_SOURCE)

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `load_stage2_5_thresholds()`
- `safe_read_parquet(MEMORY_PATH)`
- `safe_read_parquet(RUNTIME_COGNITION_SOURCE)`
- `safe_read_parquet(CANDLE_SOURCE)`
- `safe_read_parquet(VOLUME_CLASS_SOURCE)`

**METHOD EXPRESSIONS**:

- `pd.to_datetime(values, errors="coerce")`

**OUTPUTS**:

- `atomic_parquet_write(existing, MEMORY_PATH)`

## auction_reinforcement_engine_v1.py

**PURPOSE**: Учитывать подтверждение и сохранение когнитивного процесса в существующей reinforcement памяти; это не новый training run.

**SOURCE**: /app/auction_reinforcement_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 0e70928ea5509fa9a06fc81e6315ab00ac080cb671bc16a2e53abc8f88d052a6

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: pd.read_parquet(path), pd.read_parquet(resolve_read('auction_reinforcement_memory.parquet'))

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `_load_latest_runtime_cognition()`
- `pd.read_parquet(path)`
- `pd.read_parquet( resolve_read("auction_reinforcement_memory.parquet") )`
- `resolve_read("auction_reinforcement_memory.parquet")`

**METHOD EXPRESSIONS**:

- `pd.to_datetime(work["timestamp"], utc=True)`
- `pd.to_datetime( row["lineage_event_timestamp"], utc=True, )`
- `pd.to_datetime( row["auction_event_timestamp"], utc=True, )`
- `pd.to_datetime(memory["timestamp"], utc=True)`
- `latest_rows[identity_cols].drop_duplicates()`

**OUTPUTS**:

- `memory.to_parquet( resolve_write("auction_reinforcement_memory.parquet") )`
- `resolve_write("auction_reinforcement_memory.parquet")`

## probabilistic_auction_engine_v1.py

**PURPOSE**: Сохранить текущую вероятностную характеристику аукционного режима; вероятностный score не заменяет admission.

**SOURCE**: /app/probabilistic_auction_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 9ef8e1e62a71b0021c55c0e229e021acfe782522bc1f0f64a9a223dcaf51fd58

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: STATE.get('candle_structure'), STATE.get('volume_response'), pd.read_parquet(_history_path), pd.read_parquet(path), safe_read_parquet('auction_reinforcement_memory.parquet'), safe_read_parquet('probabilistic_auction_memory.parquet')

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `_load_latest_runtime_cognition()`
- `safe_read_parquet( "auction_reinforcement_memory.parquet" )`
- `safe_read_parquet( "probabilistic_auction_memory.parquet" )`
- `robustness_snapshot.update(regime_exports)`
- `robustness_snapshot.update(robustness_exports)`
- `read_probabilistic_state_with_evidence("probabilistic_auction_memory.parquet")`
- `pd.read_parquet(path)`
- `pd.read_parquet(_history_path)`

**METHOD EXPRESSIONS**:

- `pd.to_datetime(work["timestamp"], utc=True)`
- `pd.to_datetime( row["lineage_event_timestamp"], utc=True, )`
- `pd.to_datetime( row["auction_event_timestamp"], utc=True, )`
- `pd.to_datetime(reinforcement["timestamp"], utc=True)`
- `pd.to_datetime(probabilistic_history["timestamp"], utc=True)`
- `pd.to_datetime( reinforcement.loc[ reinf_ts == evaluation_timestamp, "timestamp" ].iloc[-1], utc=True, )`
- `latest_rows[identity_cols].drop_duplicates()`

**OUTPUTS**:

- `publish_append_frame( "probabilistic_auction_memory.parquet", row, producer=__file__, writer=append_state_row, )`

## auction_context_arbitration_engine_v1.py

**PURPOSE**: Разрешить предусмотренные конфликты контекста по принятому правилу.

**SOURCE**: /app/auction_context_arbitration_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 0a1f28379658413666c890113e6f6b65610cddfe5adedffa8980516347f063e3

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: safe_read_parquet(name), safe_read_parquet(str(path))

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `safe_read_parquet(name)`
- `_read_memory("candle_structure_memory.parquet")`
- `_read_memory("volume_response_state.parquet")`
- `_read_memory("auction_convergence_memory.parquet")`
- `_read_memory("runtime_cognition_composite.parquet")`
- `_read_memory("runtime_cognition_memory.parquet")`
- `_read_memory("probabilistic_auction_memory.parquet")`
- `_read_memory("trading_state_memory.parquet")`
- `_read_memory("market_state_memory.parquet")`
- `safe_read_parquet(str(path))`

**METHOD EXPRESSIONS**:

- `pd.to_datetime(work[ts_col], utc=True, errors="coerce")`
- `pd.to_datetime(candle_row.get("timestamp"), utc=True, errors="coerce")`
- `pd.to_datetime(cognition["evaluation_timestamp"], utc=True, errors="coerce")`
- `pd.to_datetime(anchor_ts_raw, utc=True, errors="coerce")`
- `pd.to_datetime(candle_history["timestamp"], utc=True, errors="coerce")`

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

## auction_decay_engine_v1.py

**PURPOSE**: Учитывать старение/ослабление evidence с сохранением его исходной временной принадлежности.

**SOURCE**: /app/auction_decay_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 0caed1d3c2e0a7c0155d02c1e0fe5600585e6257bd5c7bdffc7830e6d9bb52ba

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: safe_read_parquet('auction_convergence_memory.parquet'), safe_read_parquet('auction_reinforcement_memory.parquet')

**METHOD**: Procedural script body (functions may be empty)

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `safe_read_parquet( "auction_convergence_memory.parquet" )`
- `safe_read_parquet( "auction_reinforcement_memory.parquet" )`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

## state_transition_engine_v1.py

**PURPOSE**: Зафиксировать переходы модельного состояния по наблюдённым входам.

**SOURCE**: /app/state_transition_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 44eb92198e2942dafe27efa2fd25446acaf8b938e074fa193869c442aaf5ced6

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: safe_read_parquet(STATE_FILE)

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `load_parquet_cached("auction_synthesis_memory.parquet")`
- `load_parquet_cached("probabilistic_auction_memory.parquet")`
- `safe_read_parquet(STATE_FILE)`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

## adaptive_meta_cognition_engine_v1.py

**PURPOSE**: Добавить существующую оценку устойчивости/согласованности когнитивного состояния.

**SOURCE**: /app/adaptive_meta_cognition_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 8ad6db7822beda9a155190f37e20bf3bf51252ca1e5bf49f29c1f85e2bae5161

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: Ordered pipeline dependency guard + reader calls below; no claim of absent dependency

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `read_meta_reinforcement_with_evidence( resolve_read("auction_reinforcement_memory.parquet") )`
- `resolve_read("auction_reinforcement_memory.parquet")`

**METHOD EXPRESSIONS**:

- `pd.to_datetime(latest["timestamp"], utc=True)`

**OUTPUTS**:

- `publish_atomic_frame(row, "adaptive_meta_cognition_state.parquet", producer=__file__, writer=atomic_parquet_write, input_lineage=input_lineage)`

## mtf_availability_runtime_engine_v1.py

**PURPOSE**: Опубликовать собственную доступность TF и причины stale/missing, не копируя M15 на старшие TF.

**SOURCE**: /app/mtf_availability_runtime_engine_v1.py in SOURCES/INSTALLED/canonical-runtime.tar.gz

**SOURCE_SHA256**: 60ddef5f7ef475ab7adcec1f9ebd0ea6a35317131ef83af7f7186c3951782046

**OWNER**: canonical-runtime

**DATA**: Native declared input/output paths through saved path_registry and actual config

**TRIGGER**: Its ordered pipeline step after existing dependency guard

**DEPENDENCIES**: Ordered pipeline dependency guard + reader calls below; no claim of absent dependency

**METHOD**: Functions/script body as in source

**TRANSITIONS**: Pipeline RUNNING → SUCCESS / FAILED / TIMEOUT or dependency SKIP; domain state remains native code-defined

**FAILURE_BEHAVIOR**: Existing execution guard/status/atomic IO, no synthetic ready/default direction

**CONSUMERS**: Subsequent registered engines; native Publisher/availability consumers

**INPUTS**:

- `load_m15_candles()`

**METHOD EXPRESSIONS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.

**OUTPUTS**:

Resolved through native globals/dependencies in the saved full source; not inferred as empty.
