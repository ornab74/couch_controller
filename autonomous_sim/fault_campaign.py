from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import random

from temporal_assurance import TemporalSnapshot


class FaultKind(str, Enum):
    gps_bias = "gps_bias"
    localization_dropout = "localization_dropout"
    supervisor_loss = "supervisor_loss"
    stale_command = "stale_command"
    obstacle_false_negative = "obstacle_false_negative"
    wheel_slip = "wheel_slip"
    actuator_stuck = "actuator_stuck"
    geofence_breach = "geofence_breach"


@dataclass(slots=True)
class FaultEvent:
    kind: FaultKind
    start_ms: int
    duration_ms: int
    magnitude: float = 1.0
    channel: str = "default"

    def active(self, timestamp_ms: int) -> bool:
        return self.start_ms <= timestamp_ms < self.start_ms + self.duration_ms


@dataclass(slots=True)
class FaultCampaign:
    campaign_id: str
    seed: int
    events: list[FaultEvent] = field(default_factory=list)


@dataclass(slots=True)
class InjectionResult:
    snapshot: TemporalSnapshot
    active_faults: list[str]
    annotations: dict[str, float | bool | str]


class DeterministicFaultInjector:
    """Repeatable fault injection for simulation and regression tests."""

    def __init__(self, campaign: FaultCampaign) -> None:
        self.campaign = campaign
        self.rng = random.Random(campaign.seed)
        self._stuck_speed: float | None = None

    def inject(self, snapshot: TemporalSnapshot) -> InjectionResult:
        current = snapshot
        active: list[str] = []
        annotations: dict[str, float | bool | str] = {}
        for event in self.campaign.events:
            if not event.active(snapshot.timestamp_ms):
                continue
            active.append(event.kind.value)
            if event.kind == FaultKind.localization_dropout:
                current = replace(current, localization_ok=False)
            elif event.kind == FaultKind.supervisor_loss:
                current = replace(current, supervisor_present=False)
            elif event.kind == FaultKind.geofence_breach:
                current = replace(current, inside_geofence=False)
            elif event.kind == FaultKind.obstacle_false_negative:
                current = replace(current, collision_free=True)
                annotations["obstacle_observation_suppressed"] = True
            elif event.kind == FaultKind.wheel_slip:
                measured = max(0.0, current.speed_mps * (1.0 - min(event.magnitude, 0.95)))
                current = replace(current, speed_mps=measured)
                annotations["wheel_slip_fraction"] = min(event.magnitude, 0.95)
            elif event.kind == FaultKind.actuator_stuck:
                if self._stuck_speed is None:
                    self._stuck_speed = current.commanded_speed_mps
                current = replace(current, commanded_speed_mps=self._stuck_speed)
                annotations["stuck_command_mps"] = self._stuck_speed
            elif event.kind == FaultKind.stale_command:
                annotations["command_age_ms"] = int(event.magnitude)
            elif event.kind == FaultKind.gps_bias:
                annotations["gps_bias_m"] = event.magnitude
        if FaultKind.actuator_stuck.value not in active:
            self._stuck_speed = None
        return InjectionResult(current, active, annotations)


def standard_campaign(start_ms: int) -> FaultCampaign:
    return FaultCampaign(
        campaign_id="standard-mission-assurance-v1",
        seed=7401,
        events=[
            FaultEvent(FaultKind.gps_bias, start_ms + 1000, 1500, 1.2),
            FaultEvent(FaultKind.localization_dropout, start_ms + 3500, 700),
            FaultEvent(FaultKind.supervisor_loss, start_ms + 5200, 900),
            FaultEvent(FaultKind.wheel_slip, start_ms + 7500, 1200, 0.45, "left"),
            FaultEvent(FaultKind.geofence_breach, start_ms + 9800, 600),
            FaultEvent(FaultKind.actuator_stuck, start_ms + 11600, 800),
        ],
    )
