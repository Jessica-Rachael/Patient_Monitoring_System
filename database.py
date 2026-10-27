"""
database.py
-----------
Everything stored on disk in SQLite (data/hospital.db). The file starts
EMPTY - every row is created from the website.

  users     - login accounts: admin, doctor, nurse, patient
  patients  - patient records; each patient gets its own device ID and
              secret device key when a doctor registers them
  vitals    - every reading the server accepted from the network
  alerts    - every clinical alert
"""

import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

import config

_lock = threading.RLock()
os.makedirs(os.path.dirname(config.DATABASE_FILE), exist_ok=True)
_conn = sqlite3.connect(config.DATABASE_FILE, check_same_thread=False)
_conn.row_factory = sqlite3.Row

VITAL_KEYS = ["heart_rate", "spo2", "temperature", "resp_rate", "bp_sys", "bp_dia"]


def now():
    return datetime.now().isoformat(timespec="seconds")


def query(sql, args=(), one=False):
    with _lock:
        rows = [dict(r) for r in _conn.execute(sql, args).fetchall()]
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def init():
    with _lock:
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,          -- never the plain password
            role TEXT NOT NULL,                   -- admin | doctor | nurse | patient
            full_name TEXT NOT NULL,
            patient_id INTEGER,                   -- only for patient accounts
            created_at TEXT);
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_code TEXT UNIQUE,
            full_name TEXT NOT NULL,
            age INTEGER, gender TEXT, phone TEXT,
            ward TEXT, bed TEXT, diagnosis TEXT, emergency_contact TEXT,
            doctor TEXT,
            device_id TEXT UNIQUE,
            device_key TEXT,
            limits TEXT,                          -- JSON: alert limits set by the doctor
            status TEXT DEFAULT 'admitted',       -- admitted | discharged
            created_at TEXT);
        CREATE TABLE IF NOT EXISTS vitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT, received_at TEXT, source_ip TEXT,
            heart_rate REAL, spo2 REAL, temperature REAL, resp_rate REAL,
            bp_sys REAL, bp_dia REAL, status TEXT);
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT, raised_at TEXT, level TEXT, message TEXT);
        CREATE INDEX IF NOT EXISTS idx_vitals_dev ON vitals(device_id, id);
        """)
        _conn.commit()


# ---------------- users ----------------
def has_users():
    return query("SELECT id FROM users LIMIT 1", one=True) is not None


def create_user(username, password, role, full_name, patient_id=None):
    return execute(
        "INSERT INTO users (username, password_hash, role, full_name, patient_id, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (username.strip().lower(), generate_password_hash(password), role, full_name.strip(),
         patient_id, now()))


def username_taken(username):
    return query("SELECT id FROM users WHERE username=?", (username.strip().lower(),), one=True) is not None


def authenticate(username, password):
    user = query("SELECT * FROM users WHERE username=?", (username.strip().lower(),), one=True)
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def list_staff():
    return query("SELECT id, username, role, full_name, created_at FROM users"
                 " WHERE role != 'patient' ORDER BY id")


def delete_user(user_id):
    execute("DELETE FROM users WHERE id=? AND role != 'admin'", (user_id,))


# ---------------- patients ----------------
def _decode(p):
    if p:
        p["limits"] = json.loads(p["limits"]) if p.get("limits") else {}
    return p


def create_patient(data, limits, doctor):
    pid = execute(
        "INSERT INTO patients (full_name, age, gender, phone, ward, bed, diagnosis, emergency_contact,"
        " doctor, device_key, limits, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["full_name"], data["age"], data["gender"], data["phone"], data["ward"], data["bed"],
         data["diagnosis"], data["emergency_contact"], doctor,
         secrets.token_hex(16),                     # 128-bit random secret for HMAC signing
         json.dumps(limits), now()))
    execute("UPDATE patients SET patient_code=?, device_id=? WHERE id=?",
            (f"PT-{pid:04d}", f"DEV-{pid:04d}", pid))
    return get_patient(pid)


def get_patient(pid):
    return _decode(query("SELECT * FROM patients WHERE id=?", (pid,), one=True))


def get_patient_by_device(device_id):
    return _decode(query("SELECT * FROM patients WHERE device_id=?", (device_id,), one=True))


def list_patients(status=None):
    sql = "SELECT * FROM patients" + (" WHERE status=?" if status else "") + " ORDER BY status, id"
    return [_decode(p) for p in query(sql, (status,) if status else ())]


def set_limits(pid, limits):
    execute("UPDATE patients SET limits=? WHERE id=?", (json.dumps(limits), pid))


def set_status(pid, status):
    execute("UPDATE patients SET status=? WHERE id=?", (status, pid))


def regenerate_key(pid):
    key = secrets.token_hex(16)
    execute("UPDATE patients SET device_key=? WHERE id=?", (key, pid))
    return key


def patient_username(pid):
    row = query("SELECT username FROM users WHERE patient_id=?", (pid,), one=True)
    return row["username"] if row else None


# ---------------- vitals & alerts ----------------
def save_reading(device_id, v, status, ip):
    execute(
        "INSERT INTO vitals (device_id, received_at, source_ip, heart_rate, spo2, temperature,"
        " resp_rate, bp_sys, bp_dia, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (device_id, now(), ip, v["heart_rate"], v["spo2"], v["temperature"],
         v["resp_rate"], v["bp_sys"], v["bp_dia"], status))


def recent_readings(device_id, limit=300):
    rows = query("SELECT * FROM vitals WHERE device_id=? ORDER BY id DESC LIMIT ?", (device_id, limit))
    return list(reversed(rows))


def all_readings(device_id):
    return query("SELECT received_at, source_ip, heart_rate, spo2, temperature, resp_rate, bp_sys,"
                 " bp_dia, status FROM vitals WHERE device_id=? ORDER BY id", (device_id,))


def save_alert(device_id, level, message):
    execute("INSERT INTO alerts (device_id, raised_at, level, message) VALUES (?,?,?,?)",
            (device_id, now(), level, message))
