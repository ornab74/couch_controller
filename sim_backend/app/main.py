from __future__ import annotations

import asyncio
import math
import os
import random
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock

from fastapi import Depends, FastAPI, Header, HTTPException, status

from .secure_channel import SecureChannel
from pydantic import BaseModel, Field

API_KEY = os.getenv("COUCH_API_KEY", "dev-couch-key")

app = FastAPI(title="Four-Motor Couch Simulator", version="0.2.0")
secure = SecureChannel(os.getenv("COUCH_IDENTITY_FILE", "./couch_identity.key"), API_KEY)


class DriveCommand(BaseModel):
    throttle: float = Field(ge=-1.0, le=1.0)
    steering: float = Field(ge=-1.0, le=1.0)


class ArmCommand(BaseModel):
    armed: bool


class ToggleCommand(BaseModel):
    enabled: bool


@dataclass
class Motor:
    id: str
    rpm: float = 0.0
    temperature_c: float = 28.0
    current_a: float = 0.0
    output: float = 0.0


class CouchSimulation:
    def __init__(self) -> None:
        self.lock = Lock()
        self.armed = False
        self.estop = False
        self.collision_avoidance = True
        self.throttle = 0.0
        self.steering = 0.0
        self.speed_mph = 0.0
        self.heading_deg = 0.0
        self.battery_percent = 82.0
        self.battery_voltage = 50.8
        self.closest_obstacle_ft = 12.0
        self.last_command = time.monotonic()
        self.motors = [Motor("FRONT LEFT"), Motor("FRONT RIGHT"), Motor("REAR LEFT"), Motor("REAR RIGHT")]

    def command(self, throttle: float, steering: float) -> None:
        with self.lock:
            self.last_command = time.monotonic()
            if not self.armed or self.estop:
                self.throttle = self.steering = 0.0
                return
            # Simulated safety envelope: inhibit forward motion inside 2.5 ft.
            if self.collision_avoidance and self.closest_obstacle_ft < 2.5 and throttle > 0:
                throttle = 0.0
            self.throttle, self.steering = throttle, steering

    def tick(self, dt: float) -> None:
        with self.lock:
            # Dead-man timeout: motion command must be refreshed continuously.
            if time.monotonic() - self.last_command > 0.45:
                self.throttle = self.steering = 0.0
            if not self.armed or self.estop:
                self.throttle = self.steering = 0.0

            target_speed = self.throttle * 5.0
            self.speed_mph += (target_speed - self.speed_mph) * min(1.0, dt * 3.0)
            self.heading_deg = (self.heading_deg + self.steering * abs(self.speed_mph) * dt * 20.0) % 360

            # Simulate a changing ultrasonic/LiDAR proximity reading.
            wander = random.uniform(-0.25, 0.25)
            self.closest_obstacle_ft = min(18.0, max(1.2, self.closest_obstacle_ft + wander))
            if self.collision_avoidance and self.closest_obstacle_ft < 2.5 and self.speed_mph > 0:
                self.speed_mph *= 0.72

            left = max(-1.0, min(1.0, self.throttle - self.steering * 0.65))
            right = max(-1.0, min(1.0, self.throttle + self.steering * 0.65))
            outputs = [left, right, left, right]
            total_current = 0.0
            for motor, output in zip(self.motors, outputs):
                motor.output = output
                motor.rpm += (output * 1450 - motor.rpm) * min(1.0, dt * 5.0)
                motor.current_a = abs(output) * 16.0 + abs(self.speed_mph) * 0.45
                total_current += motor.current_a
                heat_in = motor.current_a * 0.030
                cooling = max(0.0, motor.temperature_c - 27.0) * 0.018
                motor.temperature_c += (heat_in - cooling) * dt

            self.battery_percent = max(0.0, self.battery_percent - total_current * dt / 160000.0 * 100.0)
            self.battery_voltage = 42.0 + self.battery_percent / 100.0 * 10.0 - total_current * 0.012

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "connected": True,
                "armed": self.armed,
                "battery_percent": round(self.battery_percent, 2),
                "battery_voltage": round(self.battery_voltage, 2),
                "speed_mph": round(self.speed_mph, 3),
                "heading_deg": round(self.heading_deg, 2),
                "collision_avoidance": self.collision_avoidance,
                "closest_obstacle_ft": round(self.closest_obstacle_ft, 2),
                "estop": self.estop,
                "motors": [asdict(m) for m in self.motors],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }


sim = CouchSimulation()


def authorize(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, API_KEY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")


@app.on_event("startup")
async def startup() -> None:
    async def loop() -> None:
        last = time.monotonic()
        while True:
            now = time.monotonic()
            sim.tick(min(0.1, now - last))
            last = now
            await asyncio.sleep(0.02)
    asyncio.create_task(loop())


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "couch-simulator"}


@app.get("/v1/telemetry", dependencies=[Depends(authorize)])
def telemetry() -> dict:
    return sim.snapshot()


@app.post("/v1/drive", dependencies=[Depends(authorize)])
def drive(command: DriveCommand) -> dict:
    sim.command(command.throttle, command.steering)
    return {"accepted": True}


@app.post("/v1/arm", dependencies=[Depends(authorize)])
def arm(command: ArmCommand) -> dict:
    with sim.lock:
        if sim.estop and command.armed:
            raise HTTPException(status_code=409, detail="Clear emergency stop before arming")
        sim.armed = command.armed
        if not command.armed:
            sim.throttle = sim.steering = 0.0
    return {"armed": sim.armed}


@app.post("/v1/safety/collision-avoidance", dependencies=[Depends(authorize)])
def collision_avoidance(command: ToggleCommand) -> dict:
    with sim.lock:
        sim.collision_avoidance = command.enabled
    return {"enabled": sim.collision_avoidance}


@app.post("/v1/estop", dependencies=[Depends(authorize)])
def estop() -> dict:
    with sim.lock:
        sim.estop = True
        sim.armed = False
        sim.throttle = sim.steering = 0.0
    return {"estop": True}


@app.post("/v1/estop/clear", dependencies=[Depends(authorize)])
def clear_estop() -> dict:
    with sim.lock:
        sim.estop = False
    return {"estop": False}


class SessionRequest(BaseModel):
    api_key: str
    client_public_key: str
    client_nonce: str


@app.get("/v2/security/identity")
def security_identity() -> dict:
    return {"identity_public_key": secure.identity_public.hex(), "identity_fingerprint": secure.fingerprint}


@app.post("/v2/security/session")
def security_session(request: SessionRequest) -> dict:
    try:
        return secure.create_session(request.api_key, request.client_public_key, request.client_nonce)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def dispatch_secure(message: dict) -> dict:
    method, path, body = message.get("method"), message.get("path"), message.get("body", {})
    if method == "GET" and path == "/v1/telemetry":
        return sim.snapshot()
    if method == "POST" and path == "/v1/drive":
        sim.command(float(body["throttle"]), float(body["steering"]))
        return {"accepted": True}
    if method == "POST" and path == "/v1/arm":
        with sim.lock:
            if sim.estop and body.get("armed"):
                return {"error": "clear emergency stop before arming"}
            sim.armed = bool(body.get("armed"))
            if not sim.armed:
                sim.throttle = sim.steering = 0.0
        return {"armed": sim.armed}
    if method == "POST" and path == "/v1/safety/collision-avoidance":
        with sim.lock:
            sim.collision_avoidance = bool(body.get("enabled"))
        return {"enabled": sim.collision_avoidance}
    if method == "POST" and path == "/v1/estop":
        with sim.lock:
            sim.estop = True
            sim.armed = False
            sim.throttle = sim.steering = 0.0
        return {"estop": True}
    if method == "POST" and path == "/v1/estop/clear":
        with sim.lock:
            sim.estop = False
        return {"estop": False}
    return {"error": "unsupported secure route"}


@app.post("/v2/secure")
def secure_request(envelope: dict) -> dict:
    try:
        session, message = secure.decrypt(envelope)
        result = dispatch_secure(message)
        return secure.encrypt(envelope["session_id"], session, int(envelope["sequence"]), result)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid encrypted envelope: {exc}") from exc
