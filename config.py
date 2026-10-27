"""
config.py
---------
Technical settings only (ports, security, file paths).
There is NO patient data, NO user account and NO vital sign value in the
code. Accounts and patients are created on the website, and vital signs
are entered by staff in the Bedside Monitor app.
"""

# ---------------------------------------------------------------
# NETWORK
# ---------------------------------------------------------------
SERVER_BIND_HOST = "0.0.0.0"   # listen on every network card (LAN access)
DEVICE_PORT = 9000             # devices send vitals here (TCP + TLS)
DASHBOARD_PORT = 8443          # web dashboard (HTTPS)
DASHBOARD_HTTPS = True         # False = plain http (no browser warning)

# ---------------------------------------------------------------
# SECURITY
# ---------------------------------------------------------------
CERT_FILE = "certs/server.crt"
KEY_FILE = "certs/server.key"
FLASK_SECRET_KEY = "change-this-secret-for-your-project-2026"
MAX_PACKET_AGE_SECONDS = 30    # older packets are treated as replays

# ---------------------------------------------------------------
# MONITORING
# ---------------------------------------------------------------
DEVICE_TIMEOUT_SECONDS = 6     # no data for this long -> "No signal"
BEDSIDE_PORT = 7000            # port of the Bedside Monitor app (bedside_monitor.py)

# Standard adult ranges. They are only PRE-FILLED in the patient registration
# form; the doctor can change them for every patient.
DEFAULT_LIMITS = {
    "heart_rate":  (50, 120),
    "spo2":        (92, 100),
    "temperature": (35.5, 38.0),
    "resp_rate":   (10, 24),
    "bp_sys":      (90, 150),
    "bp_dia":      (55, 95),
}

# Values outside these are physically impossible and are refused as input errors
PLAUSIBLE = {
    "heart_rate":  (20, 250),
    "spo2":        (50, 100),
    "temperature": (30, 44),
    "resp_rate":   (4, 60),
    "bp_sys":      (50, 260),
    "bp_dia":      (25, 160),
}

DATABASE_FILE = "data/hospital.db"
