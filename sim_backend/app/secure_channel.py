from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))


def raw_public(key) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def load_or_create_identity(path: str) -> Ed25519PrivateKey:
    file = Path(path)
    if file.exists():
        return Ed25519PrivateKey.from_private_bytes(unb64(file.read_text().strip()))
    file.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    file.write_text(b64(private))
    try:
        os.chmod(file, 0o600)
    except OSError:
        pass
    return key


@dataclass
class Session:
    key: bytes
    expires_at: float
    highest_sequence: int = 0


class SecureChannel:
    def __init__(self, identity_path: str, api_key: str):
        self.identity = load_or_create_identity(identity_path)
        self.api_key = api_key
        self.sessions: dict[str, Session] = {}

    @property
    def identity_public(self) -> bytes:
        return raw_public(self.identity.public_key())

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(self.identity_public).hexdigest().upper()
        return ':'.join(digest[i:i+4] for i in range(0, 32, 4))

    def create_session(self, api_key: str, client_public_key: str, client_nonce: str) -> dict:
        if not secrets.compare_digest(api_key, self.api_key):
            raise PermissionError('invalid API key')
        client_pub_raw = unb64(client_public_key)
        client_nonce_raw = unb64(client_nonce)
        server_pair = X25519PrivateKey.generate()
        server_pub_raw = raw_public(server_pair.public_key())
        server_nonce = secrets.token_bytes(32)
        shared = server_pair.exchange(X25519PublicKey.from_public_bytes(client_pub_raw))
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=client_nonce_raw + server_nonce, info=b'couch-control/session/v2').derive(shared)
        session_id = secrets.token_urlsafe(24)
        self.sessions[session_id] = Session(key=key, expires_at=time.time() + 900)
        transcript = '|'.join((session_id, client_public_key, b64(server_pub_raw), client_nonce, b64(server_nonce))).encode()
        return {
            'session_id': session_id,
            'server_public_key': b64(server_pub_raw),
            'server_nonce': b64(server_nonce),
            'identity_public_key': b64(self.identity_public),
            'identity_fingerprint': self.fingerprint,
            'signature': b64(self.identity.sign(transcript)),
            'expires_in': 900,
        }

    def decrypt(self, envelope: dict) -> tuple[Session, dict]:
        session_id = envelope['session_id']
        session = self.sessions.get(session_id)
        if session is None or session.expires_at < time.time():
            self.sessions.pop(session_id, None)
            raise PermissionError('expired session')
        sequence = int(envelope['sequence'])
        if sequence <= session.highest_sequence:
            raise RuntimeError('replayed or reordered packet')
        aad = f'{session_id}:{sequence}'.encode()
        plain = AESGCM(session.key).decrypt(unb64(envelope['nonce']), unb64(envelope['ciphertext']) + unb64(envelope['tag']), aad)
        session.highest_sequence = sequence
        return session, json.loads(plain)

    def encrypt(self, session_id: str, session: Session, sequence: int, payload: dict) -> dict:
        nonce = secrets.token_bytes(12)
        aad = f'{session_id}:{sequence}'.encode()
        sealed = AESGCM(session.key).encrypt(nonce, json.dumps(payload, separators=(',', ':')).encode(), aad)
        return {'session_id': session_id, 'sequence': sequence, 'nonce': b64(nonce), 'ciphertext': b64(sealed[:-16]), 'tag': b64(sealed[-16:])}
