# Couch Controller Secure Advanced

Landscape Flutter controller and four-motor Python couch simulator. The UI is intentionally dashboard-like for a widescreen phone: dual spring-return joysticks, live battery/speed/obstacle telemetry, motor temperatures and current, collision guard, arm state, lighting/horn controls, and a physical-style emergency stop.

## Security design

This revision does **not** place a universal symmetric secret inside the Flutter binary.

- **API key at rest:** encrypted with AES-256-GCM. A random 256-bit wrapping key is stored in Android Keystore / Apple Keychain through `flutter_secure_storage`; only nonce, ciphertext, and authentication tag are stored in preferences.
- **Couch identity:** the couch backend generates a persistent Ed25519 identity key on first boot. In production, provision this key in a secure element or TPM on the controller HAT.
- **Pairing:** the app creates an ephemeral X25519 key. The couch returns its ephemeral X25519 public key and signs the complete pairing transcript with Ed25519.
- **Identity pinning:** display and verify the couch fingerprint during first pairing, then save it. A different key is rejected.
- **Command channel:** HKDF-SHA256 derives a per-session AES-256-GCM key. Every command and telemetry response is encrypted and authenticated.
- **Replay defense:** each session uses a strictly increasing sequence number. Replayed or reordered control packets are rejected.
- **Session lifetime:** simulated sessions expire after 15 minutes and are renegotiated.
- **Transport independence:** the same encrypted envelope can travel over HTTPS/Wi-Fi or BLE. BLE pairing is treated as transport protection only, not application trust.
- **Safety:** 450 ms dead-man timeout, arm/disarm gate, emergency stop, command clamping, and collision-avoidance inhibition.

> Production recommendation: use TLS 1.3 as an additional outer layer for cloud/LAN use. Put the Ed25519 private key in a hardware secure element and never ship the same private key across multiple couches.

## Backend

```bash
cd sim_backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export COUCH_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export COUCH_BIND_HOST=0.0.0.0
export COUCH_IDENTITY_FILE="$PWD/couch_identity.key"
python run.py
```

The first run generates `couch_identity.key` with restrictive permissions. Back it up only if the couch identity must survive controller replacement.

## Flutter

```bash
cd flutter_app
flutter pub get
flutter run
```

Open settings in the controller, enter the server URL and API key, connect once, compare the displayed identity fingerprint with the fingerprint shown by the couch setup console, and then pin it.

## BLE controller HAT protocol

The Flutter BLE transport discovers:

- Service: `8d7b0001-32ad-4c59-b7f2-5c60a39d8830`
- Encrypted command characteristic: `8d7b0002-32ad-4c59-b7f2-5c60a39d8830`
- Encrypted telemetry characteristic: `8d7b0003-32ad-4c59-b7f2-5c60a39d8830`

The characteristic payload is a chunked UTF-8 JSON secure envelope. The controller HAT must reassemble frames, enforce maximum frame sizes, perform the same Ed25519/X25519 handshake, decrypt AES-GCM packets, verify sequence numbers, and only then pass normalized commands to the motor MCU.

## Hardware separation

Use two processors in a real build:

1. **Connectivity HAT:** BLE/Wi-Fi, identity keys, encrypted protocol, telemetry aggregation.
2. **Safety motor MCU:** watchdog, contactor/relay control, current limits, temperature limits, wheel encoders, bumper switches, and hardwired emergency stop.

The network-facing processor should never directly generate unrestricted PWM. The motor MCU must independently reject stale, malformed, unsafe, or over-limit commands.

## Multi-transport edition

The settings dialog now supports Local API, HTTPS Cloud API, USB HAT and Bluetooth LE. The API key/bootstrap secret is AES-256-GCM encrypted at rest. Linux no longer crashes when the desktop keyring is locked: it falls back to an app-support master-key file with mode `0600`.

Hardware references are under `hardware/`, including a Raspberry Pi packet bridge and an Arduino/Teensy watchdog controller.
