/* =============================================================
   dashboard.js - ward overview, one tile per admitted patient
   ============================================================= */

const strips = {};
const TRACE = { normal: "#132A3E", warning: "#8A5208", critical: "#C0392B", offline: "#8A99A6" };

function vitalCell(cls, label, value, unit, flagged) {
  return `<div class="vital ${cls} ${flagged ? "flag" : ""}">
            <div class="label">${label}</div>
            <div class="value">${value}<span class="unit">${unit}</span></div></div>`;
}

function bedTemplate(d) {
  return `
  <a class="bed ${d.status}" id="bed-${d.device_id}" href="/patient/${d.device_id}" aria-label="Open ${esc(d.patient)}">
    <div class="bed-head">
      <div>
        <div class="bed-id">${esc(d.ward)}, bed ${esc(d.bed)}</div>
        <div class="bed-name">${esc(d.patient)}</div>
        <div class="bed-meta">${d.age} yrs, ${esc(d.patient_code)}</div>
      </div>
      <span class="pill ${d.status}" data-role="pill"></span>
    </div>
    <div class="paper"><span class="lead">II</span><canvas></canvas></div>
    <div class="vitals" data-role="vitals"></div>
    <div class="bed-foot" data-role="foot"></div>
  </a>`;
}

function renderVitals(d) {
  const v = d.vitals, f = d.flags || [], on = v && d.online;
  const val = k => on ? v[k] : "--";
  return vitalCell("hr", "Heart rate", val("heart_rate"), "bpm", f.includes("heart_rate"))
       + vitalCell("", "SpO2", val("spo2"), "%", f.includes("spo2"))
       + vitalCell("", "Temp", on ? Number(v.temperature).toFixed(1) : "--", "°C", f.includes("temperature"))
       + vitalCell("", "Resp", val("resp_rate"), "/min", f.includes("resp_rate"))
       + vitalCell("bp", "BP", on ? `${v.bp_sys}/${v.bp_dia}` : "--/--", "mmHg", f.includes("bp_sys") || f.includes("bp_dia"));
}

function footText(d) {
  if (d.online) return `Receiving from ${d.ip}, ${d.latency_ms} ms`;
  if (d.last_seen) return `Signal lost. Last reading at ${d.last_seen}`;
  return `Waiting for bedside monitor ${d.device_id}`;
}

function renderAlerts(list) {
  const ul = document.getElementById("alerts");
  ul.innerHTML = list.length ? list.map(a => `
    <li class="alert ${a.level} ${a.acknowledged ? "acked" : ""}">
      <span class="bar"></span>
      <div>
        <div class="who">${esc(a.patient)} <span class="muted small">${esc(a.device_id)}</span></div>
        <div class="what">${esc(a.message)}</div>
        <div class="when">${a.time}${a.acknowledged ? `, acknowledged by ${esc(a.ack_by)}` : ""}</div>
      </div>
      <div>${a.acknowledged ? "" : `<button class="btn" data-ack="${a.id}">Acknowledge</button>`}</div>
    </li>`).join("") : `<li class="empty">No alerts. Every reading received so far is within its limits.</li>`;
}

async function refresh() {
  try {
    const data = await api("/api/snapshot");
    const grid = document.getElementById("beds");
    const ids = new Set(data.devices.map(d => d.device_id));

    // remove tiles of discharged patients
    Object.keys(strips).forEach(id => {
      if (!ids.has(id)) { document.getElementById(`bed-${id}`)?.remove(); delete strips[id]; }
    });

    data.devices.forEach(d => {
      let tile = document.getElementById(`bed-${d.device_id}`);
      if (!tile) {
        grid.insertAdjacentHTML("beforeend", bedTemplate(d));
        tile = document.getElementById(`bed-${d.device_id}`);
        strips[d.device_id] = new EcgStrip(tile.querySelector("canvas"));
      }
      tile.className = `bed ${d.status}`;
      const pill = tile.querySelector('[data-role="pill"]');
      pill.className = `pill ${d.status}`;
      pill.textContent = STATUS_TEXT[d.status];
      tile.querySelector('[data-role="vitals"]').innerHTML = renderVitals(d);
      tile.querySelector('[data-role="foot"]').textContent = footText(d);
      strips[d.device_id].setRate(d.online && d.vitals ? d.vitals.heart_rate : 0, TRACE[d.status]);
    });

    document.getElementById("empty").hidden = data.devices.length > 0;
    const s = data.summary;
    document.getElementById("s-online").textContent = `${s.online}/${s.total}`;
    document.getElementById("s-critical").textContent = s.critical;
    document.getElementById("s-warning").textContent = s.warning;
    document.getElementById("s-alerts").textContent = s.unacknowledged;
    document.title = s.critical ? `(${s.critical}) Critical - Central Station` : "Ward overview - Central Station";
    renderAlerts(data.alerts);
    document.getElementById("conn-state").textContent =
      s.online ? `Receiving encrypted data from ${s.online} monitor${s.online > 1 ? "s" : ""}` : "Listening for bedside monitors";
  } catch (e) {
    document.getElementById("conn-state").textContent = "Website lost contact with the server";
  }
}

document.addEventListener("click", async e => {
  const id = e.target.dataset.ack;
  if (!id) return;
  e.preventDefault();
  e.target.disabled = true;
  await api(`/api/alerts/${id}/ack`, { method: "POST" });
  refresh();
});

refresh();
setInterval(refresh, 1000);
