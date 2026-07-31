# CouchPilot Risk-Sensitive Autonomy

CouchPilot is an in-house, simulation-first autonomy layer for the four-motor couch. It does not embed ArduPilot and it does not depend on graph A* for local motion generation.

## Planner stack

1. **Belief-state estimation** — the planner consumes pose, velocity, heading uncertainty, and wheel-slip probability instead of pretending localization is exact.
2. **Risk-sensitive MPPI** — samples dynamically feasible acceleration/yaw-rate sequences in continuous control space.
3. **Moving-obstacle prediction** — each candidate is evaluated against time-indexed obstacle motion.
4. **Scenario rollouts** — every candidate is replayed under multiple localization/slip disturbances.
5. **CVaR tail optimization** — selection minimizes the expensive worst-case probability tail, not only average cost.
6. **Comfort objective** — acceleration, turn rate, and jerk are penalized for seated passengers.
7. **Control-barrier shield** — the selected command is projected toward braking when predicted clearance is below stopping distance plus uncertainty margin.
8. **Independent safety path** — the planner only requests motion; an independent MCU, watchdog, bumper chain, contactor, and physical E-stop retain final authority.

## Why this is beyond A*

A* searches discrete graph nodes and normally returns a geometric path. CouchPilot searches continuous, dynamically feasible control sequences while accounting for uncertainty, moving obstacles, stopping distance, rider comfort, and tail risk. A coarse corridor generator may later provide a reference, but the local control output remains model predictive.

## Run

```bash
cd autonomous_sim
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export COUCH_AUTONOMY_API_KEY=dev-autonomy-key
python run_couchpilot.py
```

In a second terminal:

```bash
cd flutter_app
flutter run -d linux -t lib/autonomy_main.dart
```

The dashboard exposes sampling count, uncertainty scenarios, CVaR tail fraction, moving-obstacle placement, predicted path, collision probability, clearance, planner confidence, and compute latency.

## Simulation boundary

This code is for software simulation and supervised closed-course research. It must not directly drive traction motor GPIO. Physical testing requires written site authorization, an isolated test area, low speed, independent braking, a trained safety operator, a physical emergency stop, and a safety controller capable of vetoing every motion command.
