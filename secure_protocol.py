"""
secure_protocol.py
------------------
The application-layer protocol used between patient devices and the server.

Transport : TCP  (reliable, ordered delivery)
Security  : TLS  (encryption on the wire)  +  HMAC-SHA256 (message integrity
            and device authentication)  +  timestamp & sequence number
            (protection against replay attacks)
Framing   : one JSON object per line, terminated by "\n"

Packet format sent by a device:
{
  "device_id": "BED-01",
  "seq": 42,
  "timestamp": 1758700000.123,
  "source": "simulator",
  "vitals": {"heart_rate": 78, "spo2": 98, ...},
  "hmac": "<hex digest>"
}
"""

import hashlib
import hmac
import json
import time


def _canonical(packet: dict) -> bytes:
    """Return the bytes that are signed: every field except 'hmac',
    with keys sorted so sender and receiver produce identical bytes."""
    body = {k: v for k, v in packet.items() if k != "hmac"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def sign_packet(packet: dict, secret_key: str) -> dict:
    """Attach an HMAC-SHA256 signature to the packet."""
    digest = hmac.new(secret_key.encode(), _canonical(packet), hashlib.sha256).hexdigest()
    packet["hmac"] = digest
    return packet


def verify_packet(packet: dict, secret_key: str) -> bool:
    """Check the signature using a constant-time comparison."""
    received = packet.get("hmac", "")
    expected = hmac.new(secret_key.encode(), _canonical(packet), hashlib.sha256).hexdigest()
    return hmac.compare_digest(received, expected)


def build_packet(device_id: str, seq: int, vitals: dict, secret_key: str,
                 source: str = "device") -> bytes:
    """Create, sign and frame a packet ready to be sent on the socket.
    'source' tells the server what produced the data (simulator, gui, csv...)."""
    packet = {
        "device_id": device_id,
        "seq": seq,
        "timestamp": time.time(),
        "source": source,
        "vitals": vitals,
    }
    sign_packet(packet, secret_key)
    return (json.dumps(packet) + "\n").encode()


def encode_message(obj: dict) -> bytes:
    """Frame any dict (used for server acknowledgements)."""
    return (json.dumps(obj) + "\n").encode()
