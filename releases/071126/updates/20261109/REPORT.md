# BTC-ML — accepted071126 source delta and migration candidate

**SOURCE CONSOLIDATION: READY FOR REVIEW. MIGRATION READY: NOT READY.** Принятый071126 сохранён и дополнен доказанной дельтой09.11; Linux/AMD64 и фактический перенос текущего mutable state ещё не подтверждены. Production и обе основные ветки release не изменены.

## 1. Сначала сохранённая база, затем дельта

Уточнение владельца учтено: проверена отдельная существующая GitHub-публикация071126, которую прошлый аудит локального Gitea worktree не учёл. Receipt07.11 фиксирует release8f45e026… и canonical45efea61… как pushed/remote-heads-verified. Локальный сохранённый release clean на3e5c07fc… содержит тот же принятый source с последующими docs/cleanup. Новый candidate — его прямое продолжение, не альтернативная версия. Исторические manifests не переписывались.

Проверены8113 исходных Git blob IDs относительно опубликованного8f45…,8102 non-UI записи backup index и SHA13 source-архивов (30,165,409B), без пересмотра миллионов data/corpus файлов. Из8116 current service/source пар8104 уже сохранены без изменений; дельта ровно12файлов:3new/9modified в3owners. Image IDs остальных11служб совпали с071126. [RECONCILIATION_071126.md](<RECONCILIATION.md>).

Ошибочно выбранный до уточнения flat Gitea candidate0972c6cd и его упаковочные images оставлены как промежуточные доказательства, **не входят в authority или deployment этого релиза**. Повторный Cognition recovery, сделанный до обнаружения готового artifact, также не используется. Приоритет имеют уже сохранённые071126 исходники/receipts/images.

## 2. Состав и diff

Worktree: `the accepted071126 candidate worktree`; branch `candidate/071126-runtime-delta-20261109`. Source inputs commit: `3f29967c295290aebb9ea0e8722213bc128452f2`, parent3e5c07fc…. Старые `releases/071126/components`, source manifests, docs и restore material неизменны. Добавление находится только в `releases/071126/updates/20261109`. Полный source index теперь12385records (base+3new;9 источников заменяются явными refs на delta). SHA resolved manifest: `ab4205964fe284e23d623c6963ece5cb58e0b610e8de52f9f57058107f892063`.

| Owner | Runtime file | Delta | Accepted SHA256 |
| --- | --- | --- | --- |
| collector-watchdog | /app/feed_gap_recovery.py | ADDED | fde3a91c2934624c4ef4a287103e10bf0c17fa209c9c4849f57807b599d8f492 |
| collector-watchdog | /app/live_binance_feed_v2.py | MODIFIED | 1fedd0de643fc48f41f40fff60d95d32c283fc87d91b7ef571bc315ec583d289 |
| canonical-runtime | /app/auction_parquet_io.py | ADDED | bd7dc0e76544cf4ecc8d0852af6d99a04f7e120bf1381f25a8deddff76d09398 |
| canonical-runtime | /app/auction_synthesis_engine_v1.py | MODIFIED | 1e6b3a18db0db14f94b55cc062beb810f1df6a3fa1c1c76f3fc08fce0336fbde |
| canonical-runtime | /app/engine_worker.py | MODIFIED | 830c0f93a2c259e90f93e50e1e5132cba36325cbaba3493462a7dbd9608ef033 |
| canonical-runtime | /app/live_feed_paths.py | MODIFIED | fde9403ca048191a9bfd7176d6a938d48bfcf606cc483b613afe582b58206130 |
| canonical-runtime | /app/runtime_engine_guard.py | MODIFIED | 21b6860040b697f11916086e0b5d4b9aa334990ddeb02a52621a2f1515c568d1 |
| canonical-runtime | /app/src/btc_ml/runtime/canonical_candle_lane.py | ADDED | 8b97400e46cf15a801d6dd811fe4af453d69177b565e6e5eefbe4bd0177192ae |
| canonical-runtime | /app/src/btc_ml/runtime/pipeline.py | MODIFIED | 72661eda10890e53d73e69aa8f6eb51fbfb42d26bfafa39338d322beb4fca33d |
| canonical-runtime | /app/state_manager_v1.py | MODIFIED | 505c8db51166a5a65940c19133da29e78c09e166fa8da123c86f60a636895785 |
| canonical-runtime | /app/storage/path_registry.py | MODIFIED | 70204d4bcfaf69fc867bec0e38fdab6eca142f16be41dc717c8c7dc2ec9ebe7a |
| context-refresh-daemon | /app/src/btc_ml/external_traders/context_stage2_evidence.py | MODIFIED | 1c81b8b590aab23262467c94bb6c43b4aa9d53cf43e24e19c7d1d95eab160544 |

R08, Paper, Timeframe, Intrabar, Shadow, Legacy/Visual и frontend071126 не консолидировались заново: их source bytes и installed IDs совпадают с сохранённым релизом. Формулы, guards, accounting, baseline300s, JournalV3, ACK/fsync/WAL и single writer не менялись. Diff относительно принятого source base — добавление12overrides плюс metadata/tests/recipes; удалений старого source нет. Дополнительный diff к receipt8f45 отдельно сохранён, включая ранее принятые docs-only изменения.

## 3. Образы и воспроизводимое подключение

| Service | Installed09.11 | Candidate / preserved restore | Operation |
| --- | --- | --- | --- |
| canonical-runtime | sha256:1ba14bd049320df03b4945ef1dfe625359dfb4c864a9246d7280950a9d4974f4 | sha256:99908a60f82c0972ce8c1fa9ec6ee8c4b746883b65633d359419eccbc30d645c | ACCEPTED_OWNER_DELTA |
| cognition-runtime | sha256:093f628a4c8e24245ff0a1de5e8c9fc527beeb14c6cefe74bc1255b094e69f21 | sha256:348073d3a7300d3a402bea47f770505486ce4b4f6112f1c2f1b59e57e62540e8 | UNCHANGED_071126_REUSED |
| collector-watchdog | sha256:e08a62c3f50cfd1aad2910b52f35f5ad7def5a22cb13324c7334bab486520e00 | sha256:474b09f83c1752805996a8298e27ec60f53c3f2fab5b9116ed7fe82cfe688756 | ACCEPTED_OWNER_DELTA |
| context-refresh-daemon | sha256:24650abb4bb2203dfa2d56b3dc05347439b1974016c13efc949a5c0bad4f03cf | sha256:1d1393564c5c1cdaee5c5b7c65bac1a043fe35adaf4c26a9a079d6b70036adaa | ACCEPTED_OWNER_DELTA |
| context-refresher | sha256:6ffcfeecb30c1795cd68e42d4bba69b757c87dae9f1321832da2395b510dd96f | sha256:6ffcfeecb30c1795cd68e42d4bba69b757c87dae9f1321832da2395b510dd96f | UNCHANGED_071126_REUSED |
| dashboard-ui | sha256:326c04bea295e7676b7b226745d7ccfb22398626e3b4c6b315c6e2a52afcd391 | sha256:326c04bea295e7676b7b226745d7ccfb22398626e3b4c6b315c6e2a52afcd391 | UNCHANGED_071126_REUSED |
| intrabar-supervisor | sha256:e0a531a874e4188d1c3f4a3c800e30e1c125e029ef421d098aad12b7acc737f1 | sha256:e0a531a874e4188d1c3f4a3c800e30e1c125e029ef421d098aad12b7acc737f1 | UNCHANGED_071126_REUSED |
| legacy-multi-exchange | sha256:6b39b550576d4490f623b03f4c4f8205762c41bf9c9497ccf6e5f8a15d3954d1 | sha256:6b39b550576d4490f623b03f4c4f8205762c41bf9c9497ccf6e5f8a15d3954d1 | UNCHANGED_071126_REUSED |
| legacy-volume-clusters | sha256:fd9540ab0d5bd8205912818f3be5e0961ee6ebed0c747945cd239c3fa8acb98c | sha256:fd9540ab0d5bd8205912818f3be5e0961ee6ebed0c747945cd239c3fa8acb98c | UNCHANGED_071126_REUSED |
| legacy-volume-memory | sha256:6b39b550576d4490f623b03f4c4f8205762c41bf9c9497ccf6e5f8a15d3954d1 | sha256:6b39b550576d4490f623b03f4c4f8205762c41bf9c9497ccf6e5f8a15d3954d1 | UNCHANGED_071126_REUSED |
| legacy-volume-reactions | sha256:6b39b550576d4490f623b03f4c4f8205762c41bf9c9497ccf6e5f8a15d3954d1 | sha256:6b39b550576d4490f623b03f4c4f8205762c41bf9c9497ccf6e5f8a15d3954d1 | UNCHANGED_071126_REUSED |
| ops-api | sha256:45e4d228183d53e6470a4ded6196f310c6bdcb408c647983647d14afea40e53c | sha256:45e4d228183d53e6470a4ded6196f310c6bdcb408c647983647d14afea40e53c | UNCHANGED_071126_REUSED |
| paper-manager | sha256:b14405387e6a500cbfbfa33b41176aa11f242509cce5ea2b5f14ad3cbac11848 | sha256:b14405387e6a500cbfbfa33b41176aa11f242509cce5ea2b5f14ad3cbac11848 | UNCHANGED_071126_REUSED |
| timeframe-manager | sha256:0d3dbee8c6043e054cec84335daa2e0eef233987f48ccbfeedad7fed4211a18b | sha256:0d3dbee8c6043e054cec84335daa2e0eef233987f48ccbfeedad7fed4211a18b | UNCHANGED_071126_REUSED |

Только3официальных delta-image построены от точных071126 bases ad310548…/10b2575b…/8f5985fc…. Base layers сохранены; исходная image Config отличается лишь уже принятой Canonical `PYTHONFAULTHANDLER=1`. Python/native версии всех13Pythonowners совпадают с071126. Dockerfile и digest-checked builder находятся в `build/` и `build_delta.py`; никаких pip/npm ranges, новых fallback либо сетевых RUN не использовано. Для неизменённых11roles применяется загрузка уже проверенного immutable071126 artifact, а не лишний rebuild.

Новый archive3images: `071126-nov9-delta-images.tar`, 375571968B, SHA `6c6015a053b38ef709383891216b8a6a1474cf3048e1d6eb8850e891f2cf3899`. Он дополняет существующий backup, не заменяет его. Полный14-role specification: [compose.json](<deployment/compose.json>); environment key names, private bindings, volume variables и existing code-bind paths включены. Public configuration не содержит секретов или production-state payload. Parse PASS;14/14 commands/users/RO/mount targets/subpaths/limits/network-none boundaries сверены с исходным current config. Доступ к восстановленным private paths требует обычной target-проверки; число UID владельца Mac не объявляется универсальным Linux access proof.

## 4. Cognition — повторная реконструкция не требуется

Используется ранее подготовленный `348073d3a7300d3a402bea47f770505486ce4b4f6112f1c2f1b59e57e62540e8` из `BTCML_BACKUP_071126/DOCKER_IMAGES/cognition.reconstructed-image.tar.gz` (SHA bfc0e2e…). В backup уже есть load/create/import proof846source hashes, UID10001/cwd/app checks. Текущие810Cognition source entries совпадают с опубликованной сохранённой версией; installed093f… не менялся. Original OCI metadata093f… отсутствуют, но это **не означает отсутствие сохранённого restore artifact**. Идентичность original и reconstructed images не заявляется.

## 5. Regression / compile / parity

| Check | Result | Count / scope |
| --- | --- | --- |
| feed-gap-recovery | PASS | 16 |
| canonical-ordering-restart | PASS | 24 |
| canonical-arrow-native-exit | PASS | 69 |
| guards-paper-manager | PASS | 29 |
| guards-timeframe-manager | PASS | 29 |
| publisher-current-code-regression | PASS | 9 |
| final-three-image-source-owner-mode-dependencies | PASS | 3 |
| changed-code-compilation | PASS | 12 |

Feed16PASS; Canonical ordering24PASS (260saved genuine rows, FIFO2, restart, ordering, pins and no duplicate effects); Arrow69PASS (index/schema/Auction/receipts, active recovery and16short children/native cleanup); Publisher9PASS on the actual final image. Guards29+29PASS create no permissions. Финальные3images прошли2483file SHA/UID/mode checks и150dependency pins; все12изменённых Pythonfiles compiled. Сопоставительные регрессии, завершившиеся на промежуточной упаковке до уточнения, сохранены как проверка **тех же bytes/native dependencies**, не как новый accepted release base. Итоговые3delta-images отдельно проверены. Никакие production volumes, market sockets, R08 launch или full replay не использовались.

Broad provisional whole-bundle compile не выдан за PASS:9checks остановились на существующем `initiative_memory_engine.py:78`. Файл и его ошибка уже в071126, в проверенных entrypoint/pipeline ссылок не найдено; доказательство полного неиспользования не заявлено. Код сохранён, не удалён и не исправлен. Targeted paths и действительная delta compile прошли. Предупреждение Pandas на намеренно invalid timestamp в Publisher rejection fixture ожидаемо; rejection/result сохранились. Это не production throughput A/B или новая trading qualification.

## 6. ARM64 / AMD64 / не перенесённые данные

Linux/ARM64: source+frozen-artifact reconstruction воспроизводима по pinned bases и SHA, bounded regressions PASS; исходные071126 artifacts/restore tooling повторно не создавались. Полный second-stack14-service restore в этом задании не запускался. Linux/AMD64: NOT_VERIFIED. Нужны явные native bases, соответствующие Python/native locks, ABI checks и те же output/cleanup regressions на выбранной native AMD64 системе. Builder явно отклоняет AMD64; ARM64-эмуляция не подставлена как доказательство.

Намеренно не перенесены в Git: live volumes, WAL/books/positions/cursors, /r08 capture/runtime, private policy/approval/descriptor bindings и credentials. Они перечислены в inventory и уже сохранённом backup; current09.11state не выдаётся за cut07.11. Перед реальной миграцией нужен согласованный свежий consistent state handoff без rollback/reset/pre-T0 replay. Ни данные, ни source backup не изменялись для подготовки candidate.

## 7. Оставшийся долг и заключение

| Priority | Issue | Status / next step |
| --- | --- | --- |
| P0 (Linux/AMD64 target) | No native AMD64 bases/ABI/output regression evidence; ARM64 artifacts cannot be silently substituted. | NOT_VERIFIED; builder refuses AMD64 Explicit AMD64 bases and platform locks, then same bounded regressions on native target. |
| P0 (actual state migration) | Current writers advanced after the verified Nov7 backup cut. No fresh consistent Nov9 full-state handoff was made under the no-runtime-change restriction. | Prerequisite; no rollback/reset is performed Separately controlled current state handoff; preserve books/WAL/cursors/active and pending generations. |
| P1 | Feed safe_append_candle ignores metadata ok:false and suppresses exceptions; isolated16-case harness stubs metadata success. | Accepted behavior preserved; not changed by source consolidation Separate narrow failure/retry change with a boundary test, retaining owner truth. |
| P1 | Fresh dependency-from-scratch/AMD64 build is not equivalent to the verified frozen ARM64 artifact path. Generic historical recipes contain ranges. | Frozen-base reproduction is pinned and verified; no range resolver used Platform-specific clean base recipe/locks when preparing the native AMD64 target. |
| P2 / applicability unproven | Bundled initiative_memory_engine.py:78 contains a pre-existing SyntaxError. Nine broad provisional image compilation checks stopped there. | Same saved071126 bytes; no reference found in checked entrypoints/pipeline, but exhaustive non-use is not claimed. Not rewritten or deleted. Actual12 changed files compile and targeted runtime paths pass. Separate scoped ownership/use review before any repair or removal. |
| P2 | Local dirty Gitea root is distinct from the already published accepted071126 source authority. Inherited labels alone are incomplete provenance. | Corrected by explicit published-base reconciliation; existing publication and backup reused Use accepted071126 plus this additive delta; do not promote the provisional flat candidate. |

Предыдущие выводы audit о полной утрате source в Git и отсутствии Cog restore уточнены: они относились к dirty Gitea checkout, а полный опубликованный071126 и восстановленный Cog artifact уже существовали. Повторное создание R08/Execution/frontend source и Cog restore не требуется. Реальная недостающая source-дельта12файлов теперь имеет однозначные bytes, commit, recipes, image links и regression evidence.

**MIGRATION READY: NOT READY для фактического Linux/AMD64/current-state переноса. SOURCE CANDIDATE: READY FOR REVIEW.** Остались target-architecture validation и свежий controlled state handoff; source consolidation не заменяет эти этапы. Никакого автоматического merge, push, deployment или старта R08.

14/14 исходных служб RUNNING; ID/images/StartedAt/restart counts сохранены. Основная Gitea release HEAD/index/status и существующая publication release HEAD/status неизменны; контрольные SHA backup совпали. REAL_DISABLED в предусмотренных runtime flags. [final_preservation.json](<evidence/final-preservation.json>).
