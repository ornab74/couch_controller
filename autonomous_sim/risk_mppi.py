from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Iterable


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


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
    """Risk-sensitive sampling MPC with CVaR and a braking barrier shield.

    Unlike graph search, this planner samples dynamically feasible control
    sequences in continuous time, predicts moving obstacles, reasons over pose
    uncertainty and wheel slip, and optimizes the worst-cost probability tail.
    """

    def __init__(self, config: PlannerConfig | None = None) -> None:
        self.config = config or PlannerConfig()
        self.rng = random.Random(self.config.seed)
        self.mean = [Control() for _ in range(self.config.horizon_steps)]

    def reset(self) -> None:
        self.mean = [Control() for _ in range(self.config.horizon_steps)]

    def plan(self, state: BeliefState, reference: list[tuple[float, float]], obstacles: Iterable[DynamicObstacle]) -> PlannerResult:
        if not reference:
            return PlannerResult(Control(), [(state.x_m, state.y_m)], 0, 0, 0, 0, 0, diagnostics={"state": "no_reference"})
        obs = list(obstacles)
        best_path: list[tuple[float, float]] = [(state.x_m, state.y_m)]
        best = (float("inf"), float("inf"), 1.0, -1.0)
        for iteration in range(self.config.iterations):
            candidates = []
            a_sigma = 0.48 * 0.72**iteration
            w_sigma = 0.42 * 0.72**iteration
            for _ in range(self.config.samples):
                controls = [Control(
                    clamp(u.acceleration_mps2 + self.rng.gauss(0, a_sigma), -self.config.max_deceleration_mps2, self.config.max_acceleration_mps2),
                    clamp(u.yaw_rate_rps + self.rng.gauss(0, w_sigma), -self.config.max_yaw_rate_rps, self.config.max_yaw_rate_rps),
                ) for u in self.mean]
                path, metrics = self._scenarios(state, controls, reference, obs)
                candidates.append((metrics[1], controls, path, metrics))
            candidates.sort(key=lambda item: item[0])
            elite = candidates[:max(12, self.config.samples // 12)]
            base = elite[0][0]
            weights = [math.exp(-(x[0] - base) / max(self.config.temperature, 1e-6)) for x in elite]
            total = max(sum(weights), 1e-9)
            self.mean = [Control(
                sum(w * x[1][i].acceleration_mps2 for w, x in zip(weights, elite)) / total,
                sum(w * x[1][i].yaw_rate_rps for w, x in zip(weights, elite)) / total,
            ) for i in range(self.config.horizon_steps)]
            best_path, best = elite[0][2], elite[0][3]
        safe = self._barrier(state, self.mean[0], obs)
        self.mean = self.mean[1:] + [Control()]
        nominal, cvar, collision_p, clearance = best
        confidence = clamp((1 - collision_p) * math.exp(-0.7 * state.position_sigma_m), 0, 1)
        return PlannerResult(safe, best_path, nominal, cvar, collision_p, clearance, confidence, diagnostics={
            "samples": self.config.samples,
            "iterations": self.config.iterations,
            "horizon_s": self.config.horizon_steps * self.config.dt_s,
            "cvar_alpha": self.config.cvar_alpha,
            "scenario_count": self.config.scenario_count,
        })

    def _scenarios(self, state: BeliefState, controls: list[Control], reference: list[tuple[float, float]], obstacles: list[DynamicObstacle]):
        costs, collisions = [], 0
        nominal_path: list[tuple[float, float]] = []
        clearance = float("inf")
        for n in range(self.config.scenario_count):
            s = BeliefState(**asdict(state))
            s.x_m += self.rng.gauss(0, state.position_sigma_m)
            s.y_m += self.rng.gauss(0, state.position_sigma_m)
            s.yaw_rad += self.rng.gauss(0, state.yaw_sigma_rad)
            path, cost, hit, gap = self._rollout(s, controls, reference, obstacles, n)
            if n == 0:
                nominal_path = path
            costs.append(cost)
            collisions += int(hit)
            clearance = min(clearance, gap)
        ordered = sorted(costs, reverse=True)
        tail_n = max(1, math.ceil(len(ordered) * self.config.cvar_alpha))
        return nominal_path, (costs[0], sum(ordered[:tail_n]) / tail_n, collisions / len(costs), clearance)

    def _rollout(self, state: BeliefState, controls: list[Control], reference: list[tuple[float, float]], obstacles: list[DynamicObstacle], scenario: int):
        c = self.config
        x, y, yaw, speed = state.x_m, state.y_m, state.yaw_rad, state.speed_mps
        path, cost, hit, gap = [(x, y)], 0.0, False, float("inf")
        previous_accel = 0.0
        disturbance = 1 + scenario * 0.12 + state.slip_probability
        for i, u in enumerate(controls):
            accel = u.acceleration_mps2 / disturbance
            yaw_rate = u.yaw_rate_rps * (1 + self.rng.gauss(0, 0.025 * disturbance))
            speed = clamp(speed + accel * c.dt_s, 0, c.max_speed_mps)
            yaw = wrap(yaw + yaw_rate * c.dt_s)
            x += math.cos(yaw) * speed * c.dt_s
            y += math.sin(yaw) * speed * c.dt_s
            path.append((x, y))
            tx, ty = reference[min(i, len(reference) - 1)]
            error = math.hypot(x - tx, y - ty)
            jerk = (accel - previous_accel) / c.dt_s
            previous_accel = accel
            cost += c.tracking_weight * error**2 + c.comfort_accel_weight * accel**2 + c.comfort_turn_weight * yaw_rate**2 + c.jerk_weight * jerk**2 * 0.02
            t = (i + 1) * c.dt_s
            for o in obstacles:
                ox, oy = o.x_m + o.vx_mps * t, o.y_m + o.vy_mps * t
                free = math.hypot(x - ox, y - oy) - o.radius_m - c.couch_radius_m
                gap = min(gap, free)
                margin = state.position_sigma_m * (1 + i / c.horizon_steps)
                if free <= margin:
                    hit = True
                    cost += c.collision_weight * o.confidence
                else:
                    cost += o.confidence * 18 / max(free - margin, 0.08)
        gx, gy = reference[-1]
        cost += c.terminal_weight * math.hypot(x - gx, y - gy)**2
        cost += c.uncertainty_weight * (state.position_sigma_m + state.yaw_sigma_rad + state.slip_probability)
        return path, cost, hit, gap

    def _barrier(self, state: BeliefState, control: Control, obstacles: list[DynamicObstacle]) -> Control:
        if not obstacles:
            return control
        stop_d = state.speed_mps**2 / (2 * max(self.config.max_deceleration_mps2, 0.1))
        required = self.config.couch_radius_m + stop_d + 0.45 + 2 * state.position_sigma_m
        nearest = min(math.hypot(state.x_m - o.x_m, state.y_m - o.y_m) - o.radius_m for o in obstacles)
        if nearest <= self.config.couch_radius_m + 0.1:
            return Control(-self.config.max_deceleration_mps2, 0)
        if nearest < required:
            scale = clamp((nearest - self.config.couch_radius_m) / max(required - self.config.couch_radius_m, 0.01), 0, 1)
            return Control(min(control.acceleration_mps2, -self.config.max_deceleration_mps2 * (1 - scale)), control.yaw_rate_rps * scale)
        return control
