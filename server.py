"""
server.py
---------
CENTRAL MONITORING SERVER.  Run:  python server.py

Starts two network services:
  * TCP port 9000 (TLS)  - bedside monitors send vital signs here   (monitor_core.py)
  * HTTPS port 8443      - the hospital website for staff and patients (this file)

Nothing is pre-loaded. On the first visit the website asks you to create the
admin account. Admin creates doctor/nurse accounts, doctors register
patients, and vital signs arrive from the Bedside Monitor app.
"""

import csv
import io
import socket
from functools import wraps

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)

import config
import database as db
import monitor_core as core

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

STAFF = ("admin", "doctor", "nurse")
REGISTRARS = ("admin", "doctor")          # who may register / discharge patients


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


SERVER_IP = lan_ip()


@app.context_processor
def inject_globals():
    return {"me": session.get("name"), "role": session.get("role"),
            "server_ip": SERVER_IP, "device_port": config.DEVICE_PORT,
            "bedside_port": config.BEDSIDE_PORT}


# ---------------------------------------------------------------
# Access control
# ---------------------------------------------------------------
def roles(*allowed):
    def deco(view):
        @wraps(view)
        def wrapper(*a, **kw):
            if "user_id" not in session:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "login required"}), 401
                return redirect(url_for("login"))
            if session["role"] not in allowed:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "not allowed"}), 403
                return redirect(url_for("home"))
            return view(*a, **kw)
        return wrapper
    return deco


def can_view(device_id):
    if session.get("role") in STAFF:
        return True
    return session.get("role") == "patient" and session.get("device_id") == device_id


@app.before_request
def first_run():
    """If there is no account yet, everything goes to the setup page."""
    if not db.has_users() and request.endpoint not in ("setup", "static"):
        return redirect(url_for("setup"))


# ---------------------------------------------------------------
# Form helpers
# ---------------------------------------------------------------
def read_limits(form):
    limits, errors = {}, []
    for k in db.VITAL_KEYS:
        try:
            lo, hi = float(form[f"{k}_low"]), float(form[f"{k}_high"])
        except (KeyError, ValueError):
            errors.append(f"{core.LABELS[k]}: enter numbers for both limits.")
            continue
        if lo >= hi:
            errors.append(f"{core.LABELS[k]}: the low limit must be below the high limit.")
        limits[k] = [lo, hi]
    return limits, errors


def check_password(pw, confirm):
    if len(pw) < 6:
        return "Password must be at least 6 characters."
    if pw != confirm:
        return "The two passwords do not match."
    return None


# ---------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------
@app.route("/setup", methods=["GET", "POST"])
def setup():
    if db.has_users():
        return redirect(url_for("login"))
    errors = []
    if request.method == "POST":
        f = request.form
        if not f.get("full_name", "").strip() or not f.get("username", "").strip():
            errors.append("Enter your name and a username.")
        err = check_password(f.get("password", ""), f.get("confirm", ""))
        if err:
            errors.append(err)
        if not errors:
            db.create_user(f["username"], f["password"], "admin", f["full_name"])
            flash("Admin account created. Sign in to continue.")
            return redirect(url_for("login"))
    return render_template("setup.html", errors=errors)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = db.authenticate(request.form.get("username", ""), request.form.get("password", ""))
        if user:
            session.clear()
            session.update(user_id=user["id"], role=user["role"], name=user["full_name"])
            if user["role"] == "patient":
                p = db.get_patient(user["patient_id"])
                session["device_id"] = p["device_id"]
            return redirect(url_for("home"))
        error = "Username or password is incorrect."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@roles(*STAFF, "patient")
def home():
    if session["role"] == "patient":
        return redirect(url_for("portal"))
    return render_template("dashboard.html", page="ward")


@app.route("/staff", methods=["GET", "POST"])
@roles("admin")
def staff():
    errors = []
    if request.method == "POST":
        f = request.form
        if f.get("role") not in ("doctor", "nurse"):
            errors.append("Choose doctor or nurse.")
        if not f.get("full_name", "").strip() or not f.get("username", "").strip():
            errors.append("Enter the name and a username.")
        elif db.username_taken(f["username"]):
            errors.append(f"The username {f['username']} is already taken.")
        err = check_password(f.get("password", ""), f.get("confirm", ""))
        if err:
            errors.append(err)
        if not errors:
            db.create_user(f["username"], f["password"], f["role"], f["full_name"])
            flash(f"{f['role'].title()} account created for {f['full_name']}.")
            return redirect(url_for("staff"))
    return render_template("staff.html", page="staff", staff=db.list_staff(), errors=errors)


@app.route("/staff/<int:user_id>/delete", methods=["POST"])
@roles("admin")
def staff_delete(user_id):
    db.delete_user(user_id)
    flash("Account removed.")
    return redirect(url_for("staff"))


# ---------------------------------------------------------------
# Patients
# ---------------------------------------------------------------
@app.route("/patients")
@roles(*STAFF)
def patients():
    return render_template("patients.html", page="patients", patients=db.list_patients())


@app.route("/patients/new", methods=["GET", "POST"])
@roles(*REGISTRARS)
def patient_new():
    errors, form = [], request.form
    if request.method == "POST":
        data = {k: form.get(k, "").strip() for k in
                ("full_name", "age", "gender", "phone", "ward", "bed", "diagnosis", "emergency_contact")}
        if not data["full_name"]:
            errors.append("Enter the patient's full name.")
        if not data["age"].isdigit() or not 0 < int(data["age"]) < 130:
            errors.append("Enter a valid age.")
        if not data["ward"] or not data["bed"]:
            errors.append("Enter the ward and bed number.")
        limits, lim_errors = read_limits(form)
        errors += lim_errors
        username = form.get("username", "").strip()
        if not username:
            errors.append("Create a login username for the patient.")
        elif db.username_taken(username):
            errors.append(f"The username {username} is already taken.")
        err = check_password(form.get("password", ""), form.get("confirm", ""))
        if err:
            errors.append(err)

        if not errors:
            data["age"] = int(data["age"])
            p = db.create_patient(data, limits, session["name"])
            db.create_user(username, form["password"], "patient", p["full_name"], p["id"])
            core.load_patient(p)
            return redirect(url_for("patient_created", pid=p["id"]))
    return render_template("patient_new.html", page="patients", errors=errors, form=form,
                           defaults=config.DEFAULT_LIMITS, labels=core.LABELS, units=core.UNITS)


@app.route("/patients/<int:pid>/created")
@roles(*REGISTRARS)
def patient_created(pid):
    p = db.get_patient(pid) or abort(404)
    return render_template("patient_created.html", page="patients", p=p, username=db.patient_username(pid))


@app.route("/patient/<device_id>")
@roles(*STAFF)
def patient_detail(device_id):
    p = db.get_patient_by_device(device_id) or abort(404)
    return render_template("patient.html", page="patients", p=p, username=db.patient_username(p["id"]),
                           labels=core.LABELS, units=core.UNITS, portal=False)


@app.route("/patient/<device_id>/limits", methods=["POST"])
@roles(*REGISTRARS)
def patient_limits(device_id):
    p = db.get_patient_by_device(device_id) or abort(404)
    limits, errors = read_limits(request.form)
    if errors:
        for e in errors:
            flash(e, "error")
    else:
        db.set_limits(p["id"], limits)
        core.load_patient(db.get_patient(p["id"]))
        flash("Alert limits saved. New readings are checked against them.")
    return redirect(url_for("patient_detail", device_id=device_id))


@app.route("/patient/<device_id>/newkey", methods=["POST"])
@roles(*REGISTRARS)
def patient_newkey(device_id):
    p = db.get_patient_by_device(device_id) or abort(404)
    db.regenerate_key(p["id"])
    core.load_patient(db.get_patient(p["id"]))
    flash("A new device key was issued. The old key stops working immediately.")
    return redirect(url_for("patient_detail", device_id=device_id))


@app.route("/patient/<device_id>/discharge", methods=["POST"])
@roles(*REGISTRARS)
def patient_discharge(device_id):
    p = db.get_patient_by_device(device_id) or abort(404)
    if p["status"] == "admitted":
        db.set_status(p["id"], "discharged")
        core.unload_patient(device_id)
        flash(f"{p['full_name']} was discharged. Their device can no longer send data.")
    else:
        db.set_status(p["id"], "admitted")
        core.load_patient(db.get_patient(p["id"]))
        flash(f"{p['full_name']} was readmitted.")
    return redirect(url_for("patients"))


@app.route("/me")
@roles("patient")
def portal():
    p = db.get_patient_by_device(session["device_id"])
    return render_template("patient.html", page="me", p=p, username=None,
                           labels=core.LABELS, units=core.UNITS, portal=True)


@app.route("/network")
@roles(*STAFF)
def network():
    return render_template("network.html", page="network")


# ---------------------------------------------------------------
# JSON APIs (the pages call these every second)
# ---------------------------------------------------------------
@app.route("/api/snapshot")
@roles(*STAFF)
def api_snapshot():
    with core.lock:
        devs = [core.public(d) for d in core.devices.values()]
        al = list(core.alerts)[:25]
        unack = sum(1 for a in core.alerts if not a["acknowledged"])
    return jsonify({"devices": devs, "alerts": al, "summary": {
        "online": sum(d["online"] for d in devs), "total": len(devs),
        "critical": sum(d["status"] == "critical" for d in devs),
        "warning": sum(d["status"] == "warning" for d in devs), "unacknowledged": unack}})


@app.route("/api/patient/<device_id>")
@roles(*STAFF, "patient")
def api_patient(device_id):
    if not can_view(device_id):
        return jsonify({"error": "not allowed"}), 403
    with core.lock:
        dev = core.devices.get(device_id)
        if not dev:
            return jsonify({"error": "patient not admitted"}), 404
        return jsonify({"device": core.public(dev), "history": list(dev["history"]),
                        "alerts": [a for a in core.alerts if a["device_id"] == device_id][:15]})


@app.route("/api/patient/<device_id>/export.csv")
@roles(*STAFF, "patient")
def api_export(device_id):
    if not can_view(device_id):
        abort(403)
    rows = db.all_readings(device_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["received_at", "source_ip", *db.VITAL_KEYS, "status"])
    for r in rows:
        w.writerow([r["received_at"], r["source_ip"], *[r[k] for k in db.VITAL_KEYS], r["status"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={device_id}_readings.csv"})


@app.route("/api/alerts/<int:alert_id>/ack", methods=["POST"])
@roles(*STAFF)
def api_ack(alert_id):
    with core.lock:
        for a in core.alerts:
            if a["id"] == alert_id:
                a["acknowledged"], a["ack_by"] = True, session["name"]
    return jsonify({"ok": True})


@app.route("/api/network")
@roles(*STAFF)
def api_network():
    with core.lock:
        s = core.stats
        total = s["packets_accepted"] + s["packets_rejected"]
        return jsonify({
            "stats": {**s, "uptime": core.uptime(),
                      "acceptance_rate": round(100 * s["packets_accepted"] / total, 1) if total else None},
            "connections": [core.public(d) for d in core.devices.values()],
            "log": list(core.network_log)[:60],
            "inspector": list(core.inspector)[:12],
        })


if __name__ == "__main__":
    db.init()
    core.load_all()
    core.start_listener()
    scheme = "https" if config.DASHBOARD_HTTPS else "http"
    print("=" * 64)
    print("  CENTRAL MONITORING SERVER")
    print(f"  Website on this PC   : {scheme}://localhost:{config.DASHBOARD_PORT}")
    print(f"  Website on the LAN   : {scheme}://{SERVER_IP}:{config.DASHBOARD_PORT}")
    print(f"  Bedside monitors use : server IP {SERVER_IP}, port {config.DEVICE_PORT}")
    print("=" * 64)
    app.run(host=config.SERVER_BIND_HOST, port=config.DASHBOARD_PORT, threaded=True,
            ssl_context=(config.CERT_FILE, config.KEY_FILE) if config.DASHBOARD_HTTPS else None)
