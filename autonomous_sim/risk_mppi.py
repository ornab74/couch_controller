from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def wrap_angle(value: float) -> float:
    while value > math.pi:
        value -= 2.0 * math.pi
    while value < -math.pi:
        value += 2.0 * math.pi
    return value


@dataclass(slots=True)
class BeliefState:
    x_m: float = 0.0
    y_m: float = 0.0
    yaw_rad: float = 0.0
    speed_mps: float = 0.0
    yaw_rate_rps: float = 0.0
    position_sigma_m: float = 0.15
    yaw_sigma_rad: float = 0.04
    slip_probability: float = 0.02


@dataclass(slots=True)
class DynamicObstacle:
    x_m: float
    y_m: float
    vx_mps: float = 0.0
    vy_mps: float = 0.0
    radius_m: float = 0.45
    confidence: float = 1.0


@dataclass(slots=True)
class Control:
    acceleration_mps2: float = 0.0
    yaw_rate_rps: float = 0.0


@dataclass(slots=True)
class PlannerConfig:
    horizon_steps: int = 28
    dt_s: float = 0.12
    samples: int = 420
    iterations: int = 4
    temperature: float = 0.7
    max_speed_mps: float = 1.15
    max_acceleration_mps2: float = 0.8
    max_deceleration_mps2: float = 1.4
    max_yaw_rate_rps: float = 0.9
    couch_radius_m: float = 0.9
    comfort_accel_weight: float = 2.6
    comfort_turn_weight: float = 1.8
    jerk_weight: float = 2.1
    tracking_weight: float = 7.0
    terminal_weight: float = 18.0
    collision_weight: float = 5000.0
    uncertainty_weight: float = 30.0
    cvar_alpha: float = 0.18
    scenario_count: int = 7
    seed: int = 74


@dataclass(slots=True)
class PlannerResult:
    control: Control
    predicted_path: list[tuple[float, float]]
    nominal_cost: float
    cvar_cost: float
    collision_probability: float
    min_clearance_m: float
    confidence: float
    planner: str = "risk_sensitive_mppi_cbf"
    diagnostics: dict[str, float | int | str] = field(default_factory=dict)


class RiskSensitiveMPPI:
    """Sampling MPC with uncertainty scenarios and a control-barrier safety shield.

    This is deliberately not grid A*. It searches directly in dynamically feasible
    control space, evaluates moving obstacles over time, penalizes rider discomfort,
    and optimizes tail risk using CVaR. A final barrier projection can only reduce
    motion; it cannot make an unsafe candidate more aggressive.
    """

    def __init__(self, config: PlannerConfig | None = None) -> None:
        self.config = config or PlannerConfig()
        self._rng = random.Random(self.config.seed)
        self._mean = [Control() for _ in range(self.config.horizon_steps)]

    def reset(self) -> None:
        self._mean = [Control() for _ in range(self.config.horizon_steps)]

    def plan(
        self,
        state: BeliefState,
        reference: list[tuple[float, float]],
        obstacles: Iterable[DynamicObstacle],
    ) -> PlannerResult:
        if not reference:
            return PlannerResult(Control(), [(state.x_m, state.y_m)], 0, 0, 0, 0, 0, diagnostics={"state": "no_reference"})

        obstacle_list = list(obstacles)
        best_path: list[tuple[float, float]] = []
        best_metrics = (float("inf"), float("inf"), 1.0, -1.0)

        for iteration in range(self.config.iterations):
            candidates: list[tuple[float, list[Control], list[tuple[float, float]], tuple[float, float, float, float]]] = []
            accel_sigma = 0.48 * (0.72 ** iteration)
            turn_sigma = 0.42 * (0.72 ** iteration)

            for _ in range(self.config.samples):
                sequence = [
                    Control(
                        clamp(u.acceleration_mps2 + self._rng.gauss(0, accel_sigma), -self.config.max_deceleration_mps2, self.config.max_acceleration_mps2),
                        clamp(u.yaw_rate_rps + self._rng.gauss(0, turn_sigma), -self.config.max_yaw_rate_rps, self.config.max_yaw_rate_rps),
                    )
                    for u in self._mean
                ]
                path, metrics = self._evaluate_scenarios(state, sequence, reference, obstacle_list)
                candidates.append((metrics[1], sequence, path, metrics))

            candidates.sort(key=lambda item: item[0])
            elite = candidates[: max(12, self.config.samples // 12)]
            floor = elite[0][0]
            weights = [math.exp(-(item[0] - floor) / max(self.config.temperature, 1e-6)) for item in elite]
            total = max(sum(weights), 1e-9)

            next_mean: list[Control] = []
            for step in range(self.config.horizon_steps):
                acceleration = sum(w * item[1][step].acceleration_mps2 for w, item in zip(weights, elite)) / total
                yaw_rate = sum(w * item[1][step].yaw_rate_rps for w, item in zip(weights, elite)) / total
                next_mean.append(Control(acceleration, yaw_rate))
            self._mean = next_mean
            best_path = elite[0][2]
            best_metrics = elite[0][3]

        raw = self._mean[0]
        safe = self._barrier_project(state, raw, obstacle_list)
        self._mean = self._mean[1:] + [Control()]
        nominal, cvar, collision_probability, min_clearance = best_metrics
        confidence = clamp((1.0 - collision_probability) * math.exp(-state.position_sigma_m * 0.7), 0.0, 1.0)
        return PlannerResult(
            control=safe,
            predicted_path=best_path,
            nominal_cost=nominal,
            cvar_cost=cvar,
            collision_probability=collision_probability,
            min_clearance_m=min_clearance,
            confidence=confidence,
            diagnostics={
                "samples": self.config.samples,
                "iterations": self.config.iterations,
                "horizon_s": self.config.horizon_steps * self.config.dt_s,
                "cvar_alpha": self.config.cvar_alpha,
                "scenario_count": self.config.scenario_count,
            },
        )

    def _evaluate_scenarios(self, state: BeliefState, controls: list[Control], reference: list[tuple[float, float]], obstacles: list[DynamicObstacle]) -> tuple[list[tuple[float, float]], tuple[float, float, float, float]]:
        costs: list[float] = []
        collisions = 0
        nominal_path: list[tuple[float, float]] = []
        minimum_clearance = float("inf")

        for scenario in range(self.config.scenario_count):
            disturbed = BeliefState(**state.__dict__)
            disturbed.x_m += self._rng.gauss(0, state.position_sigma_m)
            disturbed.y_m += self._rng.gauss(0, state.position_sigma_m)
            disturbed.yaw_rad += self._rng.gauss(0, state.yaw_sigma_rad)
            path, cost, collided, clearance = self._rollout(disturbed, controls, reference, obstacles, scenario)
            if scenario == 0:
                nominal_path = path
            costs.append(cost)
            collisions += int(collided)
            minimum_clearance = min(minimum_clearance, clearance)

        ordered = sorted(costs, reverse=True)
        tail_count = max(1, math.ceil(len(ordered) * self.config.cvar_alpha))
        cvar = sum(ordered[:tail_count]) / tail_count
        nominal = costs[0]
        collision_probability = collisions / len(costs)
        return nominal_path, (nominal, cvar, collision_probability, minimum_clearance)

    def _rollout(self, state: BeliefState, controls: list[Control], reference: list[tuple[float, float]], obstacles: list[DynamicObstacle], scenario: int) -> tuple[list[tuple[float, float]], float, bool, float]:
        cfg = self.config
        x, y, yaw, speed = state.x_m, state.y_m, state.yaw_rad, state.speed_mps
        path: list[tuple[float, float]] = [(x, y)]
        cost = 0.0
        collided = False
        min_clearance = float("inf")
        last_accel = 0.0
        uncertainty_scale = 1.0 + scenario * 0.12 + state.slip_probability

        for index, control in enumerate(controls):
            accel = control.acceleration_mps2 / uncertainty_scale
            yaw_rate = control.yaw_rate_rps * (1.0 + self._rng.gauss(0, 0.025 * uncertainty_scale))
            speed = clamp(speed + accel * cfg.dt_s, 0.0, cfg.max_speed_mps)
            yaw = wrap_angle(yaw + yaw_rate * cfg.dt_s)
            x += math.cos(yaw) * speed * cfg.dt_s
            y += math.sin(yaw) * speed * cfg.dt_s
            path.append((x, y))

            target = reference[min(index, len(reference) - 1)]
            tracking_error = math.hypot(x - target[0], y - target[1])
            jerk = (accel - last_accel) / cfg.dt_s
            last_accel = accel
            cost += cfg.tracking_weight * tracking_error * tracking_error
            cost += cfg.comfort_accel_weight * accel * accel
            cost += cfg.comfort_turn_weight * yaw_rate * yaw_rate
            cost += cfg.jerk_weight * jerk * jerk * 0.02

            t = (index + 1) * cfg.dt_s
            for obstacle in obstacles:
                ox = obstacle.x_m + obstacle.vx_mps * t
                oy = obstacle.y_m + obstacle.vy_mps * t
                clearance = math.hypot(x - ox, y - oy) - obstacle.radius_m - cfg.couch_radius_m
                min_clearance = min(min_clearance, clearance)
                uncertainty_margin = state.position_sigma_m * (1.0 + index / cfg.horizon_steps)
                if clearance <= uncertainty_margin:
                    collided = True
                    cost += cfg.collision_weight * obstacle.confidence
                else:
                    cost += obstacle.confidence * 18.0 / max(clearance - uncertainty_margin, 0.08)

        terminal = reference[-1]
        cost += cfg.terminal_weight * math.hypot(x - terminal[0], y - terminal[1]) ** 2
        cost += cfg.uncertainty_weight * (state.position_sigma_m + state.yaw_sigma_rad + state.slip_probability)
        return path, cost, collided, min_clearance

    def _barrier_project(self, state: BeliefState, control: Control, obstacles: list[DynamicObstacle]) -> Control:
        """One-step safety projection inspired by control barrier functions."""
        if not obstacles:
            return control
        stopping_distance = state.speed_mps ** 2 / (2.0 * max(self.config.max_deceleration_mps2, 0.1))
        required = self.config.couch_radius_m + stopping_distance + 0.45 + 2.0 * state.position_sigma_m
        nearest = min(math.hypot(state.x_m - o.x_m, state.y_m - o.y_m) - o.radius_m for o in obstacles)
        if nearest <= self.config.couch_radius_m + 0.1:
            return Control(-self.config.max_deceleration_mps2, 0.0)
        if nearest < required:
            scale = clamp((nearest - self.config.couch_radius_m) / max(required - self.config.couch_radius_m, 0.01), 0.0, 1.0)
            return Control(min(control.acceleration_mps2, -self.config.max_deceleration_mps2 * (1.0 - scale)), control.yaw_rate_rps * scale)
        return control
