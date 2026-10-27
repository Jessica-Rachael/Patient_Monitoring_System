/* =============================================================
   common.js - helpers shared by every page
   ============================================================= */

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* Fetch JSON from the server; send the user to login if the session expired */
async function api(url, options = {}) {
  const res = await fetch(url, options);
  if (res.status === 401) { window.location.href = "/login"; throw new Error("login required"); }
  return res.json();
}

/* Escape text before putting it into HTML */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const STATUS_TEXT = { normal: "Stable", warning: "Needs attention", critical: "Critical", offline: "No signal" };

/* Live clock in the top bar */
function startClock() {
  const el = document.getElementById("clock");
  if (!el) return;
  const tick = () => { el.textContent = new Date().toLocaleTimeString([], { hour12: false }); };
  tick(); setInterval(tick, 1000);
}

/* -------------------------------------------------------------
   EcgStrip: draws a moving ECG-style trace on graph paper.
   The shape is synthetic (P-QRS-T), paced by the heart rate the
   device sent, so the rhythm on screen matches the real number.
   ------------------------------------------------------------- */
class EcgStrip {
  constructor(canvas, color = "#132A3E") {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.color = color;
    this.hr = 0;            // 0 = flat line (no signal)
    this.phase = 0;         // position inside the current heartbeat (0..1)
    this.cursor = 0;
    this.points = [];
    this.speed = 90;        // pixels per second (like 25 mm/s paper speed)
    this.last = performance.now();
    this.resize();
    window.addEventListener("resize", () => this.resize());
    requestAnimationFrame(t => this.frame(t));
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const r = this.canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(r.width)), h = Math.max(1, Math.floor(r.height));
    if (w === this.w && h === this.h) return;   // size unchanged: keep the trace
    this.w = w; this.h = h;
    this.canvas.width = this.w * dpr;
    this.canvas.height = this.h * dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.points = new Array(this.w).fill(null);
    this.cursor = 0;
  }

  setRate(hr, color) { this.hr = hr || 0; if (color) this.color = color; }

  /* Height of the waveform (-1..1) at a point inside one heartbeat */
  static wave(p) {
    const g = (c, w, a) => a * Math.exp(-((p - c) ** 2) / (2 * w * w));
    return g(0.12, 0.025, 0.12)     // P wave
         + g(0.215, 0.008, -0.14)   // Q
         + g(0.24, 0.010, 1.0)      // R spike
         + g(0.265, 0.010, -0.28)   // S
         + g(0.48, 0.045, 0.30);    // T wave
  }

  frame(now) {
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    if (!REDUCED_MOTION) this.advance(dt * this.speed);
    else if (!this.drawnStatic) { this.advance(this.w); this.drawnStatic = true; }
    this.draw();
    requestAnimationFrame(t => this.frame(t));
  }

  advance(px) {
    const beatsPerPx = this.hr > 0 ? (this.hr / 60) / this.speed : 0;
    for (let i = 0; i < px; i++) {
      this.phase = (this.phase + beatsPerPx) % 1;
      const y = this.hr > 0 ? EcgStrip.wave(this.phase) + (Math.random() - 0.5) * 0.02 : 0;
      this.points[this.cursor] = y;
      this.cursor = (this.cursor + 1) % this.w;
    }
  }

  draw() {
    const { ctx, w, h } = this;
    ctx.clearRect(0, 0, w, h);
    const mid = h * 0.62, amp = h * 0.48;
    const gap = 14;  // erase bar in front of the sweeping cursor
    ctx.strokeStyle = this.color;
    ctx.lineWidth = 1.8;
    ctx.lineJoin = "round";
    ctx.beginPath();
    let pen = false;
    for (let x = 0; x < w; x++) {
      const dist = (x - this.cursor + w) % w;
      const y = this.points[x];
      if (y === null || dist < gap) { pen = false; continue; }
      const py = mid - y * amp;
      if (!pen) { ctx.moveTo(x, py); pen = true; } else ctx.lineTo(x, py);
    }
    ctx.stroke();
  }
}

/* -------------------------------------------------------------
   drawTrend: small line chart with the safe range shaded.
   ------------------------------------------------------------- */
function drawTrend(canvas, values, opts) {
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  const w = r.width, h = r.height;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const pad = { l: 34, r: 8, t: 8, b: 18 };
  const series = opts.series || [{ values, color: opts.color || "#0A6F6B" }];
  const all = series.flatMap(s => s.values).filter(v => v != null);
  let min = Math.min(opts.min ?? Infinity, ...all, opts.band ? opts.band[0] : Infinity);
  let max = Math.max(opts.max ?? -Infinity, ...all, opts.band ? opts.band[1] : -Infinity);
  if (!isFinite(min)) { min = 0; max = 1; }
  const span = (max - min) || 1; min -= span * 0.08; max += span * 0.08;
  const X = i => pad.l + (i / Math.max(1, (opts.length || all.length) - 1)) * (w - pad.l - pad.r);
  const Y = v => pad.t + (1 - (v - min) / (max - min)) * (h - pad.t - pad.b);

  // safe band
  if (opts.band) {
    ctx.fillStyle = "rgba(46,125,87,0.08)";
    ctx.fillRect(pad.l, Y(opts.band[1]), w - pad.l - pad.r, Y(opts.band[0]) - Y(opts.band[1]));
    ctx.strokeStyle = "rgba(46,125,87,0.35)"; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
    [opts.band[0], opts.band[1]].forEach(v => { ctx.beginPath(); ctx.moveTo(pad.l, Y(v)); ctx.lineTo(w - pad.r, Y(v)); ctx.stroke(); });
    ctx.setLineDash([]);
  }
  // y axis labels
  ctx.fillStyle = "#5E7285"; ctx.font = "11px 'Public Sans', system-ui, sans-serif"; ctx.textAlign = "right";
  [max, (max + min) / 2, min].forEach(v => ctx.fillText(v.toFixed(opts.decimals ?? 0), pad.l - 6, Y(v) + 4));
  ctx.textAlign = "left"; ctx.fillText(opts.xLabel || "last 5 min", pad.l, h - 3);

  // lines
  series.forEach(s => {
    ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.lineJoin = "round";
    ctx.beginPath();
    s.values.forEach((v, i) => { if (i === 0) ctx.moveTo(X(i), Y(v)); else ctx.lineTo(X(i), Y(v)); });
    ctx.stroke();
  });
}

document.addEventListener("DOMContentLoaded", startClock);
