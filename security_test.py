"""
security_test.py
----------------
Proves the server blocks common network attacks. Server must be running.

    python security_test.py --id DEV-0001 --key <device key from the website>
    python security_test.py --id DEV-0001 --key <key> --host 192.168.1.20

Attacks tried:
  1. Plain TCP without TLS          (eavesdropping)      -> refused
  2. Unregistered device ID         (impersonation)      -> rejected
  3. Wrong secret key               (forged signature)   -> rejected
  4. Value changed after signing    (tampering)          -> rejected
  5. Same packet sent twice         (replay)             -> rejected
  6. Five-minute-old timestamp      (delayed replay)     -> rejected
"""

import argparse
import json
import socket
import ssl
import time

import config
from secure_protocol import build_packet, sign_packet

VITALS = {"heart_rate": 80, "spo2": 98, "temperature": 36.9, "resp_rate": 16, "bp_sys": 120, "bp_dia": 78}


def send(tls, reader, data):
    tls.sendall(data)
    return json.loads(reader.readline() or "{}")


def show(title, reply, expect_block=True):
    blocked = reply.get("status") != "ok"
    tag = "BLOCKED " if blocked else "ACCEPTED"
    good = blocked == expect_block
    print(f"  {tag}  {title}  {'(correct)' if good else '(UNEXPECTED)'}")
    if reply.get("reason"):
        print(f"            server said: {reply['reason']}")


def tls_conn(host, port):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(config.CERT_FILE)
    ctx.check_hostname = False
    raw = socket.create_connection((host, port))
    return ctx.wrap_socket(raw, server_hostname=host)


def main(host, port, dev, key):
    print(f"\nSecurity tests against {host}:{port} using {dev}\n")
    try:
        with socket.create_connection((host, port), timeout=3) as s:
            s.sendall(build_packet(dev, 0, VITALS, key))
            s.settimeout(3)
            data = s.recv(1024)
            print("  ACCEPTED  Plain TCP (UNEXPECTED)" if data.startswith(b"{")
                  else "  BLOCKED   Plain TCP without TLS  (correct)")
    except (OSError, socket.timeout):
        print("  BLOCKED   Plain TCP without TLS  (correct)")

    for title, packet in [("Unregistered device DEV-9999", build_packet("DEV-9999", 0, VITALS, "guess")),
                          ("Forged signature (wrong key)", build_packet(dev, 0, VITALS, "wrong-key"))]:
        with tls_conn(host, port) as t:
            show(title, send(t, t.makefile("r"), packet))

    with tls_conn(host, port) as t:
        r = t.makefile("r")
        p = json.loads(build_packet(dev, 0, VITALS, key))
        p["vitals"]["heart_rate"] = 35
        show("Heart rate changed after signing", send(t, r, (json.dumps(p) + "\n").encode()))

        good = build_packet(dev, 10**6, VITALS, key)
        show("Genuine packet", send(t, r, good), expect_block=False)
        show("Replay of that same packet", send(t, r, good))

        old = {"device_id": dev, "seq": 10**6 + 1, "timestamp": time.time() - 300,
               "source": "attacker", "vitals": VITALS}
        sign_packet(old, key)
        show("Five-minute-old packet", send(t, r, (json.dumps(old) + "\n").encode()))
    print("\nOpen the Network page to see how each packet was checked.\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="Device ID shown on the website, e.g. DEV-0001")
    ap.add_argument("--key", required=True, help="Device key shown on the website")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=config.DEVICE_PORT)
    a = ap.parse_args()
    main(a.host, a.port, a.id.upper(), a.key)
