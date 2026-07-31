from __future__ import annotations

import math
from dataclasses import dataclass

from risk_mppi import BeliefState, Control, DynamicObstacle, clamp


@dataclass(slots=True)
class ModelHypothesis:
    name: str
    traction_scale: float
    steering_scale: float
    latency_s: float
    probability: float


@dataclass(slots=True)
class EnsemblePrediction:
    trajectories: dict[str, list[tuple[float, float]]]
    disagreement_m: float
    epistemic_risk: float
    worst_case_clearance_m: float
    recommended_speed_scale: float


class CounterfactualWorldEnsemble:
    """Small explicit ensemble for model uncertainty.

    The ensemble represents dry pavement, wet pavement, asymmetric traction,
    actuator lag, and partial wheel slip. It is deterministic, inspectable, and
    suitable for simulation before any learned world model is introduced.
    """

    def __init__(self) -> None:
        self.hypotheses = [
            ModelHypothesis("nominal", 1.0, 1.0, 0.08, 0.42),
            ModelHypothesis("wet_surface", 0.72, 0.82, 0.14, 0.18),
            ModelHypothesis("left_slip", 0.80, 1.20, 0.12, 0.14),
            ModelHypothesis("right_slip", 0.80, 0.72, 0.12, 0.14),
            ModelHypothesis("actuator_lag", 0.90, 0.90, 0.28, 0.12),
        ]

    def predict(self, state: BeliefState, controls: list[Control], obstacles: list[DynamicObstacle], dt_s: float = 0.1) -> EnsemblePrediction:
        trajectories: dict[str, list[tuple[float, float]]] = {}
        clearances: list[float] = []
        terminal_points: list[tuple[float, float, float]] = []

        for model in self.hypotheses:
            x, y, yaw, speed = state.x_m, state.y_m, state.yaw_rad, state.speed_mps
            path = [(x, y)]
            minimum = float("inf")
            delayed_steps = max(0, round(model.latency_s / dt_s))
            for index, control in enumerate(controls):
                active = controls[max(0, index - delayed_steps)]
                speed = clamp(speed + active.acceleration_mps2 * model.traction_scale * dt_s, 0.0, 1.5)
                yaw += active.yaw_rate_rps * model.steering_scale * dt_s
                x += math.cos(yaw) * speed * dt_s
                y += math.sin(yaw) * speed * dt_s
                path.append((x, y))
                t = (index + 1) * dt_s
                for obstacle in obstacles:
                    ox = obstacle.x_m + obstacle.vx_mps * t
                    oy = obstacle.y_m + obstacle.vy_mps * t
                    minimum = min(minimum, math.hypot(x - ox, y - oy) - obstacle.radius_m - 0.9)
            trajectories[model.name] = path
            clearances.append(minimum)
            terminal_points.append((x, y, model.probability))

        mean_x = sum(x * p for x, _, p in terminal_points)
        mean_y = sum(y * p for _, y, p in terminal_points)
        disagreement = math.sqrt(sum(p * ((x - mean_x) ** 2 + (y - mean_y) ** 2) for x, y, p in terminal_points))
        worst = min(clearances) if clearances else float("inf")
        epistemic_risk = clamp(disagreement / 2.0 + max(0.0, 0.6 - worst), 0.0, 1.0)
        speed_scale = clamp(1.0 - epistemic_risk, 0.15, 1.0)
        return EnsemblePrediction(trajectories, disagreement, epistemic_risk, worst, speed_scale)
