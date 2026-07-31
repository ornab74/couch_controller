from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import asdict

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from risk_mppi import BeliefState, Control, DynamicObstacle, RiskSensitiveMPPI
from runtime_assurance import ReachabilityRuntimeAssurance
from world_ensemble import CounterfactualWorldEnsemble

API_KEY = os.environ.get("COUCH_AUTONOMY_API_KEY", "dev-autonomy-key")
planner = RiskSensitiveMPPI()
assurance = ReachabilityRuntimeAssurance()
ensemble = CounterfactualWorldEnsemble()
lock = threading.RLock()
last_result: dict | None = None


class PoseBelief(BaseModel):
    x_m: float = 0
    y_m: float = 0
    yaw_rad: float = 0
    speed_mps: float = Field(default=0, ge=0, le=2)
    yaw_rate_rps: float = Field(default=0, ge=-2, le=2)
    position_sigma_m: float = Field(default=.15, ge=.01, le=5)
    yaw_sigma_rad: float = Field(default=.04, ge=.001, le=1)
    slip_probability: float = Field(default=.02, ge=0, le=1)


class MovingObstacle(BaseModel):
    x_m: float
    y_m: float
    vx_mps: float = Field(default=0, ge=-8, le=8)
    vy_mps: float = Field(default=0, ge=-8, le=8)
    radius_m: float = Field(default=.45, ge=.05, le=5)
    confidence: float = Field(default=1, ge=0, le=1)


class Point2(BaseModel):
    x_m: float
    y_m: float


class CertifiedPlanRequest(BaseModel):
    state: PoseBelief
    reference: list[Point2] = Field(min_length=1, max_length=200)
    obstacles: list[MovingObstacle] = Field(default_factory=list, max_length=256)


async def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {API_KEY}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid autonomy API key")


app = FastAPI(
    title="CouchPilot Certified Ensemble Autonomy",
    version="0.3.0",
    description="Risk-sensitive planning with counterfactual model ensembles and independent reachability assurance.",
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "couchpilot-certified-ensemble",
        "simulation_only": True,
        "planner": "risk_sensitive_mppi",
        "world_model": "counterfactual_dynamics_ensemble",
        "runtime_assurance": "reachable_uncertainty_tube",
    }


@app.post("/v3/planner/certified-plan", dependencies=[Depends(authorize)])
def certified_plan(request: CertifiedPlanRequest) -> dict:
    global last_result
    started = time.perf_counter()
    state = BeliefState(**request.state.model_dump())
    obstacles = [DynamicObstacle(**item.model_dump()) for item in request.obstacles]
    reference = [(point.x_m, point.y_m) for point in request.reference]

    with lock:
        plan = planner.plan(state, reference, obstacles)
        candidate_sequence = [plan.control for _ in range(18)]
        world = ensemble.predict(state, candidate_sequence, obstacles)
        scaled = Control(
            acceleration_mps2=plan.control.acceleration_mps2 * world.recommended_speed_scale,
            yaw_rate_rps=plan.control.yaw_rate_rps * world.recommended_speed_scale,
        )
        certificate = assurance.certify(state, scaled, obstacles)

    elapsed_ms = (time.perf_counter() - started) * 1000
    payload = {
        "ok": True,
        "timestamp_ms": int(time.time() * 1000),
        "requested_control": asdict(plan.control),
        "ensemble_scaled_control": asdict(scaled),
        "selected_control": asdict(certificate.selected),
        "runtime_assurance": asdict(certificate),
        "planner": {
            "name": plan.planner,
            "nominal_cost": plan.nominal_cost,
            "cvar_cost": plan.cvar_cost,
            "collision_probability": plan.collision_probability,
            "min_clearance_m": plan.min_clearance_m,
            "confidence": plan.confidence,
            "predicted_path": [{"x_m": x, "y_m": y} for x, y in plan.predicted_path],
        },
        "world_ensemble": {
            "disagreement_m": world.disagreement_m,
            "epistemic_risk": world.epistemic_risk,
            "worst_case_clearance_m": world.worst_case_clearance_m,
            "recommended_speed_scale": world.recommended_speed_scale,
            "trajectories": {
                name: [{"x_m": x, "y_m": y} for x, y in path]
                for name, path in world.trajectories.items()
            },
        },
        "compute_ms": elapsed_ms,
    }
    last_result = payload
    return payload


@app.get("/v3/planner/telemetry", dependencies=[Depends(authorize)])
def telemetry() -> dict:
    return last_result or {"ok": True, "state": "waiting_for_certified_plan"}
