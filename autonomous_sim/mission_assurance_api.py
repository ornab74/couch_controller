from __future__ import annotations

import os
import secrets
import time
from dataclasses import asdict

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from fault_campaign import DeterministicFaultInjector, FaultCampaign, FaultEvent, FaultKind, standard_campaign
from temporal_assurance import TemporalMissionAssurance, TemporalSnapshot

API_KEY = os.environ.get("COUCH_AUTONOMY_API_KEY", "dev-autonomy-key")
monitor = TemporalMissionAssurance()
injector: DeterministicFaultInjector | None = None
last_report: dict | None = None


class SnapshotRequest(BaseModel):
    timestamp_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    armed: bool = False
    estop: bool = False
    supervisor_present: bool = True
    localization_ok: bool = True
    collision_free: bool = True
    inside_geofence: bool = True
    speed_mps: float = Field(default=0, ge=0, le=3)
    commanded_speed_mps: float = Field(default=0, ge=-3, le=3)
    mission_active: bool = False
    goal_reached: bool = False


class FaultRequest(BaseModel):
    kind: FaultKind
    start_ms: int
    duration_ms: int = Field(ge=1, le=600000)
    magnitude: float = 1.0
    channel: str = "default"


class CampaignRequest(BaseModel):
    campaign_id: str = Field(min_length=3, max_length=120)
    seed: int = 7401
    events: list[FaultRequest] = Field(default_factory=list, max_length=100)


async def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {API_KEY}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid autonomy API key")


app = FastAPI(
    title="CouchPilot Formal Mission Assurance",
    version="0.5.0",
    description="Temporal safety contracts and deterministic fault campaigns for simulation-only validation.",
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "couchpilot-formal-mission-assurance",
        "simulation_only": True,
        "monitor": "bounded_temporal_contracts",
        "fault_engine": "deterministic_campaigns",
    }


@app.post("/v5/monitor/observe", dependencies=[Depends(authorize)])
def observe(request: SnapshotRequest) -> dict:
    global last_report
    snapshot = TemporalSnapshot(**request.model_dump())
    active_faults: list[str] = []
    annotations: dict = {}
    if injector is not None:
        injected = injector.inject(snapshot)
        snapshot = injected.snapshot
        active_faults = injected.active_faults
        annotations = injected.annotations
    rules = monitor.observe(snapshot)
    last_report = {
        "ok": True,
        "timestamp_ms": snapshot.timestamp_ms,
        "motion_veto": monitor.should_veto_motion(),
        "active_faults": active_faults,
        "fault_annotations": annotations,
        "snapshot": asdict(snapshot),
        "rules": [
            {
                "rule_id": rule.rule_id,
                "verdict": rule.verdict.value,
                "message": rule.message,
                "severity": rule.severity,
                "evidence": rule.evidence,
            }
            for rule in rules
        ],
    }
    return last_report


@app.get("/v5/monitor/report", dependencies=[Depends(authorize)])
def report() -> dict:
    return last_report or {"ok": True, "state": "waiting_for_snapshot"}


@app.post("/v5/campaign/load", dependencies=[Depends(authorize)])
def load_campaign(request: CampaignRequest) -> dict:
    global injector
    campaign = FaultCampaign(
        campaign_id=request.campaign_id,
        seed=request.seed,
        events=[FaultEvent(**event.model_dump()) for event in request.events],
    )
    injector = DeterministicFaultInjector(campaign)
    return {"ok": True, "campaign_id": campaign.campaign_id, "events": len(campaign.events)}


@app.post("/v5/campaign/load-standard", dependencies=[Depends(authorize)])
def load_standard() -> dict:
    global injector
    campaign = standard_campaign(int(time.time() * 1000))
    injector = DeterministicFaultInjector(campaign)
    return {"ok": True, "campaign_id": campaign.campaign_id, "events": len(campaign.events)}


@app.post("/v5/campaign/clear", dependencies=[Depends(authorize)])
def clear_campaign() -> dict:
    global injector
    injector = None
    return {"ok": True}


@app.post("/v5/monitor/reset", dependencies=[Depends(authorize)])
def reset_monitor() -> dict:
    global monitor, last_report
    monitor = TemporalMissionAssurance()
    last_report = None
    return {"ok": True}
