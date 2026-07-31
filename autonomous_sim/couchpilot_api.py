from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import asdict

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from risk_mppi import BeliefState, DynamicObstacle, PlannerConfig, RiskSensitiveMPPI

API_KEY = os.environ.get("COUCH_AUTONOMY_API_KEY", "dev-autonomy-key")
planner = RiskSensitiveMPPI()
lock = threading.RLock()
last_plan: dict | None = None


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


class PlanningRequest(BaseModel):
    state: PoseBelief
    reference: list[Point2] = Field(min_length=1, max_length=200)
    obstacles: list[MovingObstacle] = Field(default_factory=list, max_length=256)


class PlannerSettings(BaseModel):
    horizon_steps: int = Field(default=28, ge=8, le=80)
    samples: int = Field(default=420, ge=32, le=4000)
    iterations: int = Field(default=4, ge=1, le=12)
    cvar_alpha: float = Field(default=.18, ge=.03, le=.5)
    scenario_count: int = Field(default=7, ge=1, le=32)
    max_speed_mps: float = Field(default=1.15, ge=.05, le=1.5)


async def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {API_KEY}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid autonomy API key")


app = FastAPI(
    title="CouchPilot Risk-Sensitive Autonomy",
    version="0.2.0",
    description="In-house stochastic model-predictive planning for simulation and supervised testing.",
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "couchpilot-risk-mppi",
        "simulation_only": True,
        "planner": "risk_sensitive_mppi_cbf",
    }


@app.post("/v2/planner/config", dependencies=[Depends(authorize)])
def configure(settings: PlannerSettings) -> dict:
    global planner
    with lock:
        planner = RiskSensitiveMPPI(PlannerConfig(**settings.model_dump()))
    return {"ok": True, "config": settings.model_dump()}


@app.post("/v2/planner/reset", dependencies=[Depends(authorize)])
def reset() -> dict:
    with lock:
        planner.reset()
    return {"ok": True}


@app.post("/v2/planner/plan", dependencies=[Depends(authorize)])
def plan(request: PlanningRequest) -> dict:
    global last_plan
    started = time.perf_counter()
    state = BeliefState(**request.state.model_dump())
    obstacles = [DynamicObstacle(**item.model_dump()) for item in request.obstacles]
    reference = [(point.x_m, point.y_m) for point in request.reference]
    with lock:
        result = planner.plan(state, reference, obstacles)
    elapsed_ms = (time.perf_counter() - started) * 1000
    payload = {
        "ok": True,
        "timestamp_ms": int(time.time() * 1000),
        "control": asdict(result.control),
        "predicted_path": [{"x_m": x, "y_m": y} for x, y in result.predicted_path],
        "nominal_cost": result.nominal_cost,
        "cvar_cost": result.cvar_cost,
        "collision_probability": result.collision_probability,
        "min_clearance_m": result.min_clearance_m,
        "confidence": result.confidence,
        "planner": result.planner,
        "compute_ms": elapsed_ms,
        "diagnostics": result.diagnostics,
    }
    last_plan = payload
    return payload


@app.get("/v2/planner/telemetry", dependencies=[Depends(authorize)])
def telemetry() -> dict:
    return last_plan or {"ok": True, "planner": "risk_sensitive_mppi_cbf", "state": "waiting_for_plan"}
