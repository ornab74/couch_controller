from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time


class Verdict(str, Enum):
    satisfied = "satisfied"
    pending = "pending"
    violated = "violated"


@dataclass(slots=True)
class TemporalSnapshot:
    timestamp_ms: int
    armed: bool
    estop: bool
    supervisor_present: bool
    localization_ok: bool
    collision_free: bool
    inside_geofence: bool
    speed_mps: float
    commanded_speed_mps: float
    mission_active: bool
    goal_reached: bool


@dataclass(slots=True)
class RuleResult:
    rule_id: str
    verdict: Verdict
    message: str
    severity: str
    evidence: dict[str, object] = field(default_factory=dict)


class TemporalMissionAssurance:
    """Small runtime monitor for safety and liveness contracts.

    The monitor is deliberately independent from the planner. It evaluates
    temporal obligations over a rolling history and can veto motion when a
    safety invariant is violated or an expected recovery does not happen.
    """

    def __init__(self, max_history: int = 500) -> None:
        self.max_history = max_history
        self.history: list[TemporalSnapshot] = []
        self.last_results: list[RuleResult] = []

    def observe(self, snapshot: TemporalSnapshot) -> list[RuleResult]:
        self.history.append(snapshot)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]
        self.last_results = self._evaluate(snapshot)
        return self.last_results

    def should_veto_motion(self) -> bool:
        return any(r.verdict == Verdict.violated and r.severity in {"critical", "high"} for r in self.last_results)

    def _evaluate(self, s: TemporalSnapshot) -> list[RuleResult]:
        results: list[RuleResult] = []

        results.append(self._invariant(
            "S1_ESTOP_IMPLIES_ZERO_SPEED",
            not s.estop or (abs(s.commanded_speed_mps) < 1e-3 and abs(s.speed_mps) < 0.08),
            "Emergency stop must imply zero commanded motion and near-zero measured speed.",
            "critical",
            {"estop": s.estop, "commanded_speed_mps": s.commanded_speed_mps, "speed_mps": s.speed_mps},
        ))
        results.append(self._invariant(
            "S2_NO_MOTION_WITHOUT_SUPERVISOR",
            s.supervisor_present or abs(s.commanded_speed_mps) < 1e-3,
            "Loss of supervisor must force zero commanded speed.",
            "critical",
            {"supervisor_present": s.supervisor_present, "commanded_speed_mps": s.commanded_speed_mps},
        ))
        results.append(self._invariant(
            "S3_GEOFENCE_CONTAINMENT",
            s.inside_geofence or abs(s.commanded_speed_mps) < 1e-3,
            "Outside-geofence state must not permit continued motion.",
            "critical",
            {"inside_geofence": s.inside_geofence, "commanded_speed_mps": s.commanded_speed_mps},
        ))
        results.append(self._invariant(
            "S4_LOCALIZATION_GATE",
            s.localization_ok or abs(s.commanded_speed_mps) < 1e-3,
            "Localization degradation must force hold or stop.",
            "high",
            {"localization_ok": s.localization_ok, "commanded_speed_mps": s.commanded_speed_mps},
        ))
        results.append(self._invariant(
            "S5_COLLISION_FREE_COMMAND",
            s.collision_free or abs(s.commanded_speed_mps) < 1e-3,
            "Known collision conflict must force zero commanded speed.",
            "critical",
            {"collision_free": s.collision_free, "commanded_speed_mps": s.commanded_speed_mps},
        ))

        results.append(self._bounded_response(
            "L1_ESTOP_STOPS_WITHIN_750MS",
            trigger=lambda x: x.estop,
            response=lambda x: abs(x.speed_mps) < 0.08,
            bound_ms=750,
            message="After E-stop activation, measured speed must fall below 0.08 m/s within 750 ms.",
            severity="critical",
        ))
        results.append(self._bounded_response(
            "L2_LOST_SUPERVISOR_HOLDS_WITHIN_500MS",
            trigger=lambda x: not x.supervisor_present,
            response=lambda x: abs(x.commanded_speed_mps) < 1e-3,
            bound_ms=500,
            message="Supervisor loss must produce a hold command within 500 ms.",
            severity="critical",
        ))

        if s.mission_active and not s.goal_reached:
            results.append(RuleResult(
                "L3_MISSION_PROGRESS",
                Verdict.pending,
                "Mission remains active and goal has not yet been reached.",
                "info",
                {"mission_active": True, "goal_reached": False},
            ))
        else:
            results.append(RuleResult(
                "L3_MISSION_PROGRESS",
                Verdict.satisfied,
                "Mission is inactive or the goal is reached.",
                "info",
                {"mission_active": s.mission_active, "goal_reached": s.goal_reached},
            ))
        return results

    def _invariant(self, rule_id: str, condition: bool, message: str, severity: str, evidence: dict[str, object]) -> RuleResult:
        return RuleResult(rule_id, Verdict.satisfied if condition else Verdict.violated, message, severity, evidence)

    def _bounded_response(self, rule_id: str, trigger, response, bound_ms: int, message: str, severity: str) -> RuleResult:
        if not self.history:
            return RuleResult(rule_id, Verdict.pending, message, severity)
        now = self.history[-1].timestamp_ms
        candidates = [x for x in self.history if trigger(x)]
        if not candidates:
            return RuleResult(rule_id, Verdict.satisfied, message, severity, {"trigger_seen": False})
        first = candidates[0]
        window = [x for x in self.history if first.timestamp_ms <= x.timestamp_ms <= first.timestamp_ms + bound_ms]
        if any(response(x) for x in window):
            return RuleResult(rule_id, Verdict.satisfied, message, severity, {"latency_ms": min(x.timestamp_ms - first.timestamp_ms for x in window if response(x))})
        if now - first.timestamp_ms <= bound_ms:
            return RuleResult(rule_id, Verdict.pending, message, severity, {"elapsed_ms": now - first.timestamp_ms, "bound_ms": bound_ms})
        return RuleResult(rule_id, Verdict.violated, message, severity, {"elapsed_ms": now - first.timestamp_ms, "bound_ms": bound_ms})


def now_ms() -> int:
    return int(time.time() * 1000)
