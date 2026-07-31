#!/usr/bin/env python3
"""Raspberry Pi USB/BLE HAT bridge reference.

This reference keeps all motor outputs disabled until a valid, fresh,
non-replayed AES-GCM packet is received. Replace MotorDriver with your isolated
motor-controller interface. Do not drive traction motors directly from GPIO.
"""
import asyncio, base64, hashlib, json, os, time
from dataclasses import dataclass
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

BOOTSTRAP_KEY = os.environ.get('COUCH_BOOTSTRAP_KEY', 'replace-me').encode()
COUCH_ID = b'couch-hat-v1'


def derive_key() -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b'couch-controller-local-v1', info=COUCH_ID).derive(BOOTSTRAP_KEY)

@dataclass
class SafetyState:
    armed: bool = False
    estop: bool = False
    last_sequence: int = 0
    last_command: float = 0.0

state = SafetyState()


def open_packet(packet: dict) -> dict:
    seq = int(packet['sequence'])
    ts = int(packet['timestamp_ms'])
    if seq <= state.last_sequence:
        raise ValueError('replay detected')
    if abs(int(time.time() * 1000) - ts) > 3000:
        raise ValueError('stale packet')
    header = {'v': packet['v'], 'couch_id': packet['couch_id'], 'sequence': seq, 'timestamp_ms': ts}
    aad = json.dumps(header, separators=(',', ':')).encode()
    nonce = base64.urlsafe_b64decode(packet['nonce'] + '==')
    cipher = base64.urlsafe_b64decode(packet['ciphertext'] + '==')
    tag = base64.urlsafe_b64decode(packet['tag'] + '==')
    clear = AESGCM(derive_key()).decrypt(nonce, cipher + tag, aad)
    state.last_sequence = seq
    state.last_command = time.monotonic()
    return json.loads(clear)


def dispatch(command: dict) -> dict:
    path, body = command.get('path'), command.get('body', {})
    if path == '/v1/arm':
        state.armed = bool(body.get('armed')) and not state.estop
    elif path == '/v1/estop':
        state.estop, state.armed = True, False
    elif path == '/v1/estop/clear':
        state.estop = False
    elif path == '/v1/drive':
        throttle = max(-1.0, min(1.0, float(body.get('throttle', 0))))
        steering = max(-1.0, min(1.0, float(body.get('steering', 0))))
        if not state.armed or state.estop:
            throttle = steering = 0.0
        # Send these normalized values to an independent safety MCU.
        print(f'DRIVE throttle={throttle:.3f} steering={steering:.3f}', flush=True)
    return {'accepted': True, 'armed': state.armed, 'estop': state.estop}


async def watchdog():
    while True:
        if state.armed and time.monotonic() - state.last_command > 0.45:
            state.armed = False
            print('WATCHDOG STOP', flush=True)
        await asyncio.sleep(0.05)

if __name__ == '__main__':
    print('Reference bridge. Integrate serial/BLE GATT I/O around open_packet() and dispatch().')
    asyncio.run(watchdog())
