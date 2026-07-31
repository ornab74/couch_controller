from __future__ import annotations

import math
from dataclasses import dataclass, field

from risk_mppi import BeliefState, Control, DynamicObstacle, clamp


@dataclass(slots=True)
class AssuranceConfig:
    dt_s: float = 0.08
    horizon_steps: int = 18
    couch_radius_m: float = 0.9
    actuator_delay_s: float = 0.16
    max_deceleration_mps2: float = 1.4
    max_yaw_rate_rps: float = 0.9
    uncertainty_growth_mps: float = 0.12
    minimum_clearance_m: float = 0.25


@dataclass(slots=True)
class AssuranceDecision:
    accepted: bool
    selected: Control
    fallback: Control
    reason: str
    reachable_min_clearance_m: float
    safety_margin_m: float
    intervention_level: str
    certificates: dict[str, float | bool | str] = field(default_factory=dict)


class ReachabilityRuntimeAssurance:
    """Independent safety supervisor for simulation.

    The planner is treated as untrusted. This module propagates an uncertainty
    tube around the requested command and substitutes deterministic braking when
    that tube violates the robust stopping envelope.
    """

    def __init__(self, config: AssuranceConfig | None = None) -> None:
        self.config = config or AssuranceConfig()

    def certify(self, state: BeliefState, requested: Control, obstacles: list[DynamicObstacle]) -> AssuranceDecision:
        fallback = self._fallback(state)
        requested_clearance = self._tube_clearance(state, requested, obstacles)
        fallback_clearance = self._tube_clearance(state, fallback, obstacles)
        stopping_distance = state.speed_mps * self.config.actuator_delay_s + state.speed_mps**2 / (2.0 * max(self.config.max_deceleration_mps2, 0.1))
        uncertainty = 2.5 * state.position_sigma_m + self.config.uncertainty_growth_mps * (self.config.horizon_steps * self.config.dt_s)
        required = self.config.minimum_clearance_m + stopping_distance + uncertainty
        margin = requested_clearance - required

        if requested_clearance <= 0:
            return self._decision(False, fallback, fallback, "reachable tube intersects obstacle occupancy", requested_clearance, margin, "emergency", state, fallback_clearance, required)
        if margin < 0:
            return self._decision(False, fallback, fallback, "insufficient robust stopping margin", requested_clearance, margin, "protective_brake", state, fallback_clearance, required)
        if state.position_sigma_m > 1.0 or state.slip_probability > 0.45:
            return self._decision(False, fallback, fallback, "belief uncertainty exceeds autonomous envelope", requested_clearance, margin, "degraded", state, fallback_clearance, required)
        return self._decision(True, requested, fallback, "reachability certificate passed", requested_clearance, margin, "none", state, fallback_clearance, required)

    def _decision(self, accepted: bool, selected: Control, fallback: Control, reason: str, clearance: float, margin: float, level: str, state: BeliefState, fallback_clearance: float, required: float) -> AssuranceDecision:
        return AssuranceDecision(
            accepted,
            selected,
            fallback,
            reason,
            clearance,
            margin,
            level,
            {
                "requested_tube_clearance_m": clearance,
                "fallback_tube_clearance_m": fallback_clearance,
                "required_margin_m": required,
                "position_sigma_m": state.position_sigma_m,
                "slip_probability": state.slip_probability,
                "horizon_s": self.config.horizon_steps * self.config.dt_s,
                "method": "forward_reachable_uncertainty_tube",
            },
        )

    def _fallback(self, state: BeliefState) -> Control:
        brake = -self.config.max_deceleration_mps2 if state.speed_mps > 0.03 else 0.0
        counter_yaw = clamp(-1.4 * state.yaw_rate_rps, -self.config.max_yaw_rate_rps, self.config.max_yaw_rate_rps)
        return Control(brake, counter_yaw)

    def _tube_clearance(self, state: BeliefState, control: Control, obstacles: list[DynamicObstacle]) -> float:
        if not obstacles:
            return float("inf")
        x, y, yaw, speed = state.x_m, state.y_m, state.yaw_rad, state.speed_mps
        minimum = float("inf")
        for step in range(self.config.horizon_steps):
            t = (step + 1) * self.config.dt_s
            speed = max(0.0, speed + control.acceleration_mps2 * self.config.dt_s)
            yaw += clamp(control.yaw_rate_rps, -self.config.max_yaw_rate_rps, self.config.max_yaw_rate_rps) * self.config.dt_s
            x += math.cos(yaw) * speed * self.config.dt_s
            y += math.sin(yaw) * speed * self.config.dt_s
            tube_radius = self.config.couch_radius_m + 2.5 * state.position_sigma_m + self.config.uncertainty_growth_mps * t + speed * self.config.actuator_delay_s
            for obstacle in obstacles:
                ox = obstacle.x_m + obstacle.vx_mps * t
                oy = obstacle.y_m + obstacle.vy_mps * t
                minimum = min(minimum, math.hypot(x - ox, y - oy) - tube_radius - obstacle.radius_m)
        return minimum
