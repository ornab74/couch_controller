from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

from models import (
    AutonomousCommand,
    AutonomousTelemetry,
    AutonomyMode,
    FollowTargetRequest,
    MissionPlan,
    SafetyEnvelope,
    SensorFrame,
)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class Event:
    timestamp_ms: int
    level: str
    code: str
    message: str


class AutonomousCouchService:
    """Simulation-only supervised autonomy controller.

    This layer never talks directly to motor GPIO. It emits normalized throttle
    and steering commands that must still pass through the existing safety MCU,
    arm gate, watchdog, bumper inputs, and physical emergency stop.
    """

    def __init__(self, safety: SafetyEnvelope | None = None) -> None:
        self._lock = threading.RLock()
        self.safety = safety or SafetyEnvelope()
        self.mode = AutonomyMode.parked
        self.armed = False
        self.estop = False
        self.supervisor_present = False
        self.last_supervisor_heartbeat_ms = 0
        self.last_sensor: SensorFrame | None = None
        self.mission: MissionPlan | None = None
        self.waypoint_index = 0
        self.follow: FollowTargetRequest | None = None
        self.last_command = AutonomousCommand(
            throttle=0,
            steering=0,
            requested_speed_mps=0,
            reason="boot",
        )
        self.events: deque[Event] = deque(maxlen=500)
        self._event("info", "BOOT", "Autonomous simulation service initialized")

    @staticmethod
    def now_ms() -> int:
        return int(time.time() * 1000)

    def _event(self, level: str, code: str, message: str) -> None:
        self.events.append(Event(self.now_ms(), level, code, message))

    def set_supervisor_heartbeat(self) -> None:
        with self._lock:
            self.last_supervisor_heartbeat_ms = self.now_ms()
            if not self.supervisor_present:
                self._event("info", "SUPERVISOR_ONLINE", "Supervisor heartbeat acquired")
            self.supervisor_present = True

    def set_armed(self, armed: bool) -> None:
        with self._lock:
            if armed and self.estop:
                raise ValueError("Cannot arm while emergency stop is active")
            if armed and not self.supervisor_present:
                raise ValueError("Cannot arm autonomous mode without a supervisor heartbeat")
            self.armed = armed
            if not armed:
                self.mode = AutonomyMode.parked
                self._stop("disarmed")
            self._event("info", "ARM_STATE", f"Autonomous arm state set to {armed}")

    def emergency_stop(self, reason: str = "operator") -> None:
        with self._lock:
            self.estop = True
            self.armed = False
            self.mode = AutonomyMode.emergency_stop
            self._stop(f"emergency stop: {reason}")
            self._event("critical", "ESTOP", reason)

    def clear_emergency_stop(self) -> None:
        with self._lock:
            self.estop = False
            self.mode = AutonomyMode.parked
            self._stop("estop cleared; re-arm required")
            self._event("warning", "ESTOP_CLEARED", "Emergency stop cleared; vehicle remains disarmed")

    def load_mission(self, mission: MissionPlan) -> None:
        with self._lock:
            self.mission = mission
            self.waypoint_index = 0
            self._event("info", "MISSION_LOADED", mission.mission_id)

    def start_mission(self) -> None:
        with self._lock:
            self._require_ready()
            if self.mission is None:
                raise ValueError("No mission loaded")
            self.mode = AutonomyMode.waypoint_mission
            self.follow = None
            self._event("info", "MISSION_STARTED", self.mission.mission_id)

    def start_follow(self, request: FollowTargetRequest) -> None:
        with self._lock:
            self._require_ready()
            self.follow = request
            self.mode = AutonomyMode.follow_target
            self._event("info", "FOLLOW_STARTED", request.target_id)

    def stop_autonomy(self, reason: str = "operator") -> None:
        with self._lock:
            self.mode = AutonomyMode.supervised if self.armed else AutonomyMode.parked
            self.follow = None
            self._stop(reason)
            self._event("info", "AUTONOMY_STOPPED", reason)

    def ingest_sensor_frame(self, frame: SensorFrame) -> AutonomousCommand:
        with self._lock:
            self.last_sensor = frame
            self._update_supervisor_state()
            self.last_command = self._calculate_command(frame)
            return self.last_command

    def tick(self) -> AutonomousCommand:
        with self._lock:
            self._update_supervisor_state()
            if self.last_sensor is None:
                return self._stop("waiting for sensor frame")
            age = self.now_ms() - self.last_sensor.timestamp_ms
            if age > self.safety.stale_sensor_timeout_ms:
                return self._stop("stale sensor frame")
            self.last_command = self._calculate_command(self.last_sensor)
            return self.last_command

    def _update_supervisor_state(self) -> None:
        age = self.now_ms() - self.last_supervisor_heartbeat_ms
        online = age <= self.safety.supervisor_heartbeat_timeout_ms
        if self.supervisor_present and not online:
            self._event("critical", "SUPERVISOR_LOST", "Supervisor heartbeat timed out")
            self._stop("supervisor heartbeat lost")
            self.mode = AutonomyMode.supervised if self.armed else AutonomyMode.parked
        self.supervisor_present = online

    def _require_ready(self) -> None:
        self._update_supervisor_state()
        if self.estop:
            raise ValueError("Emergency stop is active")
        if not self.armed:
            raise ValueError("Autonomous system is disarmed")
        if not self.supervisor_present:
            raise ValueError("Supervisor heartbeat is required")

    def _nearest_obstacle(self, frame: SensorFrame) -> float | None:
        valid = [o.distance_m for o in frame.obstacles if o.confidence >= 0.5]
        return min(valid) if valid else None

    def _speed_scale_for_obstacle(self, nearest: float | None) -> float:
        if nearest is None:
            return 1.0
        if nearest <= self.safety.hard_stop_distance_m:
            return 0.0
        if nearest >= self.safety.slow_zone_distance_m:
            return 1.0
        span = self.safety.slow_zone_distance_m - self.safety.hard_stop_distance_m
        return clamp((nearest - self.safety.hard_stop_distance_m) / span, 0.0, 1.0)

    def _calculate_command(self, frame: SensorFrame) -> AutonomousCommand:
        if self.estop:
            return self._stop("emergency stop active")
        if not self.armed:
            return self._stop("autonomy disarmed")
        if not self.supervisor_present:
            return self._stop("supervisor absent")
        if frame.camera_health < 0.5 or frame.localization_health < 0.5:
            return self._stop("sensor health below safety threshold")

        nearest = self._nearest_obstacle(frame)
        speed_scale = self._speed_scale_for_obstacle(nearest)
        if speed_scale == 0:
            return self._stop("obstacle inside hard-stop envelope")

        if self.mode == AutonomyMode.follow_target:
            return self._follow_command(frame, speed_scale)
        if self.mode == AutonomyMode.waypoint_mission:
            return self._mission_command(frame, speed_scale)
        return self._stop("no active autonomous behavior")

    def _follow_command(self, frame: SensorFrame, speed_scale: float) -> AutonomousCommand:
        assert self.follow is not None
        if not frame.target_visible:
            return self._stop("follow target not visible")
        if frame.target_confidence < self.follow.confidence_floor:
            return self._stop("follow target confidence too low")

        distance_error = frame.target_distance_m - self.follow.desired_distance_m
        if abs(distance_error) < 0.35:
            throttle = 0.0
        else:
            throttle = clamp(distance_error / 4.0, -0.35, 0.65)

        steering = clamp(frame.target_bearing_deg / 45.0, -0.75, 0.75)
        speed = min(abs(throttle) * self.follow.max_speed_mps, self.safety.max_speed_mps)
        speed *= speed_scale
        throttle *= speed_scale

        return AutonomousCommand(
            throttle=throttle,
            steering=steering,
            requested_speed_mps=speed,
            reason="follow target tracking",
        )

    def _mission_command(self, frame: SensorFrame, speed_scale: float) -> AutonomousCommand:
        # Phase 1 intentionally simulates path execution rather than performing
        # real GPS navigation. ArduPilot SITL/MAVLink will replace this stub.
        assert self.mission is not None
        waypoint = self.mission.waypoints[self.waypoint_index]
        nominal = min(
            waypoint.speed_mps,
            self.mission.max_speed_mps,
            self.safety.max_speed_mps,
        )
        speed = nominal * speed_scale
        throttle = clamp(speed / max(self.safety.max_speed_mps, 0.01), 0, 0.65)
        steering = math.sin(self.now_ms() / 5000.0) * 0.05
        return AutonomousCommand(
            throttle=throttle,
            steering=steering,
            requested_speed_mps=speed,
            reason=f"simulated mission waypoint {self.waypoint_index + 1}",
        )

    def _stop(self, reason: str) -> AutonomousCommand:
        self.last_command = AutonomousCommand(
            throttle=0,
            steering=0,
            requested_speed_mps=0,
            reason=reason,
        )
        return self.last_command

    def telemetry(self) -> AutonomousTelemetry:
        with self._lock:
            self._update_supervisor_state()
            now = self.now_ms()
            age = now - self.last_sensor.timestamp_ms if self.last_sensor else 2**31 - 1
            nearest = self._nearest_obstacle(self.last_sensor) if self.last_sensor else None
            target_locked = bool(
                self.last_sensor
                and self.last_sensor.target_visible
                and self.follow
                and self.last_sensor.target_confidence >= self.follow.confidence_floor
            )
            safety_state = "ESTOP" if self.estop else self.last_command.reason
            return AutonomousTelemetry(
                mode=self.mode,
                armed=self.armed,
                estop=self.estop,
                supervisor_present=self.supervisor_present,
                collision_avoidance_active=self.safety.require_collision_avoidance,
                mission_id=self.mission.mission_id if self.mission else None,
                waypoint_index=self.waypoint_index,
                target_id=self.follow.target_id if self.follow else None,
                target_locked=target_locked,
                target_distance_m=self.last_sensor.target_distance_m if target_locked else None,
                nearest_obstacle_m=nearest,
                commanded_speed_mps=self.last_command.requested_speed_mps,
                throttle=self.last_command.throttle,
                steering=self.last_command.steering,
                safety_state=safety_state,
                last_sensor_age_ms=max(0, age),
                event_count=len(self.events),
            )

    def event_log(self) -> list[dict]:
        with self._lock:
            return [event.__dict__ for event in self.events]
