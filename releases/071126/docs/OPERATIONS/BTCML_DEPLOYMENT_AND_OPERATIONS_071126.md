# BTCML_DEPLOYMENT_AND_OPERATIONS_071126

Руководство по фактической установке 14 служб. R08 — дочерний процесс Paper, не контейнер №15. Источник истины: приватный `INVENTORY/containers.private.json`, exact image IDs, `SOURCES/INSTALLED` и сохранённые bind overlays. Старое рабочее дерево и старые Compose не заменяют эту конфигурацию. Торговые алгоритмы, fsync/ACK, лимиты и REAL этой работой не менялись.

Backup root далее обозначен `B`; это каталог `BTCML_BACKUP_071126` на подключённом накопителе. Абсолютное положение накопителя может измениться. Runtime Compose находится в `RESTORE/compose.restore.private.json`; он использует `BTCML_BACKUP_ROOT` и имена восстановленных volumes, а не `/Users/fontecrypto`. Исторические абсолютные пути в receipts остаются provenance, не переписываются.

## Значение показателей

CONFIGURED LIMIT — cgroup/daemon config, не измеренное потребление. MEASURED USAGE ниже — один общий исторический рабочий срез 07.11.2026 11:19:39 UTC, до обслуживания; CPU в ядрах, RAM — container working set. Он не является пиком или нормой. RSS детей из P0 — отдельные process samples, их нельзя складывать с working set. ACTUAL CYCLE берётся только из завершённого штатного лога с cycle_id. REQUIRED DEADLINE существует только там, где он задан действующим контрактом. Неизвестные пики, нормативы полного цикла и допустимые задержки обозначены NOT_ESTABLISHED, а не выдуманы из poll interval.

Контейнер RUNNING/healthy, свежий owner output, готовность source binding и PAPER OPEN — разные состояния. Успешный M15-переход и NO_ELIGIBLE_INITIATIVE не дают S0/S1 или LIVE_QUALIFIED. RESEARCH_OBSERVED разрешает только предусмотренный observer путь, не обход OPEN guards.

## Профиль рабочего места

Текущий host — Mac M1/8 GB; VM MemoryMiB=6144, SwapMiB=1024. Значения сохранены, не менялись. Образы — Linux/arm64; другой компьютер должен поддерживать эту платформу. Восстановление compiled images не требует исходного Mac, pip, npm или старого Git checkout. Полный дополнительный stack на том же 8-GB host не тестируется: для него потребовалась бы вторая копия state и RAM. Изолированные artifact checks явно отделены от FULL_RUNTIME_RESTORE.

Не запускать параллельно тяжёлую backup/restore проверку, replay или квалификацию. Startup тяжёлых аналитических owners разносить по штатным dependency-ready этапам. Период Publisher 900 s не обещает завершение за 900 s: зафиксированы overrun и пропуск missed slots. При плохом memory pressure остановить именно техническую проверку, не повышать лимиты и не закрывать приложения владельца.

## Точный состав

### 01. canonical-runtime

Назначение: Последовательный Stage1/Stage2 pipeline, run.py → runtime/pipeline.py.

- **Installed image:** `sha256:10b2575b15a71d3a7f1e0ea968613a65b6cc883fa743119533db9af86f783697`.
- **Команда:** `/usr/bin/tini -- /bin/sh /app/deploy/vps/entrypoints/canonical_runtime.sh`.
- **User / cwd:** `btcml` / `/app`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Watchdog feed и native Legacy outputs; после входной проверки dependency guard.
- **Mounts:** `/app/data` (volume, RW); `/app/data/legacy_sources` (volume, RO). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Полный проход затем RUNTIME_LOOP_DELAY=5 s. ENGINE_TIMEOUT_SECONDS по env, default 120 s; это deadline отдельного engine, не всего pipeline..
- **Выход:** cognition/*.parquet, runtime_engine_state, availability/metadata.
- **CONFIGURED LIMIT:** RAM unlimited (0), CPU unlimited (0); остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 1.4060177088110057 cores; RAM 899563520 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/canonical-runtime.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** Остановка прекращает новые Stage1 generations; атомарно опубликованные parquet остаются. Незавершённые temp не становятся подтверждённым output.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 02. context-refresh-daemon

Назначение: Publisher Final/Lifecycle/Context Phase четырёх TF; один causal child.

- **Installed image:** `sha256:8f5985fccb854353ed5953c1afde718431f7d3a54a3f60709bba24d5ffd6c9d6`.
- **Команда:** `/usr/bin/tini -- /bin/sh /app/deploy/vps/entrypoints/context_refresh_daemon.sh`.
- **User / cwd:** `btcml` / `/app`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Пригодные собственные native frames и Stage2 evidence; admission и source pins.
- **Mounts:** `/app/data` (volume, RW). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Monotonic interval 900 s. Пропущенные slots пропускаются, не ставятся в очередь полных циклов..
- **Выход:** live/primary_context_publication.json, live/context_refresh_daemon_status.json; own-TF Final/Lifecycle, phase generations.
- **CONFIGURED LIMIT:** RAM unlimited (0), CPU unlimited (0); остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.2802667616007857 cores; RAM 507879424 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/context-refresh-daemon.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** SIGTERM ставит stop flag; активный run_cycle завершается до выхода. Не обрывать публикацию SIGKILL.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 03. context-refresher

Назначение: Подготовка read-only visual projections из owner outputs.

- **Installed image:** `sha256:6ffcfeecb30c1795cd68e42d4bba69b757c87dae9f1321832da2395b510dd96f`.
- **Команда:** `/usr/bin/tini -- /bin/sh /app/deploy/vps/entrypoints/context_refresher.sh`.
- **User / cwd:** `btcml` / `/app`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Опубликованные Final/Lifecycle/trade/phase источники; /profile — диагностика.
- **Mounts:** `/app/apps/context_visualizer/public/data` (volume, RW); `/profile` (bind, RW); `/app/data` (volume, RW). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Штатный loop из entrypoint. Установленная проверка versions пропускает полный пересчёт неизменённых входов; точный период см. сохранённый command/env..
- **Выход:** visual public volume; /profile diagnostics.
- **CONFIGURED LIMIT:** RAM 805306368 bytes, CPU unlimited (0); остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.7170817651098901 cores; RAM 288792576 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/context-refresher.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** Остановка убирает новые visual projections, не меняет сделки или контексты.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 04. legacy-volume-memory

Назначение: Native Memory/Regime pair под IO wrapper.

- **Installed image:** `sha256:6b39b550576d4490f623b03f4c4f8205762c41bf9c9497ccf6e5f8a15d3954d1`.
- **Команда:** `/usr/bin/tini -- python -u /opt/btcml-legacy-memory-regime/legacy_pair_runtime.py --root /legacy`.
- **User / cwd:** `10001:10001` / `/legacy`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Текущий multi_exchange_flow snapshot из /legacy.
- **Mounts:** `/legacy` (volume, RW); `/opt/btcml-legacy-memory-regime` (bind, RO). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Родной цикл pair. Входной snapshot переиспользуется внутри прохода; формулы native unchanged..
- **Выход:** /legacy native Memory/Regime parquet и /legacy/ops provenance.
- **CONFIGURED LIMIT:** RAM 1073741824 bytes, CPU 1.0 cores; остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.2317411481687559 cores; RAM 198623232 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/legacy-volume-memory.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** Новые generations прекращаются; прежние атомарные публикации остаются.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 05. legacy-volume-reactions

Назначение: Native Reactions/Acceptance pair.

- **Installed image:** `sha256:6b39b550576d4490f623b03f4c4f8205762c41bf9c9497ccf6e5f8a15d3954d1`.
- **Команда:** `/usr/bin/tini -- python -u /opt/btcml-legacy-reactions-acceptance/legacy_pair_runtime.py --root /legacy`.
- **User / cwd:** `10001:10001` / `/legacy`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Текущий multi_exchange_flow snapshot из /legacy.
- **Mounts:** `/legacy` (volume, RW); `/opt/btcml-legacy-reactions-acceptance` (bind, RO). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Родной цикл pair; расчёты/AST admission сохранены..
- **Выход:** /legacy native Reactions/Acceptance и /legacy/ops.
- **CONFIGURED LIMIT:** RAM 1073741824 bytes, CPU 1.0 cores; остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.11497511716737144 cores; RAM 190095360 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/legacy-volume-reactions.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** Не подменять отсутствие нового output старой датой как fresh.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 06. legacy-volume-clusters

Назначение: Native Clusters/Inventory pair с текущим pass-local snapshot reuse.

- **Installed image:** `sha256:fd9540ab0d5bd8205912818f3be5e0961ee6ebed0c747945cd239c3fa8acb98c`.
- **Команда:** `/usr/bin/tini -- python -u /opt/btcml-legacy-pair/legacy_pair_runtime.py --root /legacy`.
- **User / cwd:** `10001:10001` / `/legacy`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** /legacy multi_exchange_flow + проверенные native source pins.
- **Mounts:** `/opt/btcml-legacy-pair` (bind, RO); `/legacy` (volume, RW). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Родной dispatch; один неизменный входной snapshot делится только внутри pair..
- **Выход:** /legacy native Clusters/Inventory + ops capture/published metadata.
- **CONFIGURED LIMIT:** RAM 1073741824 bytes, CPU 1.0 cores; остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.15879737973421384 cores; RAM 214188032 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/legacy-volume-clusters.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** Обёртка пишет temp, проверяет roundtrip и заменяет atomic. Технические partial отдельно от committed.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 07. legacy-multi-exchange

Назначение: Сборщик multi-exchange flow под IO runtime.

- **Installed image:** `sha256:6b39b550576d4490f623b03f4c4f8205762c41bf9c9497ccf6e5f8a15d3954d1`.
- **Команда:** `/usr/bin/tini -- python -u /opt/btcml-legacy-original/io_runtime.py /opt/btcml-legacy-original/multi_exchange_collector.py multi_exchange_flow.parquet`.
- **User / cwd:** `10001:10001` / `/legacy`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Реальные соединения сборщика; точные endpoints в сохранённом source.
- **Mounts:** `/legacy` (volume, RW). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Непрерывное получение, штатный flush/публикация исходного collector..
- **Выход:** /legacy multi_exchange_flow parquet, ops source evidence.
- **CONFIGURED LIMIT:** RAM 536870912 bytes, CPU 0.5 cores; остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.2937736211658196 cores; RAM 113569792 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/legacy-multi-exchange.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** При остановке возникает наблюдательный gap. Не восстанавливать его синтетически или незапрошенным историческим backfill.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 08. dashboard-ui

Назначение: Один nginx: Dashboard + встроенный Market Context/legacy Chart.

- **Installed image:** `sha256:326c04bea295e7676b7b226745d7ccfb22398626e3b4c6b315c6e2a52afcd391`.
- **Команда:** `/docker-entrypoint.sh nginx -g 'daemon off;'`.
- **User / cwd:** `image default` / `/`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Статика image, /visual-data RO, /release/manifest.json RO, внутренний ops-api.
- **Mounts:** `/release/manifest.json` (bind, RO); `/visual-data` (volume, RO). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** GET/static и запросы UI; модель не вычисляется..
- **Выход:** 127.0.0.1:15173; :18765 только Chart static/GET projection.
- **CONFIGURED LIMIT:** RAM unlimited (0), CPU unlimited (0); остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.00809602034807642 cores; RAM 8597504 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/dashboard-ui.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** UI liveness не является допуском PAPER. Остановка не останавливает владельцев торговых данных.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 09. ops-api

Назначение: Read-only FastAPI/WS транспорт owner данных и bounded Docker GET telemetry.

- **Installed image:** `sha256:45e4d228183d53e6470a4ded6196f310c6bdcb408c647983647d14afea40e53c`.
- **Команда:** `/usr/bin/tini -- python run_api.py`.
- **User / cwd:** `btcml` / `/app/dashboard/backend`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Data/visual RO, release manifest RO, Docker socket RO и действующий socket GID.
- **Mounts:** `/app/data` (volume, RO); `/app/apps/context_visualizer/public/data` (volume, RO); `/release/manifest.json` (bind, RO); `/var/run/docker.sock` (bind, RO). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Данные читаются по запросам/ограниченному transport cache. Docker counters требуют двух сопоставимых samples..
- **Выход:** 127.0.0.1:18080; health/runtime/chart projections.
- **CONFIGURED LIMIT:** RAM 1610612736 bytes, CPU unlimited (0); остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.05020858509731962 cores; RAM 42962944 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/ops-api.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** UNAVAILABLE/UNKNOWN сохраняются при отсутствии owner публикации. Не вычисляет новый PnL или торговые разрешения.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 10. collector-watchdog

Назначение: Watchdog штатных required collectors.

- **Installed image:** `sha256:ad31054879010c097ffeba7c2494788bfbfc42d48c0df07d3b577f6ad1d72b81`.
- **Команда:** `/usr/bin/tini -- /bin/sh /app/deploy/vps/entrypoints/collector_watchdog.sh`.
- **User / cwd:** `btcml` / `/app`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Сохранённая конфигурация collectors; в P0 фактически работал live_binance_feed_v2 child.
- **Mounts:** `/app/data` (volume, RW). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Существующий supervision loop, не отдельный новый collector..
- **Выход:** Feed parquet, collector heartbeats и штатные logs.
- **CONFIGURED LIMIT:** RAM unlimited (0), CPU unlimited (0); остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.14204877493344256 cores; RAM 137637888 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/collector-watchdog.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** Запускать имеющийся watchdog, не второй feed writer. Наличие collector в исходниках не доказывает его текущую работу.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 11. cognition-runtime

Назначение: LIVE1A Spot stream, архив raw_event_journal и provisional cognition.

- **Installed image:** `sha256:093f628a4c8e24245ff0a1de5e8c9fc527beeb14c6cefe74bc1255b094e69f21`.
- **Команда:** `/usr/bin/tini -- /bin/sh /app/deploy/vps/entrypoints/cognition_runtime.sh`.
- **User / cwd:** `btcml` / `/app`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Spot BTCUSDT aggTrade/bookTicker; нормализация source/session/receive metadata.
- **Mounts:** `/app/data` (volume, RW). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Receive непрерывен; архивный writer bounded, chunk policy в source: 50k events / 60 s, ZSTD..
- **Выход:** raw_market_events_v2; cognition/intrabar_context_events; runtime/intrabar_cognition_health.json.
- **CONFIGURED LIMIT:** RAM unlimited (0), CPU unlimited (0); остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.568840208009172 cores; RAM 273297408 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/cognition-runtime.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** SIGTERM закрывает WS/queue, writer.stop(flush=True). Реконструированный restore image проверен отдельно; исходный image store ID отсутствовал.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 12. paper-manager

Назначение: Единственный Paper writer; Futures receive, WAL/ACK, исполнение/сопровождение; штатный R08 child.

- **Installed image:** `sha256:b14405387e6a500cbfbfa33b41176aa11f242509cce5ea2b5f14ad3cbac11848`.
- **Команда:** `/usr/bin/tini -- /bin/sh /app/deploy/vps/entrypoints/financial_candidate_paper.sh --continuity-mode FLAT_START --fresh-live-domain paper-t0-20261104T182435Z`.
- **User / cwd:** `10001:10001` / `/app`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Native books/epoch, историческая provenance + выбранный release pins, действительные bindings, свежие Futures и BBO.
- **Mounts:** `/app/data/cognition` (volume, RO); `/app/data` (volume, RW); `/control` (bind, RO); `/app/config/qualified_paper_launcher.py` (bind, RO); `/paper-policy` (bind, RO); `/app/config/intrabar_paper_execution.qualified-anti-saw.json` (bind, RO); `/app/data/live` (volume, RO); `/run/btcml-financial-admission` (bind, RO); `/r08` (bind, RW). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Receive/ACK/SLTP непрерывны; один последовательный market worker; существующий poll/health loop..
- **Выход:** Paper WAL/checkpoints/books/financial heads, health и owner projections; /r08 producer outputs.
- **CONFIGURED LIMIT:** RAM 1610612736 bytes, CPU 2.0 cores; остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.27274908126166847 cores; RAM 279625728 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/paper-manager.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** SIGTERM закрывает owned R08, прекращает convergence, flush_durable(shutdown), освобождает append handle. Нет reset WAL/cursors. REAL=false обязателен.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 13. timeframe-manager

Назначение: Четыре независимых TF decisions → CommandBus.

- **Installed image:** `sha256:0d3dbee8c6043e054cec84335daa2e0eef233987f48ccbfeedad7fed4211a18b`.
- **Команда:** `/usr/bin/tini -- /bin/sh /app/deploy/vps/entrypoints/financial_trend_service.sh timeframe-manager`.
- **User / cwd:** `btcml` / `/app`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Собственные M15/M30/H1/H4 контексты, phase/strength, Paper state и genuine source bindings.
- **Mounts:** `/app/config/intrabar_paper_execution.qualified-anti-saw.json` (bind, RO); `/r08` (bind, RO); `/app/data/live` (volume, RO); `/app/data` (volume, RW); `/paper-policy` (bind, RO); `/app/config/qualified_paper_launcher.py` (bind, RO); `/control` (bind, RO); `/run/btcml-financial-admission` (bind, RO); `/app/data/cognition` (volume, RO). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Текущий daemon interval/poll; одинаковые evaluation/intent keys дедуплицируются..
- **Выход:** trading/manager/*, timeframe_command_memory, timeframe_manager_latest/health.
- **CONFIGURED LIMIT:** RAM unlimited (0), CPU unlimited (0); остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.671239121851321 cores; RAM 304300032 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/timeframe-manager.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** Не исполняет ордера. Missing descriptor/policy/source — техническая неготовность, не ожидание инициативы.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

### 14. intrabar-supervisor

Назначение: Существующий supervisor/наблюдатель execution служб.

- **Installed image:** `sha256:e0a531a874e4188d1c3f4a3c800e30e1c125e029ef421d098aad12b7acc737f1`.
- **Команда:** `/usr/bin/tini -- /bin/sh /app/deploy/vps/entrypoints/intrabar_supervisor.sh`.
- **User / cwd:** `btcml` / `/app`.
- **Конфигурация:** приватный container/environment snapshot; exact restore Compose и `CONFIG/HOST_BIND_MAPPING.private.json`. Секреты в публичный Git не входят.
- **Входные зависимости:** Paper/Timeframe owner health, control/config и shared runtime state.
- **Mounts:** `/app/data` (volume, RW). Source paths и volume subpaths полностью сохранены в приватном Compose.
- **Триггер:** Штатный supervision loop из сохранённой команды..
- **Выход:** runtime/intrabar_supervision_state.json и штатные журналы.
- **CONFIGURED LIMIT:** RAM unlimited (0), CPU unlimited (0); остальные pids/tmpfs/memswap/security flags — exact config.
- **MEASURED USAGE:** CPU 0.050317041942966746 cores; RAM 13066240 bytes, общий срез `2026-11-07T11:19:39 UTC`. Пик RSS/working set: NOT_ESTABLISHED этим срезом.
- **Процессы:** полный список основного процесса и children — `INVENTORY/intrabar-supervisor.processes.txt`; R08 в Paper на P0 не был активным child.
- **ACTUAL CYCLE / REQUIRED DEADLINE:** завершённые значения — журнал циклов и timing annex; универсальная длительность NOT_ESTABLISHED. Для publishers требуются действительные generation/source timestamps; для execution — имеющиеся freshness/availability guards.
- **Health/readiness:** текущие Docker State/Health и owner output должны проверяться отдельно; исторический health нельзя выдавать за свежий.
- **Остановка и восстановление:** Останавливается раньше управляемых execution writers; запускается после их действительного startup.
- **Проверка output:** прочитать штатный health, его timestamp, ссылку на committed generation и прогресс последнего source/event; существование файла само по себе недостаточно.

## COLD START / RESTORE FROM BACKUP

1. Использовать совместимый Docker/Compose с volume subpath support. Нужен свежий target: нельзя накладывать restore на существующие production containers/непустые volumes. Установка сохраняет project name `btcml-vps-smoke`: принятый OPS runtime observer фильтрует этот label. Это логический идентификатор, не зависимость от Mac. Не запускать второй полный stack рядом с действующим на 8 GB.
2. Проверить `SHA256SUMS`, coverage и `BACKUP_RESTORE_VERIFICATION.md`. INCOMPLETE package не является disaster recovery. Приватные environment/policy/control файлы остаются локальными.
3. Загрузить сохранённые images, без pull/build и без замены существующих чужих тегов:

```sh
B="/путь/к/MaksTiger/BTCML_BACKUP_071126"
docker load --input "$B/images.tar.gz"
docker load --input "$B/DOCKER_IMAGES/cognition.reconstructed-image.tar.gz"
```

4. Создать только новые пустые целевые named volumes. Данные каждого component распаковывает `RESTORE/restore_component.py`, запущенный из сохранённого Paper image под root только для восстановления файлов/UID/modes. Его `target` должен быть пустым. Main/legacy/visual — разные components. Не использовать обычный `tar -x` как готовый runtime: archive content links должны стать независимыми файлами; исходные настоящие hardlinks сохраняются отдельно. Скрипт проверяет SHA и fsync restored files/dirs.

```sh
docker volume create btcml_restore_071126_data
docker run --rm --log-driver none --network none --read-only --user 0 \
  --mount type=volume,source=btcml_restore_071126_data,target=/restore \
  --mount type=bind,source="$B",target=/backup,readonly \
  --entrypoint python sha256:b14405387e6a500cbfbfa33b41176aa11f242509cce5ea2b5f14ad3cbac11848 \
  -I /backup/RESTORE/restore_component.py /backup/VOLUMES/main.tar.zst /restore main
```

Аналогично восстановить legacy и visual в свои новые volumes. На новом host требуется место для полного логического restored state, а не только размера compressed archive. На Mac учитывать также свободное место файла backing VM; большое свободное место внутри Linux VM не означает свободный SSD Mac.

5. Bind snapshots из `CONFIG/HOST_MOUNTS` копируются в отдельный новый `BTCML_RUNTIME_ROOT/HOST_MOUNTS`; приложения никогда не получают mutable mount самого backup. Mappings — из `CONFIG/HOST_BIND_MAPPING.private.json`. Оригинальные working paths не перенастраивать наугад. На целевом runtime проверить create/write/rename/delete одного временного файла в restored RW mount именно UID/GID приложения; root/host write не подтверждает доступ приложения. Если Linux требует ownership, изменять только новый восстановленный runtime-каталог, не весь диск и не originals. Mac host UID не обязан численно совпадать с 10001.
6. Установить `BTCML_BACKUP_ROOT`, отдельный новый `BTCML_RUNTIME_ROOT`, `BTCML_VOLUME_PREFIX=btcml_restore_071126`, `DOCKER_SOCKET_GID` по фактическому gid сокета внутри runtime. Ни chmod 0777, ни root для постоянного API не нужны. `RESTORE/compose.restore.private.json` сохраняет исходных users/limits/subpaths. Cognition restore image имеет новый ID из `DOCKER_IMAGES/COGNITION_RECONSTRUCTION.json`: это проверенная реконструкция фактического rootfs, не байтовая идентичность старому image. `CONFIG/restore_release_manifest.json` явно описывает это; исторический approved manifest не изменяется.
7. Проверить `docker compose -f "$B/RESTORE/compose.restore.private.json" config --quiet`. Никакого `up` по старому рабочему Compose: он может вернуть ранние images/configs.

## Порядок штатного запуска и критерии startup

UI/API можно поднять первыми для наблюдения; пустые/stale owner данные должны оставаться UNKNOWN/UNAVAILABLE. Из data owners сначала Legacy collector/pairs и required feed watchdog; Cognition — независимый Spot consumer. Убедиться в advancing receive/committed native outputs и timestamps. Затем Canonical; дождаться действительного завершения/прогресса его первого прохода и пригодных собственных TF inputs. После этого Publisher; не накладывать его cold preparation на лишний специально запущенный цикл. Visual запускается как consumer публикаций.

Paper запускается только через сохранённый штатный entrypoint, с теми же native books, epoch, provenance и текущим release implementation manifest. Producer не обязан иметь INIT/descriptor до своего запуска: штатный owner создаёт их при действительных входах. R08 остаётся единственным дочерним процессом Paper. Ему нужны реальные новые Spot deliveries/ACK, наблюдённый prefix 300 s, реальные Context/policy и корректный first-eligible handoff. Нельзя брать исследовательский архив как новый LIVE prefix.

После Paper startup и настоящих source/descriptor/permission publications запускается Timeframe Manager, затем Intrabar. Проверять completed Manager cycle → command IDs → Paper cursor/ACK и отсутствие повторного эффекта. NO_ACTION с рыночной причиной допустим. Missing bindings, source process exit, stale transport или missing policy — конкретная техническая неготовность, не «ждём рынок».

Адресный запуск на **новом** target после восстановления:

```sh
docker compose -p btcml-vps-smoke -f "$B/RESTORE/compose.restore.private.json" up -d --no-deps --no-build --pull never legacy-multi-exchange
# Остальные компоненты — по одному, в указанном порядке и после их dependency-ready.
```

Не применять эту команду к текущей production installation без адресного install plan. Не использовать `--remove-orphans`, mass rebuild или reset.

## NORMAL RESTART / PARTIAL SERVICE RESTART

Использовать существующий container, не пересоздавать исправные соседние службы. Перед Paper restart проверить позиции, pending work, источник checkpoint и допустимость перерыва сопровождения. Остановить генерацию новых Manager-команд, штатно завершить Paper, дождаться durable flush. `docker stop --timeout -1 NAME` не заменять SIGKILL ради скорости. Затем `docker start NAME`; проверить новый timestamp owner status, правильный epoch/domain и продвигающийся именно processed/persisted cursor. Downloads не являются обработанными событиями.

Нормальный startup может проверять/восстанавливать committed state по существующим механизмам. Это не разрешение запускать отдельный исторический replay/backfill. Pre-T0 recovery запрещён. Старые commands, books и WAL не удаляются и не обнуляются. При давно устаревшем restored snapshot запуск с нового T0 возможен только штатным FLAT_START/fresh-live-domain механизмом, с проверкой фактических позиций и quarantining старых команд; это отдельное явно отмечаемое действие оператора, не ручной прыжок cursor и не переписывание старого domain.

## CONTROLLED STOP

Сначала Intrabar/Manager, затем Paper с durable WAL flush/append-handle close; Cognition закрывает receive/queue и flush writer. Publisher завершает активную публикацию по stop flag. Остальные writers прекращаются поддерживаемым lifecycle; их атомарно опубликованные generations остаются, incomplete temp отдельно обозначается. UI/API — read-only consumers. Согласованный cut записывается после выхода всех writers. Не копировать меняющийся WAL и не объявлять его консистентным.

## PAPER-ONLY MODE / защитные условия

Подтвердить `real_execution_enabled=false` в actual config и owner health, paper-only contract, отсутствие exchange execution. Не присваивать READY, OPEN, LIVE_QUALIFIED, S0/S1 вручную. Не ослаблять Trend Strength/Context Phase/DRA/R08, cost-aware sizing, SL/TP или позиционные блокировки. Старое financial approval описывает историческое состояние; текущие implementation pins берутся из принятого выбранного release. Одно не переименовывает другое.

## Неисправности и DISASTER RECOVERY

- Нет свежих Final/Lifecycle: проверить их собственного owner, TF, generation и доступность входов; не копировать M15 в старшие TF.
- Нет descriptor/source/permission: проверить Paper-owned producer и точный missing input; не создавать фиктивную permission и не называть это ожиданием рынка.
- Старый health: сопоставить timestamp, checkpoint и процессы. Barrier может удерживать progress; текущий processed cursor отличается от downloaded/recovery buffer.
- ENOSPC/EIO: прекратить дополнительные writes/starts, сохранить WAL и disk image, обеспечить реальное место host. Не удалять Docker.raw, volumes или последние backups. В инциденте 07.11 причиной лишнего расхода оказался **maintenance binary stdout с json-file logging**. Исправлено `--log-driver=none` только у temporary backup readers; обычные app logs сохранены. Kernel EIO требует повторной проверки сохранённых heads/checkpoints и file checksums, а не заявления «данные целы» без проверки.
- Broken image metadata: не подменять старым похожим tag. Для Cognition сохранён фактический rootfs + metadata и отдельно проверенный reconstructed image. Смена restore identity отражена явно.

Восстановление не должно быть зависимо от старого GitHub/Gitea доступа или рабочего checkout. Backup содержит images, code, private configs и state. GitHub — публичная кодовая/документационная часть; private backup, WAL и книги туда не публикуются. После обслуживания подтвердить 14 actual services, свежие timestamps, version 071126 и REAL DISABLED; market entry readiness сообщать отдельно.
<!-- CLEANUP_REVISION_20261108 -->

## Схемы зависимостей и восстановления — 08.11.2026

[Все14 контейнеров](../ARCHITECTURE_DIAGRAMS/02A_FOURTEEN_CONTAINERS_OVERVIEW.svg) · [подробные IO](../ARCHITECTURE_DIAGRAMS/02_ALL_14_CONTAINERS_C4_L2.svg) · [startup/readiness/failure graph](../ARCHITECTURE_DIAGRAMS/08_STARTUP_READINESS_FAILURE_DEPENDENCIES.svg).

Это порядок готовности данных, не отсутствующие Compose depends_on. Market owners независимы; сначала нужны их действительные source generations, затем admitted native/Canonical inputs, Publisher own contexts и readers. Paper проверяет историческую financial provenance отдельно от current release implementation pins до writer. R08 запускается только существующим Paper child launcher при штатных bootstrap gates; baseline/INIT/descriptor заранее не выдумываются. Manager читает фактически опубликованные bindings. Политика и descriptor — технические входы: их отсутствие означает BLOCKED, не ожидание рынка.

OBSERVE/NO_ACTION допустимы только при действительных необходимых технических входах и неудовлетворённых рыночных условиях. STALE — просроченный owner output; RUNNING/healthy не превращает его в свежий. Недостающий seal первого неполного бара остаётся WAITING_FOR_COVERAGE. Не запускать дополнительный R08 collector, второй writer или восстановление до T0.

Эта cleanup-ревизия не выполняла restart, новый capture, replay, финансовую квалификацию или новую проверку торгового допуска. Приведённые выше historical CPU/RAM и configured periods не являются нормативами или свежим рабочим срезом. Актуальные 14 identities и REAL flags проверены отдельно в cleanup report.
