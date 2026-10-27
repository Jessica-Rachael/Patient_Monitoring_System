"""
bedside_monitor.py
------------------
THE DEVICE SIDE (the "sender"). Run it on any laptop in the same network:

    python bedside_monitor.py

then open  http://localhost:7000

A doctor or nurse:
  1. types the central server's IP address,
  2. types the Device ID and Device Key that the website gave when the
     patient was registered,
  3. enters heart rate, SpO2, temperature, respiration and BP,
  4. presses "Start transmitting".

From then on this program opens a TCP connection to the server, performs
the TLS handshake, and every second sends one signed packet containing
the values the staff member entered. The page shows each packet it sent
and the acknowledgement the server returned.

"Natural variation" (optional) adds the tiny beat-to-beat wobble a real
monitor shows, around the values the staff entered.
"""

import json
import random
import socket
import ssl
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import config
from secure_protocol import build_packet

app = Flask(__name__, template_folder="bedside_templates")
monitors = {}            # device_id -> Monitor
monitors_lock = threading.Lock()

JITTER = {"heart_rate": 2, "spo2": 0.6, "temperature": 0.05, "resp_rate": 0.6, "bp_sys": 2, "bp_dia": 1.5}


class Monitor:
    """One bedside monitor = one TLS connection to the central server."""

    def __init__(self, host, port, device_id, key, interval):
        self.host, self.port, self.device_id, self.key = host, port, device_id, key
        self.interval = interval
        self.values = None          # set by the staff member on the page
        self.variation = True
        self.transmitting = False
        self.state = "Connecting"
        self.error = None
        self.tls = None
        self.local = None
        self.seq = 0
        self.sent = self.acked = self.rejected = 0
        self.last_packet = None
        self.last_ack = None
        self.log = []
        self.stop = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()

    def note(self, text):
        self.log.insert(0, f"{datetime.now().strftime('%H:%M:%S')}  {text}")
        del self.log[40:]

    def reading(self):
        v = dict(self.values)
        if self.variation:
            for k, j in JITTER.items():
                v[k] = v[k] + random.uniform(-j, j)
        return {
            "heart_rate": int(round(v["heart_rate"])), "spo2": int(round(min(100, v["spo2"]))),
            "temperature": round(v["temperature"], 1), "resp_rate": int(round(v["resp_rate"])),
            "bp_sys": int(round(v["bp_sys"])), "bp_dia": int(round(v["bp_dia"])),
        }

    def run(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_verify_locations(config.CERT_FILE)   # trust only OUR server's certificate
        ctx.check_hostname = False                    # LAN IPs change; cert itself is still verified
        ctx.verify_mode = ssl.CERT_REQUIRED

        while not self.stop.is_set():
            try:
                self.state = "Connecting"
                self.note(f"Opening TCP connection to {self.host}:{self.port}")
                with socket.create_connection((self.host, self.port), timeout=5) as raw:
                    self.local = "%s:%d" % raw.getsockname()
                    self.note(f"TCP connected from {self.local}; starting TLS handshake")
                    with ctx.wrap_socket(raw, server_hostname=self.host) as tls:
                        self.tls = f"{tls.version()}, {tls.cipher()[0]}"
                        self.state = "Connected"
                        self.error = None
                        self.note(f"TLS established ({self.tls}); server certificate verified")
                        reader = tls.makefile("r", encoding="utf-8")
                        while not self.stop.is_set():
                            if self.transmitting and self.values:
                                data = build_packet(self.device_id, self.seq, self.reading(), self.key, "bedside")
                                tls.sendall(data)
                                self.sent += 1
                                self.last_packet = json.loads(data)
                                ack = json.loads(reader.readline() or "{}")
                                self.last_ack = ack
                                if ack.get("status") == "ok":
                                    self.acked += 1
                                else:
                                    self.rejected += 1
                                    self.note(f"Server rejected packet #{self.seq}: {ack.get('reason')}")
                                    if ack.get("fatal"):
                                        self.transmitting = False
                                        self.error = ack.get("reason")
                                self.seq += 1
                            self.stop.wait(self.interval)
            except ssl.SSLCertVerificationError:
                self.state, self.error = "Error", "Server certificate not trusted. Copy certs/server.crt from the server laptop."
            except (ConnectionError, socket.timeout, OSError) as e:
                if self.stop.is_set():
                    break
                self.state, self.error = "Retrying", f"Cannot reach {self.host}:{self.port} ({e.__class__.__name__})"
            if not self.stop.is_set():
                self.note(self.error or "Connection lost")
                self.stop.wait(3)
        self.state = "Disconnected"

    def to_dict(self):
        return {k: getattr(self, k) for k in (
            "host", "port", "device_id", "interval", "values", "variation", "transmitting", "state",
            "error", "tls", "local", "sent", "acked", "rejected", "last_packet", "last_ack", "log")}


# ---------------- page + API used by the page ----------------
@app.route("/")
def index():
    return render_template("bedside.html", default_port=config.DEVICE_PORT,
                           plausible=config.PLAUSIBLE)


@app.route("/api/monitors")
def list_monitors():
    with monitors_lock:
        return jsonify([m.to_dict() for m in monitors.values()])


@app.route("/api/monitors", methods=["POST"])
def add_monitor():
    f = request.get_json()
    dev = f.get("device_id", "").strip().upper()
    key = f.get("key", "").strip()
    host = f.get("host", "").strip()
    if not dev or not key or not host:
        return jsonify({"error": "Enter the server IP, Device ID and Device Key."}), 400
    with monitors_lock:
        if dev in monitors:
            return jsonify({"error": f"{dev} is already connected on this page."}), 400
        monitors[dev] = Monitor(host, int(f.get("port") or config.DEVICE_PORT), dev, key,
                                max(0.5, float(f.get("interval") or 1)))
    return jsonify({"ok": True})


@app.route("/api/monitors/<dev>", methods=["PUT"])
def update_monitor(dev):
    m = monitors.get(dev)
    if not m:
        return jsonify({"error": "not found"}), 404
    f = request.get_json()
    if "values" in f:
        errors = []
        vals = {}
        for k, (lo, hi) in config.PLAUSIBLE.items():
            try:
                vals[k] = float(f["values"][k])
                if not lo <= vals[k] <= hi:
                    errors.append(f"{k.replace('_', ' ')} must be between {lo} and {hi}")
            except (KeyError, TypeError, ValueError):
                errors.append(f"enter a number for {k.replace('_', ' ')}")
        if errors:
            return jsonify({"error": "Check the values: " + "; ".join(errors)}), 400
        m.values = vals
        m.note("New values entered by staff: " + ", ".join(f"{k}={v:g}" for k, v in vals.items()))
    if "transmitting" in f:
        if f["transmitting"] and not m.values:
            return jsonify({"error": "Enter and apply the vital signs first."}), 400
        m.transmitting = bool(f["transmitting"])
        m.error = None if m.transmitting else m.error
        m.note("Transmission started" if m.transmitting else "Transmission paused")
    if "variation" in f:
        m.variation = bool(f["variation"])
    return jsonify({"ok": True})


@app.route("/api/monitors/<dev>", methods=["DELETE"])
def remove_monitor(dev):
    with monitors_lock:
        m = monitors.pop(dev, None)
    if m:
        m.stop.set()
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 60)
    print("  BEDSIDE MONITOR (device side)")
    print(f"  Open http://localhost:{config.BEDSIDE_PORT} in your browser")
    print("=" * 60)
    app.run(host="127.0.0.1", port=config.BEDSIDE_PORT, threaded=True)
