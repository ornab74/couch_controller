from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import FollowTargetRequest, MissionPlan, SafetyEnvelope, SensorFrame
from service import AutonomousCouchService

API_KEY = os.environ.get("COUCH_AUTONOMY_API_KEY", "dev-autonomy-key")
service = AutonomousCouchService()


class ArmRequest(BaseModel):
    armed: bool


class StopRequest(BaseModel):
    reason: str = "operator"


class SafetyRequest(BaseModel):
    envelope: SafetyEnvelope


async def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {API_KEY}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    service.stop_autonomy("server shutdown")


app = FastAPI(
    title="Couch Autonomous Simulation API",
    version="0.1.0",
    description="Simulation-only supervised autonomy layer for the couch controller.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "couch-autonomous-sim", "simulation_only": True}


@app.post("/v1/supervisor/heartbeat", dependencies=[Depends(authorize)])
def heartbeat() -> dict:
    service.set_supervisor_heartbeat()
    return {"ok": True}


@app.post("/v1/arm", dependencies=[Depends(authorize)])
def arm(request: ArmRequest) -> dict:
    try:
        service.set_armed(request.armed)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "armed": request.armed}


@app.post("/v1/estop", dependencies=[Depends(authorize)])
def estop(request: StopRequest) -> dict:
    service.emergency_stop(request.reason)
    return {"ok": True}


@app.post("/v1/estop/clear", dependencies=[Depends(authorize)])
def clear_estop() -> dict:
    service.clear_emergency_stop()
    return {"ok": True}


@app.post("/v1/mission", dependencies=[Depends(authorize)])
def load_mission(mission: MissionPlan) -> dict:
    service.load_mission(mission)
    return {"ok": True, "mission_id": mission.mission_id}


@app.post("/v1/mission/start", dependencies=[Depends(authorize)])
def start_mission() -> dict:
    try:
        service.start_mission()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/v1/follow/start", dependencies=[Depends(authorize)])
def start_follow(request: FollowTargetRequest) -> dict:
    try:
        service.start_follow(request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "target_id": request.target_id}


@app.post("/v1/autonomy/stop", dependencies=[Depends(authorize)])
def stop_autonomy(request: StopRequest) -> dict:
    service.stop_autonomy(request.reason)
    return {"ok": True}


@app.post("/v1/sensors", dependencies=[Depends(authorize)])
def sensors(frame: SensorFrame) -> dict:
    command = service.ingest_sensor_frame(frame)
    return {"ok": True, "command": command.model_dump()}


@app.get("/v1/telemetry", dependencies=[Depends(authorize)])
def telemetry() -> dict:
    service.tick()
    return service.telemetry().model_dump()


@app.get("/v1/events", dependencies=[Depends(authorize)])
def events() -> dict:
    return {"events": service.event_log()}
