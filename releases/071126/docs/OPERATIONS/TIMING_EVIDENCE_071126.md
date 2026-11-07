# Timing evidence and resource scope —071126

These are existing ordinary log records from the P0 capture, not newly run performance tests. Full original bounded tails remain private in the backup. A cycle ID separates passes. Overrun is not network delay; wall minus CPU is not asserted as pure disk I/O. Missing CPU/peak values remain NOT_ESTABLISHED.

| Service | Timestamp | Event / cycle | Measured time | Outcome |
| --- | --- | --- | --- | --- |
| context-refresh-daemon | 2026-11-06T23:02:16.501148Z | REFRESH_FAILED / 20261106T221600Z-26 | duration_s=2775.351 | REFRESH_FAILED |
| context-refresh-daemon | 2026-11-06T23:02:16.529067Z | REFRESH_INTERVAL_OVERRUN / 20261106T221600Z-26 | cycle_duration_seconds=2775.428327; configured_interval_seconds=900.0 | owner log event |
| context-refresh-daemon | 2026-11-06T23:35:16.769679Z | REFRESH_SUCCESS / 20261106T231601Z-27 | duration_s=1155.615 | REFRESH_SUCCESS |
| context-refresh-daemon | 2026-11-06T23:35:16.778249Z | REFRESH_INTERVAL_OVERRUN / 20261106T231601Z-27 | cycle_duration_seconds=1155.798453; configured_interval_seconds=900.0 | owner log event |
| context-refresh-daemon | 2026-11-06T23:52:38.051590Z | REFRESH_FAILED / 20261106T234600Z-28 | duration_s=397.009 | REFRESH_FAILED |
| context-refresh-daemon | 2026-11-07T00:21:40.614678Z | REFRESH_SUCCESS / 20261107T000100Z-29 | duration_s=1239.614 | REFRESH_SUCCESS |
| context-refresh-daemon | 2026-11-07T00:21:40.615970Z | REFRESH_INTERVAL_OVERRUN / 20261107T000100Z-29 | cycle_duration_seconds=1239.794102; configured_interval_seconds=900.0 | owner log event |
| context-refresh-daemon | 2026-11-07T00:45:58.194263Z | REFRESH_SUCCESS / 20261107T003100Z-30 | duration_s=897.336 | REFRESH_SUCCESS |
| context-refresh-daemon | 2026-11-07T00:46:02.403432Z | PIPELINE_PENDING / 20261107T004600Z-31 | duration_s=1.588 | PIPELINE_PENDING |
| context-refresh-daemon | 2026-11-07T01:13:55.196520Z | REFRESH_SUCCESS / 20261107T010101Z-32 | duration_s=773.889 | REFRESH_SUCCESS |
| context-refresh-daemon | 2026-11-07T01:16:04.274480Z | PIPELINE_PENDING / 20261107T011601Z-33 | duration_s=2.9 | PIPELINE_PENDING |
| context-refresh-daemon | 2026-11-07T07:09:30.735709Z | REFRESH_SUCCESS / 20261107T013101Z-34 | duration_s=20309.355 | REFRESH_SUCCESS |
| context-refresh-daemon | 2026-11-07T07:09:30.764517Z | REFRESH_INTERVAL_OVERRUN / 20261107T013101Z-34 | cycle_duration_seconds=20309.313145; configured_interval_seconds=900.0 | owner log event |
| context-refresh-daemon | 2026-11-07T07:27:44.433639Z | REFRESH_FAILED / 20261107T071601Z-35 | duration_s=702.832 | REFRESH_FAILED |
| context-refresh-daemon | 2026-11-07T08:32:45.118602Z | REFRESH_SUCCESS / 20261107T073101Z-36 | duration_s=3703.446 | REFRESH_SUCCESS |
| context-refresh-daemon | 2026-11-07T08:32:45.123744Z | REFRESH_INTERVAL_OVERRUN / 20261107T073101Z-36 | cycle_duration_seconds=3703.386933; configured_interval_seconds=900.0 | owner log event |
| context-refresh-daemon | 2026-11-07T09:36:09.733268Z | REFRESH_FAILED / 20261107T084603Z-37 | duration_s=2999.649 | REFRESH_FAILED |
| context-refresh-daemon | 2026-11-07T09:36:09.958549Z | REFRESH_INTERVAL_OVERRUN / 20261107T084603Z-37 | cycle_duration_seconds=3004.864591; configured_interval_seconds=900.0 | owner log event |
| context-refresh-daemon | 2026-11-07T10:37:37.788515Z | REFRESH_FAILED / 20261107T094601Z-38 | duration_s=3095.797 | REFRESH_FAILED |
| context-refresh-daemon | 2026-11-07T10:37:37.796305Z | REFRESH_INTERVAL_OVERRUN / 20261107T094601Z-38 | cycle_duration_seconds=3095.755957; configured_interval_seconds=900.0 | owner log event |
| context-refresh-daemon | 2026-11-07T11:13:30.941778Z | REFRESH_FAILED / 20261107T104601Z-39 | duration_s=1648.801 | REFRESH_FAILED |
| context-refresh-daemon | 2026-11-07T11:13:30.978972Z | REFRESH_INTERVAL_OVERRUN / 20261107T104601Z-39 | cycle_duration_seconds=1648.961065; configured_interval_seconds=900.0 | owner log event |
| context-refresh-daemon | 2026-11-07T11:50:21.328422Z | REFRESH_SUCCESS / 20261107T111602Z-40 | duration_s=2059.139 | REFRESH_SUCCESS |
| context-refresh-daemon | 2026-11-07T11:50:21.334363Z | REFRESH_INTERVAL_OVERRUN / 20261107T111602Z-40 | cycle_duration_seconds=2059.24949; configured_interval_seconds=900.0 | owner log event |

Historical accepted report boundaries: Publisher native-pass fixture and previous optimization measurements are in the engineering source reports, with wall/CPU/RSS and identical input scope. They are not whole production cycle measurements. The original historical6307.5s cycle and 900s schedule are not a real-time guarantee. Later successful and failed ordinary cycles are recorded above, without claiming different workload sizes are exact A/B.

Initial runtime API resource frame at2026-11-07T11:19:39.403609UTC measured4.966 Docker cores and3.234GiB container working set, system statusDEGRADED. This is not total Mac/VM RAM or a peak. All14 service per-role measurements and configured caps are in the operations cards. They cannot be combined with another interval's CPU or multiplied into a capacity claim.

Deployment incidents prior to preservation include R08 source process failure/overflow, memory pressure and Publisher/Canonical lateness. Preserving artifacts is not a new certification that these market owners are current. The final post-maintenance sample is reported separately. Existing source/admission and PAPER guards remain active.
