from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AutonomyMode(str, Enum):
    parked = "parked"
    supervised = "supervised"
    follow_target = "follow_target"
    waypoint_mission = "waypoint_mission"
    return_home = "return_home"
    emergency_stop = "emergency_stop"


class GeoPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = 0.0


class MissionWaypoint(BaseModel):
    point: GeoPoint
    speed_mps: float = Field(default=0.75, ge=0.05, le=1.5)
    acceptance_radius_m: float = Field(default=1.5, ge=0.5, le=10)
    hold_seconds: float = Field(default=0, ge=0, le=120)


class MissionPlan(BaseModel):
    mission_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=3, max_length=120)
    waypoints: list[MissionWaypoint] = Field(min_length=1, max_length=100)
    geofence_radius_m: float = Field(default=150, ge=5, le=1000)
    max_speed_mps: float = Field(default=1.0, ge=0.05, le=1.5)
    requires_supervisor: bool = True


class FollowTargetRequest(BaseModel):
    target_id: str = Field(min_length=1, max_length=80)
    desired_distance_m: float = Field(default=3.0, ge=1.5, le=10)
    max_speed_mps: float = Field(default=0.75, ge=0.05, le=1.0)
    confidence_floor: float = Field(default=0.75, ge=0.5, le=0.99)


class ObstacleObservation(BaseModel):
    bearing_deg: float = Field(ge=-180, le=180)
    distance_m: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    source: Literal["camera", "depth", "lidar", "ultrasonic", "bumper", "sim"] = "sim"


class SensorFrame(BaseModel):
    timestamp_ms: int = Field(ge=0)
    target_visible: bool = False
    target_bearing_deg: float = Field(default=0, ge=-180, le=180)
    target_distance_m: float = Field(default=0, ge=0, le=100)
    target_confidence: float = Field(default=0, ge=0, le=1)
    obstacles: list[ObstacleObservation] = Field(default_factory=list, max_length=256)
    camera_health: float = Field(default=1, ge=0, le=1)
    localization_health: float = Field(default=1, ge=0, le=1)


class SafetyEnvelope(BaseModel):
    max_speed_mps: float = Field(default=1.0, ge=0.05, le=1.5)
    hard_stop_distance_m: float = Field(default=1.25, ge=0.5, le=5)
    slow_zone_distance_m: float = Field(default=4.0, ge=1.5, le=15)
    stale_sensor_timeout_ms: int = Field(default=500, ge=100, le=5000)
    supervisor_heartbeat_timeout_ms: int = Field(default=750, ge=100, le=5000)
    max_camera_health_loss_seconds: float = Field(default=1.0, ge=0.1, le=10)
    require_collision_avoidance: bool = True

    @field_validator("slow_zone_distance_m")
    @classmethod
    def slow_zone_must_exceed_stop_zone(cls, value: float, info):
        stop = info.data.get("hard_stop_distance_m")
        if stop is not None and value <= stop:
            raise ValueError("slow_zone_distance_m must exceed hard_stop_distance_m")
        return value


class AutonomousCommand(BaseModel):
    throttle: float = Field(ge=-1, le=1)
    steering: float = Field(ge=-1, le=1)
    requested_speed_mps: float = Field(ge=0, le=1.5)
    reason: str


class AutonomousTelemetry(BaseModel):
    mode: AutonomyMode
    armed: bool
    estop: bool
    supervisor_present: bool
    collision_avoidance_active: bool
    mission_id: str | None
    waypoint_index: int
    target_id: str | None
    target_locked: bool
    target_distance_m: float | None
    nearest_obstacle_m: float | None
    commanded_speed_mps: float
    throttle: float
    steering: float
    safety_state: str
    last_sensor_age_ms: int
    event_count: int
