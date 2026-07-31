from __future__ import annotations

import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from crowd_risk_fusion import CrowdRiskFusion
from social_intent import AgentObservation

API_KEY = os.environ.get("COUCH_AUTONOMY_API_KEY", "dev-autonomy-key")
fusion = CrowdRiskFusion()


class AgentRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)
    x_m: float
    y_m: float
    vx_mps: float
    vy_mps: float
    radius_m: float = Field(default=.4, ge=.1, le=2)
    heading_rad: float | None = None
    attention_to_couch: float = Field(default=.5, ge=0, le=1)


class CrowdRequest(BaseModel):
    couch_x_m: float = 0
    couch_y_m: float = 0
    agents: list[AgentRequest] = Field(default_factory=list, max_length=128)


class ResidualRequest(BaseModel):
    predicted_x_m: float
    predicted_y_m: float
    measured_x_m: float
    measured_y_m: float


async def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {API_KEY}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid autonomy API key")


app = FastAPI(
    title="CouchPilot Crowd-Aware Risk Service",
    version="0.4.0",
    description="Multimodal social intent prediction plus online conformal safety calibration.",
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "couchpilot-crowd-risk",
        "simulation_only": True,
        "intent_model": "multimodal_interpretable_lattice",
        "calibration": "online_split_conformal",
    }


@app.post("/v4/crowd/evaluate", dependencies=[Depends(authorize)])
def evaluate(request: CrowdRequest) -> dict:
    agents = [AgentObservation(**item.model_dump()) for item in request.agents]
    decision = fusion.evaluate(agents, (request.couch_x_m, request.couch_y_m))
    return {
        "ok": True,
        "speed_scale": decision.speed_scale,
        "required_margin_m": decision.required_margin_m,
        "max_crossing_probability": decision.max_crossing_probability,
        "max_intent_entropy": decision.max_intent_entropy,
        "conformal_margin_m": decision.conformal_margin_m,
        "intervention": decision.intervention,
        "agents": decision.agents,
    }


@app.post("/v4/calibration/residual", dependencies=[Depends(authorize)])
def residual(request: ResidualRequest) -> dict:
    fusion.observe_prediction_error(
        (request.predicted_x_m, request.predicted_y_m),
        (request.measured_x_m, request.measured_y_m),
    )
    report = fusion.conformal.report()
    return {"ok": True, "report": report.__dict__}


@app.post("/v4/calibration/reset", dependencies=[Depends(authorize)])
def reset() -> dict:
    fusion.conformal.reset()
    return {"ok": True}
