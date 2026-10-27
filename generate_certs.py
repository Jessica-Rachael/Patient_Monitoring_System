"""
generate_certs.py
-----------------
Run ONCE before starting the server:
    python generate_certs.py

Creates a self-signed TLS certificate (certs/server.crt) and its private
key (certs/server.key). The server uses them to encrypt traffic; devices
use server.crt to verify they are talking to the real server.
"""

import datetime
import ipaddress
import os
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import config


def local_ip_addresses():
    """Collect this computer's IP addresses so they can go inside the cert."""
    ips = {"127.0.0.1"}
    try:
        # Trick: "connecting" a UDP socket sends nothing but reveals the LAN IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ips)


def main():
    os.makedirs("certs", exist_ok=True)

    print("[*] Generating 2048-bit RSA private key ...")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    ips = local_ip_addresses()
    print(f"[*] Certificate will be valid for: localhost, {', '.join(ips)}")

    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Patient Monitoring Mini Project"),
        x509.NameAttribute(NameOID.COMMON_NAME, "monitoring-server"),
    ])

    san = [x509.DNSName("localhost"), x509.DNSName("monitoring-server")]
    san += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)                      # self-signed: issuer = subject
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    with open(config.KEY_FILE, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(config.CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"[+] Saved {config.CERT_FILE}")
    print(f"[+] Saved {config.KEY_FILE}")
    print("[+] Done. Copy certs/server.crt to any other laptop that runs patient devices.")


if __name__ == "__main__":
    main()
