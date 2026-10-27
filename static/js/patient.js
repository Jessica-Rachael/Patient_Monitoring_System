/* =============================================================
   patient.js - one patient in detail (staff view and patient portal)
   ============================================================= */

const DEV_ID = document.body.dataset.device;
const strip = new EcgStrip(document.getElementById("ecg"));
const TRACE = { normal: "#132A3E", warning: "#8A5208", critical: "#C0392B", offline: "#8A99A6" };
const FIELDS = ["heart_rate", "spo2", "temperature", "resp_rate", "bp_sys", "bp_dia"];

async function refresh() {
  const data = await api(`/api/patient/${DEV_ID}`);
  if (data.error) { document.getElementById("waiting").textContent = data.error; return; }
  const d = data.device, v = d.vitals, h = data.history, L = d.limits;
  const on = v && d.online;

  const pill = document.getElementById("status-pill");
  pill.className = `pill ${d.status}`;
  pill.textContent = STATUS_TEXT[d.status];

  FIELDS.forEach(k => {
    const cell = document.getElementById(`v-${k}`);
    cell.querySelector(".n").textContent = on ? (k === "temperature" ? Number(v[k]).toFixed(1) : v[k]) : "--";
    cell.classList.toggle("flag", d.flags.includes(k));
  });

  const waiting = document.getElementById("waiting");
  waiting.hidden = on;
  if (!on) waiting.textContent = d.last_seen
    ? `Signal lost. The last reading from ${d.device_id} arrived at ${d.last_seen}.`
    : `Waiting for the bedside monitor. Nothing has been received from ${d.device_id} yet.`;

  strip.setRate(on ? v.heart_rate : 0, TRACE[d.status]);

  if (h.length) {
    const col = k => h.map(p => p[k]);
    const len = Math.max(60, h.length);
    drawTrend(document.getElementById("c-hr"), col("heart_rate"), { band: L.heart_rate, color: "#132A3E", length: len, xLabel: "recent readings" });
    drawTrend(document.getElementById("c-spo2"), col("spo2"), { band: L.spo2, color: "#0A6F6B", length: len, xLabel: "recent readings" });
    drawTrend(document.getElementById("c-temp"), col("temperature"), { band: L.temperature, color: "#A8660B", length: len, decimals: 1, xLabel: "recent readings" });
    drawTrend(document.getElementById("c-bp"), null, { length: len, band: [L.bp_dia[0], L.bp_sys[1]], xLabel: "recent readings",
      series: [{ values: col("bp_sys"), color: "#C0392B" }, { values: col("bp_dia"), color: "#5E7285" }] });
  }

  const set = (id, t) => { document.getElementById(id).textContent = t; };
  set("f-link", d.online ? "Receiving now" : (d.last_seen ? "Signal lost" : "Never connected"));
  set("f-ip", d.ip ? `${d.ip} : ${d.port}` : "--");
  set("f-tls", d.tls || "--");
  set("f-packets", d.packets);
  set("f-latency", d.latency_ms != null ? `${d.latency_ms} ms` : "--");
  set("f-seen", d.last_seen || "--");

  document.getElementById("alerts").innerHTML = data.alerts.length ? data.alerts.map(a => `
    <li class="alert ${a.level} ${a.acknowledged ? "acked" : ""}"><span class="bar"></span>
      <div><div class="what">${esc(a.message)}</div><div class="when">${a.time}${a.acknowledged ? `, seen by ${esc(a.ack_by)}` : ""}</div></div><div></div>
    </li>`).join("") : `<li class="empty">No alerts yet.</li>`;
}

refresh();
setInterval(refresh, 1000);
