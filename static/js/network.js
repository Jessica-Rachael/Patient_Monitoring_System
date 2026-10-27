/* =============================================================
   network.js - live network view with packet inspector
   ============================================================= */

let openPacket = null;   // keeps the selected packet expanded between refreshes

function packetRow(p, i) {
  const ok = p.result.startsWith("Accepted");
  const key = `${p.from}-${p.raw.slice(-24)}`;
  let pretty = p.raw;
  try { pretty = JSON.stringify(JSON.parse(p.raw), null, 2); } catch (e) {}
  return `
  <details class="packet ${ok ? "ok" : "bad"}" data-key="${key}" ${openPacket === key ? "open" : ""}>
    <summary>
      <span class="ptime">${p.time}</span>
      <span class="tag ${ok ? "IDENTIFIED" : "REJECTED"}">${ok ? "accepted" : "rejected"}</span>
      <span><strong>${esc(p.device_id || "unknown")}</strong> from ${esc(p.from)}</span>
      <span class="muted small">${p.bytes} bytes</span>
    </summary>
    <div class="packet-body">
      <div>
        <h3>Checks the server ran</h3>
        <ol class="checks">${p.checks.map(c => `
          <li class="${c.ok ? "pass" : "fail"}"><span class="mark">${c.ok ? "Pass" : "Fail"}</span>
            <div><strong>${esc(c.name)}</strong><div class="small muted">${esc(c.detail)}</div></div></li>`).join("")}
        </ol>
        <p class="small"><strong>Result:</strong> ${esc(p.result)}</p>
        <p class="small muted">Arrived through ${esc(p.tls)}. On the wire this was encrypted; below is what the server decrypted.</p>
      </div>
      <div>
        <h3>Decrypted packet</h3>
        <pre>${esc(pretty)}</pre>
      </div>
    </div>
  </details>`;
}

async function refresh() {
  const data = await api("/api/network");
  const s = data.stats;
  const set = (id, v) => { document.getElementById(id).textContent = v; };
  set("n-accepted", s.packets_accepted.toLocaleString());
  set("n-rejected", s.packets_rejected.toLocaleString());
  set("n-bytes", (s.bytes_received / 1024).toFixed(1) + " KB");
  set("n-accept-rate", s.acceptance_rate == null ? "--" : s.acceptance_rate + "%");
  set("n-uptime", s.uptime);
  set("n-conns", s.connections_total);

  document.getElementById("inspector").innerHTML = data.inspector.length
    ? data.inspector.map(packetRow).join("")
    : `<p class="empty">No packets yet. Start transmitting from the Bedside Monitor app.</p>`;

  document.getElementById("conn-rows").innerHTML = data.connections.length ? data.connections.map(c => `
    <tr><td><strong>${esc(c.device_id)}</strong></td><td>${esc(c.patient)}</td>
      <td>${c.ip ? `${c.ip} : ${c.port}` : "--"}</td><td>${c.packets}</td>
      <td>${c.latency_ms != null ? c.latency_ms + " ms" : "--"}</td><td>${c.last_seen || "--"}</td>
      <td><span class="pill ${c.online ? "normal" : "offline"}" style="margin:0">${c.online ? "Sending" : "Silent"}</span></td></tr>`).join("")
    : `<tr><td colspan="7" class="empty">No patients admitted.</td></tr>`;

  const reasons = Object.entries(s.reject_reasons);
  document.getElementById("reasons").innerHTML = reasons.length
    ? reasons.map(([r, n]) => `<li><span>${esc(r)}</span><b>${n}</b></li>`).join("")
    : `<li class="empty">Nothing blocked yet. Run security_test.py to try some attacks.</li>`;

  document.getElementById("log-rows").innerHTML = data.log.length ? data.log.map(e => `
    <tr><td>${e.time}</td><td><span class="tag ${e.kind}">${e.kind.toLowerCase()}</span></td>
      <td>${esc(e.device)}</td><td>${esc(e.ip)}</td><td class="detail">${esc(e.detail)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">No connections yet.</td></tr>`;
}

document.addEventListener("toggle", e => {
  if (e.target.matches?.("details.packet")) openPacket = e.target.open ? e.target.dataset.key : (openPacket === e.target.dataset.key ? null : openPacket);
}, true);

refresh();
setInterval(refresh, 1500);
