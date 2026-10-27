"""
monitor_core.py
---------------
THE NETWORK RECEIVER. This is where vital signs arrive from the network.

For every bedside monitor that connects:
  1. TCP three-way handshake        (done by the operating system)
  2. TLS handshake                  (certificate + key exchange -> encrypted channel)
  3. Read one line = one packet     (application-layer framing)
  4. Verify the packet              (5 checks, see receive_packet)
  5. Store + evaluate + alert
  6. Send an acknowledgement (ACK) back to the device

Every packet and every check is recorded in `inspector` so the Network
page can show exactly how each reading was received.
"""

import json
import socket
import ssl
import threading
import time
from collections import deque
from datetime import datetime

import config
import database as db
from secure_protocol import encode_message, verify_packet

lock = threading.RLock()
SERVER_START = time.time()

devices = {}                       # device_id -> live state of one patient's monitor
alerts = deque(maxlen=200)
network_log = deque(maxlen=200)    # connection-level events
inspector = deque(maxlen=40)       # packet-level details (newest first)
stats = {"packets_accepted": 0, "packets_rejected": 0, "bytes_received": 0,
         "reject_reasons": {}, "connections_total": 0}
_alert_id = 0

LABELS = {"heart_rate": "Heart rate", "spo2": "SpO2", "temperature": "Temperature",
          "resp_rate": "Respiration", "bp_sys": "Systolic BP", "bp_dia": "Diastolic BP"}
UNITS = {"heart_rate": "bpm", "spo2": "%", "temperature": "°C",
         "resp_rate": "/min", "bp_sys": "mmHg", "bp_dia": "mmHg"}


# =================================================================
# Patient / device registry (loaded from the database)
# =================================================================
def load_patient(p):
    """Add (or refresh) one admitted patient in the live registry."""
    with lock:
        old = devices.get(p["device_id"], {})
        devices[p["device_id"]] = {
            "device_id": p["device_id"], "patient_id": p["id"], "patient_code": p["patient_code"],
            "patient": p["full_name"], "age": p["age"], "gender": p["gender"],
            "ward": p["ward"], "bed": p["bed"], "doctor": p["doctor"],
            "key": p["device_key"], "limits": p["limits"],
            "vitals": old.get("vitals"), "status": old.get("status", "offline"),
            "flags": old.get("flags", []), "last_seen": old.get("last_seen"),
            "ip": old.get("ip"), "port": old.get("port"), "tls": old.get("tls"),
            "packets": old.get("packets", 0), "latency_ms": old.get("latency_ms"),
            "recent_macs": old.get("recent_macs", deque(maxlen=500)),
            "history": old.get("history") or deque(
                ({"t": 0, **{k: r[k] for k in db.VITAL_KEYS}} for r in db.recent_readings(p["device_id"])),
                maxlen=300),
        }


def unload_patient(device_id):
    with lock:
        devices.pop(device_id, None)


def load_all():
    for p in db.list_patients("admitted"):
        load_patient(p)


# =================================================================
# Clinical evaluation using the limits the doctor entered
# =================================================================
def evaluate(v, limits):
    flags = [k for k, (lo, hi) in limits.items() if v[k] < lo or v[k] > hi]
    far = any(v[k] < lo - 0.1 * (hi - lo) or v[k] > hi + 0.15 * (hi - lo)
              for k, (lo, hi) in limits.items())
    if len(flags) >= 2 or (flags and far):
        return "critical", flags
    if flags:
        return "warning", flags
    return "normal", flags


def _raise_alert(dev, level, flags, v):
    global _alert_id
    msg = ", ".join(f"{LABELS[f]} {v[f]} {UNITS[f]}" for f in flags) or "Vitals out of range"
    _alert_id += 1
    alerts.appendleft({"id": _alert_id, "device_id": dev["device_id"], "patient": dev["patient"],
                       "level": level, "message": msg, "time": datetime.now().strftime("%H:%M:%S"),
                       "acknowledged": False, "ack_by": None})
    db.save_alert(dev["device_id"], level, msg)


def _log(kind, device, source, detail):
    network_log.appendleft({"time": datetime.now().strftime("%H:%M:%S"), "kind": kind,
                            "device": device or "awaiting ID", "ip": source, "detail": detail})


# =================================================================
# Receiving ONE packet  (called for every line that arrives)
# =================================================================
def receive_packet(line, ip, port, tls_info, last_seq):
    """Run all checks on one received line. Returns (ack_dict, device_id or None)."""
    arrived = time.time()
    record = {"time": datetime.now().strftime("%H:%M:%S"), "from": f"{ip}:{port}",
              "tls": tls_info, "bytes": len(line.encode()), "raw": line.strip()[:600],
              "checks": [], "result": "", "device_id": None}

    def check(name, ok, detail):
        record["checks"].append({"name": name, "ok": ok, "detail": detail})
        return ok

    def reject(reason, fatal=False):
        stats["packets_rejected"] += 1
        stats["reject_reasons"][reason] = stats["reject_reasons"].get(reason, 0) + 1
        record["result"] = "Rejected: " + reason
        _log("REJECTED", record["device_id"], f"{ip}:{port}", reason)
        inspector.appendleft(record)
        return {"status": "rejected", "reason": reason, "fatal": fatal}, None

    with lock:
        stats["bytes_received"] += record["bytes"]

        # Check 1: is it valid JSON (our application-layer format)?
        try:
            packet = json.loads(line)
            vitals = packet["vitals"]
            check("1. Packet format", True, "Valid JSON with header and vitals")
        except (json.JSONDecodeError, KeyError, TypeError):
            check("1. Packet format", False, "Not a valid packet")
            return reject("Malformed packet")

        # Check 2: is the device registered to an admitted patient?
        dev_id = packet.get("device_id")
        record["device_id"] = dev_id
        dev = devices.get(dev_id)
        if not check("2. Device registered", dev is not None,
                     f"{dev_id} belongs to {dev['patient']}" if dev else f"{dev_id} is not registered"):
            return reject("Unknown device ID", fatal=True)

        # Check 3: HMAC-SHA256 signature (authenticity + integrity)
        if not check("3. HMAC signature", verify_packet(packet, dev["key"]),
                     "Signature matches this device's secret key"
                     if verify_packet(packet, dev["key"]) else "Signature does not match"):
            return reject("HMAC signature invalid (tampered or wrong key)", fatal=True)

        # Check 4: timestamp freshness (replay window)
        age = arrived - float(packet.get("timestamp", 0))
        if not check("4. Timestamp fresh", abs(age) <= config.MAX_PACKET_AGE_SECONDS,
                     f"Sent {age * 1000:.1f} ms ago (limit {config.MAX_PACKET_AGE_SECONDS} s)"):
            return reject(f"Stale timestamp ({age:.0f}s old) - possible replay")

        # Check 5: not a duplicate, sequence moves forward
        seq = int(packet.get("seq", -1))
        dup = packet["hmac"] in dev["recent_macs"]
        order_ok = seq > last_seq.get(dev_id, -1)
        if not check("5. Not a replay", not dup and order_ok,
                     f"Sequence #{seq} is new" if (not dup and order_ok) else f"Sequence #{seq} already seen"):
            return reject(f"Duplicate packet #{seq} - replay blocked")

        # Check 6: physically plausible values (input error protection)
        bad = [k for k, (lo, hi) in config.PLAUSIBLE.items()
               if not isinstance(vitals.get(k), (int, float)) or not lo <= vitals[k] <= hi]
        if not check("6. Values plausible", not bad,
                     "All six vitals within physical limits" if not bad else f"Impossible: {', '.join(bad)}"):
            return reject("Impossible vital values")

        # ---------- ACCEPTED ----------
        v = {k: vitals[k] for k in db.VITAL_KEYS}
        status, flags = evaluate(v, dev["limits"])
        prev = dev["status"]
        dev.update({"vitals": v, "status": status, "flags": flags, "last_seen": arrived,
                    "ip": ip, "port": port, "tls": tls_info,
                    "latency_ms": round(max(age, 0) * 1000, 1)})
        dev["packets"] += 1
        dev["recent_macs"].append(packet["hmac"])
        dev["history"].append({"t": arrived, **v})
        last_seq[dev_id] = seq
        stats["packets_accepted"] += 1
        if status != "normal" and status != prev:
            _raise_alert(dev, status, flags, v)
        record["result"] = f"Accepted, patient status: {status}"
        inspector.appendleft(record)

    db.save_reading(dev_id, v, status, ip)
    return {"status": "ok", "seq": seq, "patient_status": status}, dev_id


# =================================================================
# One thread per connected bedside monitor
# =================================================================
def handle_connection(conn, addr):
    ip, port = addr
    cipher = conn.cipher()
    tls_info = f"{conn.version()}, {cipher[0]}" if cipher else "TLS"
    with lock:
        stats["connections_total"] += 1
        _log("CONNECTED", None, f"{ip}:{port}", f"TCP + TLS handshake complete ({tls_info})")
    print(f"[+] {ip}:{port} connected ({tls_info})")

    identified = None
    last_seq = {}
    reader = conn.makefile("r", encoding="utf-8")
    try:
        for line in reader:                      # blocks until a full line arrives
            ack, dev_id = receive_packet(line, ip, port, tls_info, last_seq)
            if dev_id and dev_id != identified:
                identified = dev_id
                with lock:
                    _log("IDENTIFIED", dev_id, f"{ip}:{port}",
                         f"Authenticated as monitor of {devices[dev_id]['patient']}")
            conn.sendall(encode_message(ack))    # ACK back to the device
    except (ConnectionError, ssl.SSLError, OSError):
        pass
    finally:
        with lock:
            _log("DISCONNECTED", identified, f"{ip}:{port}", "Connection closed")
        print(f"[-] {identified or ip} disconnected")
        conn.close()


def start_listener():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(config.CERT_FILE, config.KEY_FILE)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)       # IPv4 + TCP
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((config.SERVER_BIND_HOST, config.DEVICE_PORT))
    sock.listen(50)
    print(f"[*] Waiting for bedside monitors on TCP port {config.DEVICE_PORT} (TLS)")

    def accept_loop():
        while True:
            raw, addr = sock.accept()
            try:
                conn = context.wrap_socket(raw, server_side=True)
            except (ssl.SSLError, OSError):
                with lock:
                    reason = "TLS handshake failed (unencrypted client)"
                    stats["packets_rejected"] += 1
                    stats["reject_reasons"][reason] = stats["reject_reasons"].get(reason, 0) + 1
                    _log("REJECTED", None, f"{addr[0]}:{addr[1]}", reason)
                raw.close()
                continue
            threading.Thread(target=handle_connection, args=(conn, addr), daemon=True).start()

    threading.Thread(target=accept_loop, daemon=True).start()


# =================================================================
# Read-only views for the web pages
# =================================================================
def public(dev):
    online = bool(dev["last_seen"] and time.time() - dev["last_seen"] < config.DEVICE_TIMEOUT_SECONDS)
    return {k: dev[k] for k in ("device_id", "patient_id", "patient_code", "patient", "age", "gender",
                                "ward", "bed", "doctor", "vitals", "ip", "port", "tls", "packets",
                                "latency_ms", "limits")} | {
        "status": dev["status"] if online else "offline",
        "flags": dev["flags"] if online else [],
        "online": online,
        "last_seen": datetime.fromtimestamp(dev["last_seen"]).strftime("%H:%M:%S") if dev["last_seen"] else None,
    }


def uptime():
    s = int(time.time() - SERVER_START)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
