"""Opt-in support wiring for the accepted 28-step Docker Cognition baseline.

No context/decision publisher, controller, finance or trading imports. The three
original cognitive reducers execute once in the approved complete-set worker;
their original pipeline positions acknowledge that same authenticated result.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

SUPPORT = (
    "market_context_engine_v1.py",
    "behavioral_scoring_engine_v1.py",
    "event_relationship_engine_v1.py",
    "adaptive_behavioral_weights_v1.py",
)
REDUCERS = {
    "contextual_memory_loader_v2.py": "contextual_memory_state.parquet",
    "perception_context_integration_v1.py": "perception_context_integration.parquet",
    "temporal_context_memory_v1.py": "temporal_context_memory.parquet",
}
CONSUMERS = frozenset({"behavioral_sequence_memory_v1.py", "behavioral_volume_observer_v1.py"})


class CognitionExtension:
    def __init__(self, *, root, python, dependencies, execute, should_run,
                 mark_success, decisions, emit):
        self.root = Path(root)
        self.python = python
        self.dependencies = dependencies
        self.execute = execute
        self.should_run = should_run
        self.mark_success = mark_success
        self.decisions = decisions
        self.emit = emit
        self.support_results = []
        self.result = None
        self.commit_id = None
        self.consumer_results = {}
        self.generation = os.environ.get("BTC_ML_COGNITION_GENERATION", "")
        # R03 enables only the accepted three-memory coordinator; R04 owns Behavioral.
        self.memory_only = os.environ.get("BTC_ML_COGNITION_MEMORY_ONLY", "0") == "1"

    @staticmethod
    def blocked(detail):
        return {"status": "SKIPPED", "reason": "REQUIRED_INPUT_UNAVAILABLE", "detail": str(detail)}

    def _support(self):
        for name in SUPPORT:
            try:
                dependencies = list(self.dependencies[name])
                if name == "adaptive_behavioral_weights_v1.py":
                    from storage.path_registry import resolve_read
                    replay = Path(resolve_read("behavioral_replay_memory.parquet"))
                    # Absence uses the original approved default-weights branch.
                    # An existing replay must be readable before calibration.
                    if replay.exists():
                        dependencies.append(str(replay))
                run = self.should_run(name, dependencies)
                if not run:
                    result = {"status": "SKIPPED", **self.decisions.get(name, {})}
                else:
                    self.execute(name, self.root / "deploy/vps/cognition_extension/upstream" / name)
                    self.mark_success(name)
                    result = {"status": "SUCCESS"}
            except Exception as error:
                result = {"status": "FAILED", "reason": type(error).__name__, "detail": str(error)}
            self.support_results.append({"engine": name, **result})
            self.emit(name, result["status"], 0.0, reason=result.get("reason", ""))

    def _verify_set(self):
        from btc_ml.runtime import cognitive_cycle as C
        from storage.path_registry import data_root
        folder = C.home(data_root())
        if (folder / "pending.json").exists():
            raise C.CognitiveStateUnavailable("UNFINISHED_COGNITIVE_PUBLICATION")
        pointer = C.load(folder / "head.json")
        _, manifest = C.verified_commit(folder, pointer)
        if pointer["id"] != self.commit_id or manifest["generation"] != self.generation:
            raise C.CognitiveStateUnavailable("COGNITIVE_CYCLE_SET_CHANGED")
        return C.committed_paths(data_root())

    def _cycle(self):
        if not self.generation or os.environ.get("BTC_ML_COGNITIVE_CHAIN_LIVE") != "1":
            self.result = self.blocked("EXPLICIT_COGNITIVE_GENERATION_AND_BASE_OVERLAY_REQUIRED")
            return
        if not self.memory_only:
            self._support()
        from storage.path_registry import data_root
        status = data_root() / "runtime/cognitive_cycle_status.json"
        started_ns = time.time_ns()
        failure = None
        try:
            self.execute("cognitive_cycle_once", self.root / "deploy/vps/cognition_extension/scripts/live/run_cognitive_cycle_once.py")
        except Exception as error:
            failure = error
        try:
            if status.stat().st_mtime_ns < started_ns:
                raise RuntimeError("STALE_COGNITIVE_CYCLE_STATUS")
            result = json.loads(status.read_text())
            if result.get("status") not in {"SUCCESS", "SKIPPED", "FAILED"}:
                raise RuntimeError("INVALID_COGNITIVE_CYCLE_STATUS")
            if result["status"] == "SUCCESS":
                if failure is not None:
                    raise RuntimeError("FAILED_CHILD_CANNOT_ACK_SUCCESS") from failure
                self.commit_id = result["id"]
                self._verify_set()
            self.result = result
        except Exception as error:
            self.result = {"status": "FAILED", "reason": type(error).__name__, "detail": str(error)}
        self.support_results.append({"engine": "cognitive_cycle_once", **self.result})
        self.emit("cognitive_cycle_once", self.result["status"], 0.0,
                  reason=self.result.get("reason", self.result.get("mode", "")))

    def run_stage(self, engine):
        """None delegates unchanged baseline steps to their original executor."""
        if self.memory_only and engine in CONSUMERS:
            # Keep baseline mandatory-input guards; do not enable the R04 branch.
            return None
        if engine not in REDUCERS and engine not in CONSUMERS:
            return None
        if self.result is None:
            try:
                self._cycle()
            except Exception as error:
                # Support/config failures must not interrupt unrelated baseline stages.
                self.result = {"status": "FAILED", "reason": type(error).__name__, "detail": str(error)}
        if self.result["status"] != "SUCCESS":
            return self.blocked(self.result.get("detail", self.result.get("reason", "COGNITIVE_SET_NOT_COMMITTED")))
        try:
            pinned = self._verify_set()
            if engine in REDUCERS:
                # These named stages were calculated by the worker, never fabricated.
                return {"status": "SUCCESS", "reason": "COMPLETE_SET_COMMITTED",
                        "commit_id": self.commit_id, "member": REDUCERS[engine],
                        "mode": self.result.get("mode")}
            # A failed current producer must not authorize an old output.
            ready = lambda result: (result.get("status") == "SUCCESS" or
                                    (result.get("status") == "SKIPPED" and
                                     result.get("reason") == "INPUT_UNCHANGED"))
            support = [row for row in self.support_results if row["engine"] in SUPPORT]
            if len(support) != len(SUPPORT) or not all(ready(row) for row in support):
                return self.blocked("BEHAVIORAL_SUPPORT_NOT_READY")
            if engine == "behavioral_volume_observer_v1.py" and not ready(
                    self.consumer_results.get("behavioral_sequence_memory_v1.py", {})):
                return self.blocked("CURRENT_BEHAVIORAL_SEQUENCE_NOT_READY")
            dependencies = [pinned.get(name, name) for name in self.dependencies[engine]]
            if not self.should_run(engine, dependencies):
                result = {"status": "SKIPPED", **self.decisions.get(engine, {})}
            else:
                self.execute(engine, self.root / "deploy/vps/cognition_extension/consumers" / engine)
                self.mark_success(engine)
                result = {"status": "SUCCESS", "commit_id": self.commit_id}
            self.consumer_results[engine] = result
            return result
        except (OSError, PermissionError) as error:
            return self.blocked(error)
        except Exception as error:
            from btc_ml.runtime.cognitive_cycle import CognitiveStateUnavailable
            if isinstance(error, CognitiveStateUnavailable):
                return self.blocked(error)
            # Failures stay FAILED, without preventing the remaining baseline steps.
            return {"status": "FAILED", "reason": type(error).__name__, "detail": str(error)}
