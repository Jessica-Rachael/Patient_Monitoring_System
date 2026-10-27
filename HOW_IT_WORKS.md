# How the system works: the computer networks part

## 1. The big picture

```
 BEDSIDE LAPTOP                         SERVER LAPTOP                       ANY LAPTOP / PHONE
 ┌──────────────────────┐   TCP 9000    ┌──────────────────────────┐ HTTPS 8443 ┌─────────────────┐
 │ Bedside Monitor app  │ ────────────► │ Receiver (monitor_core)  │ ◄───────── │ Browser:        │
 │ nurse types vitals   │  TLS tunnel   │  checks, stores, alerts  │   TLS      │ ward, patients, │
 │ builds signed packet │ ◄──────────── │ Website (server.py)      │ ─────────► │ network pages   │
 └──────────────────────┘     ACK       └──────────────────────────┘   JSON     └─────────────────┘
```

There are two separate network conversations:
* **Device to server**: a custom application protocol we designed, over TCP, inside TLS.
* **Browser to server**: HTTP over TLS (HTTPS). The page asks the server for fresh JSON every second.

## 2. The layers used (TCP/IP model)

| Layer | What is used | Where in the code |
|---|---|---|
| Application | Our monitoring protocol (JSON packets + ACK), and HTTP for the website | `secure_protocol.py`, `server.py` |
| Security (between application and transport) | TLS 1.2/1.3: certificate, key exchange, AES-GCM encryption | `ssl` module in `monitor_core.py`, `bedside_monitor.py` |
| Transport | TCP: reliable, ordered, connection-oriented; ports 9000, 8443, 7000 | `socket.SOCK_STREAM` |
| Internet | IPv4 addressing; the server binds `0.0.0.0` so every interface accepts | `socket.AF_INET`, `SERVER_BIND_HOST` |
| Link / physical | Wi-Fi or Ethernet of your LAN (handled by the OS) | - |

## 3. What happens when a nurse presses "Start transmitting"

1. **Socket creation.** The bedside app creates a TCP socket and calls
   `connect(server_ip, 9000)`. The OS picks a random source port (for example 54112).
2. **TCP three-way handshake.** SYN, SYN-ACK, ACK. The connection is now open.
   The server's `accept()` returns a new socket for this bedside monitor, and a new
   thread serves it, so many monitors work at the same time.
3. **TLS handshake.** The server presents its certificate (`server.crt`).
   The bedside app checks it against its own copy, so it cannot be fooled by a fake
   server. Both sides agree on session keys (ECDHE). From now on everything is
   encrypted with AES-256-GCM. The server records the TLS version and cipher.
4. **Building a packet** (`secure_protocol.build_packet`):
   ```json
   {"device_id":"DEV-0001","seq":16,"timestamp":1790269498.64,"source":"bedside",
    "vitals":{"heart_rate":87,"spo2":97,"temperature":37.2,"resp_rate":16,"bp_sys":123,"bp_dia":80},
    "hmac":"90adb9c3..."}
   ```
   * `seq` counts up by one per packet.
   * `timestamp` is when it was sent.
   * `hmac` = HMAC-SHA256(device key, all other fields). Only someone who knows
     this patient's device key can produce it.
   * The packet ends with a newline. That newline is our **framing**: TCP is a byte
     stream with no message boundaries, so the receiver reads one line = one packet.
5. **Transmission.** The packet is encrypted by TLS, split into TCP segments, put in
   IP packets and sent over the LAN.
6. **Reception** (`monitor_core.receive_packet`). The server decrypts it and runs 6 checks:
   | Check | Protects against |
   |---|---|
   | 1. Valid JSON packet | garbage / malformed data |
   | 2. Device ID registered to an admitted patient | unknown or discharged devices |
   | 3. HMAC signature correct | forged packets, altered values (integrity + authentication) |
   | 4. Timestamp within 30 s | old captured packets replayed later |
   | 5. Sequence number new, signature not seen before | immediate replay attacks |
   | 6. Values physically possible | typing mistakes (e.g. heart rate 900) |
7. **Processing.** The reading is compared with the limits the doctor set for this
   patient: normal, warning or critical. On a change, an alert is raised. The reading
   is stored in SQLite with the sender's IP address.
8. **Acknowledgement.** The server writes back
   `{"status":"ok","seq":16,"patient_status":"normal"}`, or
   `{"status":"rejected","reason":...}`. The bedside app shows it. This is an
   application-level ACK on top of TCP's own ACKs: TCP confirms the bytes arrived,
   our ACK confirms the reading was accepted.
9. **Display.** Every browser page calls `/api/snapshot` or `/api/patient/...`
   over HTTPS every second (polling). The server answers with JSON, and JavaScript
   updates the numbers, the trends and the ECG trace.
10. **Monitoring the link.** Latency = arrival time minus packet timestamp. If no
    packet arrives for 6 s, the patient shows "No signal". If the connection drops,
    the bedside app reconnects automatically every 3 s.

## 4. Security summary (CIA triad)

| Goal | Mechanism |
|---|---|
| Confidentiality | TLS encryption: a packet sniffer (e.g. Wireshark) sees only random bytes |
| Integrity | HMAC-SHA256: changing even one digit makes the signature fail |
| Authentication | Per-device secret key (HMAC) + server certificate (TLS) + user passwords (hashed) for the website |
| Availability / robustness | Threaded server, auto-reconnect, timeouts, bad packets rejected without crashing |
| Replay protection | Timestamp window + sequence number + remembered signatures |
| Access control | Roles: admin, doctor, nurse, patient; a patient can only open their own data (HTTP 403 otherwise) |

## 5. Ports used

| Port | Protocol | Who listens | Purpose |
|---|---|---|---|
| 9000 | TCP + TLS | server | bedside monitors send vitals |
| 8443 | HTTPS | server | hospital website and JSON APIs |
| 7000 | HTTP (localhost only) | bedside laptop | the nurse's input page for the bedside monitor |

## 6. How to show it with Wireshark (good for the viva)

1. Run the server on laptop A and the bedside monitor on laptop B.
2. Start Wireshark on either laptop, filter: `tcp.port == 9000`.
3. You will see the TCP handshake (SYN, SYN-ACK, ACK), then the TLS
   "Client Hello" / "Server Hello", then "Application Data" records.
4. Try to read the heart rate in those packets: you cannot, because it is encrypted.
   On the Network page of the website, the same packet is shown decrypted, with
   the result of each check.
