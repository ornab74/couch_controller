from __future__ import annotations

from dataclasses import asdict, dataclass

from conformal_risk import OnlineConformalRiskCalibrator
from social_intent import AgentObservation, SocialIntentPredictor


@dataclass(slots=True)
class CrowdRiskDecision:
    speed_scale: float
    required_margin_m: float
    max_crossing_probability: float
    max_intent_entropy: float
    conformal_margin_m: float
    intervention: str
    agents: list[dict]


class CrowdRiskFusion:
    """Combines social intent uncertainty with empirical prediction error.

    The output is advisory and may only reduce speed or increase clearance. It
    never expands the certified operating envelope.
    """

    def __init__(self) -> None:
        self.intent = SocialIntentPredictor()
        self.conformal = OnlineConformalRiskCalibrator()

    def observe_prediction_error(
        self,
        predicted_xy: tuple[float, float],
        measured_xy: tuple[float, float],
    ) -> None:
        self.conformal.observe(predicted_xy, measured_xy)

    def evaluate(
        self,
        agents: list[AgentObservation],
        couch_xy: tuple[float, float],
    ) -> CrowdRiskDecision:
        predictions = [self.intent.predict(agent, couch_xy) for agent in agents]
        conformal = self.conformal.report()
        maximum_crossing = max((p.crossing_probability for p in predictions), default=0.0)
        maximum_entropy = max((p.entropy for p in predictions), default=0.0)
        social_margin = max((p.recommended_margin_m for p in predictions), default=0.0)
        required_margin = max(social_margin, conformal.required_extra_margin_m)

        risk = min(1.0, 0.62 * maximum_crossing + 0.28 * maximum_entropy / 1.4)
        speed_scale = max(0.0, min(1.0, 1.0 - risk))
        if maximum_crossing >= 0.68 or required_margin >= 2.0:
            intervention = "hold"
            speed_scale = 0.0
        elif maximum_crossing >= 0.42 or maximum_entropy >= 1.1:
            intervention = "creep"
            speed_scale = min(speed_scale, 0.22)
        elif predictions:
            intervention = "yield_ready"
            speed_scale = min(speed_scale, 0.65)
        else:
            intervention = "clear"

        return CrowdRiskDecision(
            speed_scale=speed_scale,
            required_margin_m=required_margin,
            max_crossing_probability=maximum_crossing,
            max_intent_entropy=maximum_entropy,
            conformal_margin_m=conformal.required_extra_margin_m,
            intervention=intervention,
            agents=[
                {
                    "agent_id": prediction.agent_id,
                    "entropy": prediction.entropy,
                    "crossing_probability": prediction.crossing_probability,
                    "yielding_probability": prediction.yielding_probability,
                    "recommended_margin_m": prediction.recommended_margin_m,
                    "modes": [asdict(mode) for mode in prediction.modes],
                }
                for prediction in predictions
            ],
        )
