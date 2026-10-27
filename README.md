# IP-Based Patient Monitoring System (version 2)

A doctor or nurse types a patient's vital signs into a **Bedside Monitor**
app. That app sends them across the IP network, inside an encrypted TLS
connection and with a signature on every packet, to a **Central Server**.
The server checks each packet, stores it, raises alerts, and shows
everything live on a hospital website for staff and patients.

Nothing is pre-loaded in the code: no users, no patients, no vital values.

## Folder structure

```
patient-monitoring-system/
├── server.py              CENTRAL SERVER: website (HTTPS 8443) + starts the receiver
├── monitor_core.py        NETWORK RECEIVER: TCP/TLS port 9000, checks every packet
├── bedside_monitor.py     DEVICE SIDE: staff enter vitals, it transmits them
├── secure_protocol.py     Packet format + HMAC-SHA256 signing/verifying
├── database.py            SQLite storage (users, patients, readings, alerts)
├── generate_certs.py      Creates the TLS certificate (run once)
├── security_test.py       Tries 6 network attacks to prove the security works
├── config.py              Ports and technical settings only
├── requirements.txt
├── HOW_IT_WORKS.md        The computer-networks explanation for your report/viva
├── templates/             Website pages
├── bedside_templates/     Bedside Monitor page
├── static/css, static/js  Styling and page scripts
├── certs/                 server.crt + server.key appear here
└── data/                  hospital.db appears here
```

## One-time setup in VS Code

1. Install Python 3.10+ (tick "Add Python to PATH") and VS Code with the Python extension.
2. File > Open Folder > `patient-monitoring-system`, then Terminal > New Terminal.
3. Run:
   ```
   python -m venv venv
   venv\Scripts\activate            (macOS/Linux: source venv/bin/activate)
   pip install -r requirements.txt
   python generate_certs.py
   ```

If you used version 1 before, delete the old `data` folder contents first.

## Every time you run it: two terminals

Terminal 1 (central server):
```
venv\Scripts\activate
python server.py
```
Terminal 2 (bedside monitor), open with the + button:
```
venv\Scripts\activate
python bedside_monitor.py
```

## Using it, step by step

1. Open **https://localhost:8443**. Accept the certificate warning
   (Advanced > Proceed). The first visit asks you to create the
   **administrator** account.
2. As admin, open **Staff** and create a **doctor** (and nurses if you like).
3. Sign out, sign in as the doctor, and click **Register patient**. Fill in
   the details, the alert limits and a login for the patient.
4. The next page shows the **Server IP, Device ID and Device key** for that patient.
5. Open **http://localhost:7000** (the Bedside Monitor). Enter the server IP,
   Device ID and Device key, and click **Connect**.
6. Type the heart rate, SpO2, temperature, respiration and blood pressure,
   click **Apply values**, then **Start transmitting**.
7. Watch the **Ward** page: the tile goes live. Change a value (for example
   heart rate 140) and press Apply values: an alert appears within a second.
8. The **Network** page shows every packet, the 6 checks the server ran on it,
   and the decrypted contents.
9. Sign in as the patient in another browser (or a private window). They
   see only their own readings.
10. Optional attack demo (copy the Device key from the patient page):
    ```
    python security_test.py --id DEV-0001 --key <device key>
    ```

## Two laptops on the same Wi-Fi (the real network demo)

| Laptop A (server) | Laptop B (bedside) |
|---|---|
| `python generate_certs.py` | copy the whole project folder from A, including `certs/server.crt` |
| `python server.py` | `python bedside_monitor.py` |
| note the "Bedside monitors use" IP printed at startup | open http://localhost:7000 and enter Laptop A's IP |
| allow Python through the firewall (Private network) | |

Anyone else on the Wi-Fi can open `https://<Laptop A IP>:8443` to see the website.
If Windows Firewall blocks it, allow inbound TCP 9000 and 8443.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Activate the venv, then `pip install -r requirements.txt` |
| `FileNotFoundError: certs/server.crt` | `python generate_certs.py` |
| `Address already in use` | An old server is still running; close that terminal |
| Bedside says "Unknown device ID" | Patient not registered, or discharged; check the ID |
| Bedside says "HMAC signature invalid" | The Device key was typed wrong or a new key was issued |
| Bedside says "Cannot reach ..." | Wrong IP, server not running, or firewall |
| Bedside says "certificate not trusted" | Copy the server's `certs/server.crt` to the bedside laptop |
| Old errors about missing columns | Delete `data/hospital.db` (from version 1) and restart |
