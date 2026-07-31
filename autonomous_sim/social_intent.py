from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(slots=True)
class AgentObservation:
    agent_id: str
    x_m: float
    y_m: float
    vx_mps: float
    vy_mps: float
    radius_m: float = 0.4
    heading_rad: float | None = None
    attention_to_couch: float = 0.5


@dataclass(slots=True)
class IntentMode:
    name: str
    probability: float
    trajectory: list[tuple[float, float]]


@dataclass(slots=True)
class IntentPrediction:
    agent_id: str
    modes: list[IntentMode]
    entropy: float
    crossing_probability: float
    yielding_probability: float
    recommended_margin_m: float


class SocialIntentPredictor:
    """Interpretable multimodal pedestrian/cyclist predictor.

    Generates continue, yield, cross, and reverse hypotheses rather than one
    overconfident future. It is deliberately lightweight enough for phones and
    small companion computers and exposes uncertainty to the safety supervisor.
    """

    def __init__(self, horizon_steps: int = 24, dt_s: float = 0.15) -> None:
        self.horizon_steps = horizon_steps
        self.dt_s = dt_s

    def predict(self, agent: AgentObservation, couch_xy: tuple[float, float]) -> IntentPrediction:
        speed = math.hypot(agent.vx_mps, agent.vy_mps)
        to_couch = math.atan2(couch_xy[1] - agent.y_m, couch_xy[0] - agent.x_m)
        velocity_heading = math.atan2(agent.vy_mps, agent.vx_mps) if speed > 0.05 else (agent.heading_rad or 0.0)
        approach = max(0.0, math.cos(velocity_heading - to_couch))
        crossing = min(0.72, 0.10 + 0.45 * approach + 0.17 * agent.attention_to_couch)
        yielding = min(0.75, 0.12 + 0.48 * agent.attention_to_couch + (0.18 if speed < 0.7 else 0.0))
        reverse = 0.04 + (0.08 if speed < 0.2 else 0.0)
        straight = max(0.05, 1.0 - crossing - yielding - reverse)
        weights = [straight, yielding, crossing, reverse]
        total = sum(weights)
        probabilities = [value / total for value in weights]

        modes = [
            IntentMode("continue", probabilities[0], self._trajectory(agent, 1.0, 0.0)),
            IntentMode("yield", probabilities[1], self._trajectory(agent, 0.25, 0.0)),
            IntentMode("cross", probabilities[2], self._trajectory(agent, 0.85, math.pi / 2)),
            IntentMode("reverse", probabilities[3], self._trajectory(agent, -0.4, 0.0)),
        ]
        entropy = -sum(mode.probability * math.log(max(mode.probability, 1e-9)) for mode in modes)
        margin = agent.radius_m + 0.55 + 0.45 * entropy + 0.8 * crossing
        return IntentPrediction(agent.agent_id, modes, entropy, crossing, yielding, margin)

    def _trajectory(self, agent: AgentObservation, speed_scale: float, turn_rad: float) -> list[tuple[float, float]]:
        speed = math.hypot(agent.vx_mps, agent.vy_mps)
        heading = math.atan2(agent.vy_mps, agent.vx_mps) if speed > 0.05 else (agent.heading_rad or 0.0)
        heading += turn_rad
        velocity = speed * speed_scale
        return [
            (
                agent.x_m + math.cos(heading) * velocity * self.dt_s * step,
                agent.y_m + math.sin(heading) * velocity * self.dt_s * step,
            )
            for step in range(1, self.horizon_steps + 1)
        ]
