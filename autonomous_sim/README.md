# Autonomous Couch — Phase 1 SITL

This branch starts the autonomous work as a **simulation-only, supervised** control layer. It does not drive GPIO or traction motors directly.

## Included

- Follow-target simulation mode
- Waypoint mission model
- Supervisor heartbeat requirement
- Arm/disarm gate
- Emergency stop
- Stale sensor timeout
- Camera/localization health checks
- Hard-stop and slow-down obstacle envelopes
- Normalized throttle/steering output for the existing safety controller
- Event log and telemetry API

## Start

```bash
cd autonomous_sim
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export COUCH_AUTONOMY_API_KEY=dev-autonomy-key
python run.py
```

Health check:

```bash
curl http://127.0.0.1:8790/health
```

Authenticated request example:

```bash
curl -X POST http://127.0.0.1:8790/v1/supervisor/heartbeat \
  -H 'Authorization: Bearer dev-autonomy-key'
```

## Safety sequence

The simulator requires this order:

1. Send supervisor heartbeats.
2. Arm autonomous control.
3. Load a mission or select follow-target mode.
4. Continuously submit sensor frames.
5. Read telemetry and normalized commands.

Any lost heartbeat, stale camera frame, failed sensor-health check, obstacle inside the stop envelope, or emergency stop produces zero throttle.

## Planned ArduPilot integration

Phase 2 will attach this service to ArduPilot Rover SITL over MAVLink using `pymavlink`:

```text
Flutter autonomous dashboard
        |
        | encrypted local API
        v
Autonomous supervisor service
        |
        | MAVLink UDP
        v
ArduPilot Rover SITL
        |
        v
Simulated skid-steer couch physics
```

The initial university route must remain synthetic. Do not operate on a public campus route without written authorization, a closed test area, a trained safety operator, a physical emergency stop, independent braking, geofencing, and low-speed validation.

## Camera concept

Start with four independently mounted views rather than eight:

- Forward wide camera above rider head height
- Rear wide camera
- Left side camera
- Right side camera

A depth camera or lidar should remain the primary close-range safety sensor. Phone cameras can provide inexpensive video and secondary perception, but should not be the sole collision-protection system.
