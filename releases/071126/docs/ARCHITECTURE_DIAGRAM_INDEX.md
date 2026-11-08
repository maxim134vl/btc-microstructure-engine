# Architecture diagram index — release 071126

Revision: 8 November 2026. The diagrams describe accepted installed source/configuration. They do not assert current market freshness, S0/S1 or PAPER admission. All detailed blocks and edges have owner, input, output, consumer and exact SHA/source anchors in [the source index](ARCHITECTURE_DIAGRAMS/ARCHITECTURE_SOURCE_INDEX.md).

[Machine-readable source index](ARCHITECTURE_DIAGRAMS/ARCHITECTURE_SOURCE_INDEX.json). The index covers 60 exact files. SVG is the primary zoomable format; PNG is the documentation preview; DOT is editable.

| Diagram | SVG | PNG | Editable source |
|---|---|---|---|
| 1 / SYSTEM CONTEXT · C4 L1 | [SVG](ARCHITECTURE_DIAGRAMS/01_SYSTEM_CONTEXT_C4_L1.svg) | [PNG](ARCHITECTURE_DIAGRAMS/01_SYSTEM_CONTEXT_C4_L1.png) | [DOT](ARCHITECTURE_DIAGRAMS/01_SYSTEM_CONTEXT_C4_L1.dot) |
| 2 / ALL 14 CONTAINERS · C4 L2 | [SVG](ARCHITECTURE_DIAGRAMS/02_ALL_14_CONTAINERS_C4_L2.svg) | [PNG](ARCHITECTURE_DIAGRAMS/02_ALL_14_CONTAINERS_C4_L2.png) | [DOT](ARCHITECTURE_DIAGRAMS/02_ALL_14_CONTAINERS_C4_L2.dot) |
| 3 / STAGE1 · SOURCE AND DERIVATION DFD | [SVG](ARCHITECTURE_DIAGRAMS/03_STAGE1_SOURCE_AND_DERIVATION_DFD.svg) | [PNG](ARCHITECTURE_DIAGRAMS/03_STAGE1_SOURCE_AND_DERIVATION_DFD.png) | [DOT](ARCHITECTURE_DIAGRAMS/03_STAGE1_SOURCE_AND_DERIVATION_DFD.dot) |
| 4 / STAGE2 / CONTEXT / R08 / ADMISSION | [SVG](ARCHITECTURE_DIAGRAMS/04_STAGE2_CONTEXT_R08_ADMISSION.svg) | [PNG](ARCHITECTURE_DIAGRAMS/04_STAGE2_CONTEXT_R08_ADMISSION.png) | [DOT](ARCHITECTURE_DIAGRAMS/04_STAGE2_CONTEXT_R08_ADMISSION.dot) |
| 5 / FOUR INDEPENDENT TIMEFRAME CONTEXTS | [SVG](ARCHITECTURE_DIAGRAMS/05_FOUR_INDEPENDENT_TIMEFRAME_CONTEXTS.svg) | [PNG](ARCHITECTURE_DIAGRAMS/05_FOUR_INDEPENDENT_TIMEFRAME_CONTEXTS.png) | [DOT](ARCHITECTURE_DIAGRAMS/05_FOUR_INDEPENDENT_TIMEFRAME_CONTEXTS.dot) |
| 6 / TRADING DECISION / COMMAND / PAPER EXECUTION | [SVG](ARCHITECTURE_DIAGRAMS/06_TRADING_DECISION_COMMAND_PAPER_EXECUTION.svg) | [PNG](ARCHITECTURE_DIAGRAMS/06_TRADING_DECISION_COMMAND_PAPER_EXECUTION.png) | [DOT](ARCHITECTURE_DIAGRAMS/06_TRADING_DECISION_COMMAND_PAPER_EXECUTION.dot) |
| 7 / PERSISTENCE / HISTORY / TRAINING | [SVG](ARCHITECTURE_DIAGRAMS/07_PERSISTENCE_HISTORY_TRAINING.svg) | [PNG](ARCHITECTURE_DIAGRAMS/07_PERSISTENCE_HISTORY_TRAINING.png) | [DOT](ARCHITECTURE_DIAGRAMS/07_PERSISTENCE_HISTORY_TRAINING.dot) |
| 8 / STARTUP / READINESS / FAILURE DEPENDENCIES | [SVG](ARCHITECTURE_DIAGRAMS/08_STARTUP_READINESS_FAILURE_DEPENDENCIES.svg) | [PNG](ARCHITECTURE_DIAGRAMS/08_STARTUP_READINESS_FAILURE_DEPENDENCIES.png) | [DOT](ARCHITECTURE_DIAGRAMS/08_STARTUP_READINESS_FAILURE_DEPENDENCIES.dot) |
| 02A / Compact fourteen-container overview | [SVG](ARCHITECTURE_DIAGRAMS/02A_FOURTEEN_CONTAINERS_OVERVIEW.svg) | [PNG](ARCHITECTURE_DIAGRAMS/02A_FOURTEEN_CONTAINERS_OVERVIEW.png) | [DOT](ARCHITECTURE_DIAGRAMS/02A_FOURTEEN_CONTAINERS_OVERVIEW.dot) |

Diagram02 is deliberately detailed; use02A for navigation and02/source-index for exact IO. Long health observations are dotted and do not impose a producer ordering. Diagram08 is a data/readiness graph; the actual Compose depends_on lists are empty, so its arrows are not invented Compose prerequisites.

Market context is an owned observation. A trade signal is a decision made under existing guards. A position is committed Paper state. Execution is the single writer applying a valid command. CTX IDs, command IDs and trade IDs remain distinct.

The current live PAPER books have no demonstrated automatic bridge into the historical canonical Master. Diagram07 keeps those worlds separate. Future synthetic corpus is NOT_IMPLEMENTED and has no fabricated runtime arrow.

Raw/source time, local receive/order, ACK availability and owner publication availability retain their original clock domains. File copy/mtime does not confer historical availability. The approved R08 rate is literal unsigned Spot q divided by contributor T-span in seconds; neither Q/300 nor EWMA is substituted.
