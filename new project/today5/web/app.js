// Shared helpers for all LeadPulse pages.

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && location.pathname !== "/login") { location.href = "/login"; throw new Error("Please log in"); }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg, kind = "info") {
  let box = document.getElementById("toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  const el = document.createElement("div");
  el.className = "toast";
  const color = kind === "error" ? "#f87171" : kind === "good" ? "#34d399" : "#a5b4fc";
  el.innerHTML = `<span style="color:${color}">●</span>&nbsp; ${esc(msg)}`;
  box.appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 300); }, 3200);
}

function confBadge(c) {
  if (!c) return "";
  return `<span class="badge badge-${esc(c)}"><span class="dot"></span>${esc(c)} confidence</span>`;
}

function statusBadge(s, paused) {
  if (paused) return `<span class="badge badge-conflict"><span class="dot"></span>paused</span>`;
  const map = {
    new: ["badge-info", "new", false], queued: ["badge-medium", "queued", true],
    researching: ["badge-medium", "researching", true], researched: ["badge-high", "researched", false],
    failed: ["badge-low", "failed", false],
  };
  const [cls, label, pulse] = map[s] || ["badge-info", s, false];
  return `<span class="badge ${cls}"><span class="dot ${pulse ? "pulse" : ""}"></span>${esc(label)}</span>`;
}

function srcLink(url, label) {
  if (!url) return `<span class="muted text-xs">no source</span>`;
  if (url.startsWith("manual:")) return `<span class="badge badge-info">pasted old info</span>`;
  let host = url;
  try { host = new URL(url).hostname.replace(/^www\./, "") + new URL(url).pathname.replace(/\/$/, ""); } catch {}
  return `<a class="src" href="${esc(url)}" target="_blank" rel="noopener">${esc(label || host)}</a>`;
}

function fmtDate(d) {
  if (!d) return "";
  const dt = new Date(d);
  if (isNaN(dt)) return esc(d);
  return dt.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function daysAgo(d) {
  const dt = new Date(d);
  if (isNaN(dt)) return "";
  const n = Math.round((Date.now() - dt.getTime()) / 86400000);
  if (n <= 0) return "today";
  if (n === 1) return "yesterday";
  if (n < 14) return `${n} days ago`;
  if (n < 60) return `${Math.floor(n / 7)} weeks ago`;
  return `${Math.floor(n / 30)} months ago`;
}

// Animated score ring (0-100)
const RING_R = 30, RING_C = 2 * Math.PI * RING_R;
function scoreRing(total) {
  return `<div class="score-ring" data-score="${Number(total) || 0}">
    <svg width="74" height="74" viewBox="0 0 74 74">
      <defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#22d3ee"/></linearGradient></defs>
      <circle class="track" cx="37" cy="37" r="${RING_R}"/>
      <circle class="bar" cx="37" cy="37" r="${RING_R}" stroke-dasharray="${RING_C}" stroke-dashoffset="${RING_C}"/>
    </svg><div class="num">0</div></div>`;
}

function animateRings(root = document) {
  root.querySelectorAll(".score-ring:not(.done)").forEach((ring) => {
    ring.classList.add("done");
    const score = Math.max(0, Math.min(100, parseFloat(ring.dataset.score)));
    requestAnimationFrame(() => {
      ring.querySelector(".bar").style.strokeDashoffset = RING_C * (1 - score / 100);
    });
    countUp(ring.querySelector(".num"), score);
  });
}

function countUp(el, target, ms = 1300) {
  const start = performance.now();
  const step = (t) => {
    const p = Math.min(1, (t - start) / ms);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(target * eased);
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function animateMeters(root = document) {
  root.querySelectorAll(".meter > i[data-w]").forEach((m) => requestAnimationFrame(() => (m.style.width = m.dataset.w + "%")));
}

// Cursor spotlight on cards
function attachSpotlight(root = document) {
  root.querySelectorAll(".card").forEach((card) => {
    if (card.dataset.spot) return;
    card.dataset.spot = "1";
    const spot = document.createElement("div");
    spot.className = "spot";
    card.prepend(spot);
    card.addEventListener("mousemove", (e) => {
      const r = card.getBoundingClientRect();
      spot.style.left = e.clientX - r.left + "px";
      spot.style.top = e.clientY - r.top + "px";
    });
  });
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    if (btn) { const old = btn.innerHTML; btn.innerHTML = "✓ Copied"; setTimeout(() => (btn.innerHTML = old), 1500); }
    toast("Message copied", "good");
  } catch { toast("Could not copy", "error"); }
}

const LOGO = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h4l3-8 4 16 3-8h6"/></svg>`;

function navHtml(active) {
  const link = (href, key, label) => `<a href="${href}" class="nav-link ${active === key ? "active" : ""}">${label}</a>`;
  return `<nav class="max-w-6xl mx-auto px-5 pt-6 flex items-center justify-between gap-4 fade-in relative">
    <a href="/" class="flex items-center gap-2.5 no-underline">
      <div class="rank pulse-logo" style="width:34px;height:34px;border-radius:11px">${LOGO}</div>
      <span class="font-extrabold tracking-tight text-lg">LeadPulse</span>
      <span class="badge badge-info hidden lg:inline-flex">Your hottest leads, every morning</span>
    </a>
    <button class="btn md:hidden" id="nav-toggle" style="padding:.4rem .7rem" aria-label="Menu">☰</button>
    <div id="nav-links" class="nav-links hidden md:flex items-center gap-5 text-sm font-semibold">
      ${link("/", "today", "Today")}
      ${link("/companies", "companies", "Companies")}
      ${link("/settings", "settings", "Settings")}
      ${link("/how-it-works", "how", "How it works")}
      <button class="nav-link" id="logout" style="background:none;border:0;cursor:pointer;font:inherit">Log out</button>
    </div></nav>`;
}

function initNav(active) {
  document.getElementById("bg").innerHTML = backdrop();
  document.getElementById("nav").innerHTML = navHtml(active);
  const links = document.getElementById("nav-links");
  document.getElementById("nav-toggle").onclick = (e) => { e.stopPropagation(); links.classList.toggle("open"); };
  document.addEventListener("click", (e) => { if (!links.contains(e.target)) links.classList.remove("open"); });
  document.getElementById("logout").onclick = async () => {
    await api("/api/logout", { method: "POST" }).catch(() => {});
    location.href = "/login";
  };
  maybeShowGuide();
  autoTick();
}

// If the daily automation is due (its time has passed and it has not run today), start it.
// Checked at most every 10 minutes per browser tab; the server ignores it when not due.
function autoTick() {
  let last = 0;
  try { last = Number(sessionStorage.getItem("lp_tick") || 0); } catch {}
  if (Date.now() - last < 10 * 60 * 1000) return;
  try { sessionStorage.setItem("lp_tick", String(Date.now())); } catch {}
  api("/api/automation/tick", { method: "POST" }).catch(() => {});
}

// Small "?" help bubble
function help(text) {
  return `<span class="help" tabindex="0">?<span class="help-tip">${esc(text)}</span></span>`;
}

// Confirm dialog (returns a Promise<boolean>)
function confirmBox(title, text, okLabel = "Confirm", danger = false) {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "modal-wrap";
    wrap.innerHTML = `<div class="modal glass p-6">
      <h3 class="text-lg font-bold">${esc(title)}</h3>
      <p class="muted text-sm mt-2">${esc(text)}</p>
      <div class="flex justify-end gap-2 mt-6">
        <button class="btn" data-no>Cancel</button>
        <button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-yes>${esc(okLabel)}</button>
      </div></div>`;
    document.body.appendChild(wrap);
    const close = (v) => { wrap.classList.add("out"); setTimeout(() => wrap.remove(), 200); resolve(v); };
    wrap.querySelector("[data-yes]").onclick = () => close(true);
    wrap.querySelector("[data-no]").onclick = () => close(false);
    wrap.onclick = (e) => { if (e.target === wrap) close(false); };
  });
}

// First-visit guide
const GUIDE = [
  ["Welcome to LeadPulse 👋", "LeadPulse researches companies for you and every morning shows only the 5 best ones to contact today, with the reason why now, the right person and a ready message."],
  ["1. Add companies", "Go to Companies and paste website addresses or upload a CSV file (hundreds are fine). Research starts by itself, one company at a time."],
  ["2. Check Today", "The Today page shows at most 5 companies with a fresh signal (funding, hiring, a new leader...). Copy the message, then press Done, Snooze or Not relevant."],
  ["3. Settings", "In Settings you can change API keys and their backups, set the daily automation time and describe your ideal customer."],
];
function maybeShowGuide(force = false) {
  let seen = false;
  try { seen = localStorage.getItem("lp_guide_done") === "1"; } catch {}
  if (seen && !force) return;
  let i = 0;
  const wrap = document.createElement("div");
  wrap.className = "modal-wrap";
  const done = () => {
    try { localStorage.setItem("lp_guide_done", "1"); } catch {}
    wrap.classList.add("out");
    setTimeout(() => wrap.remove(), 200);
  };
  const render = () => {
    const [t, d] = GUIDE[i];
    wrap.innerHTML = `<div class="modal glass p-7">
      <div class="flex gap-1.5 mb-5">${GUIDE.map((_, j) => `<span class="step-dot ${j <= i ? "on" : ""}"></span>`).join("")}</div>
      <h3 class="text-xl font-bold">${t}</h3><p class="muted mt-2">${d}</p>
      <div class="flex justify-between gap-2 mt-7">
        <button class="btn" data-skip>Skip</button>
        <button class="btn btn-primary" data-next>${i === GUIDE.length - 1 ? "Get started" : "Next →"}</button>
      </div></div>`;
    wrap.querySelector("[data-next]").onclick = () => { if (i < GUIDE.length - 1) { i++; render(); } else done(); };
    wrap.querySelector("[data-skip]").onclick = done;
  };
  render();
  document.body.appendChild(wrap);
}

function backdrop() {
  return `<div class="aurora"><span></span><span></span><span></span></div><div class="grid-overlay"></div>`;
}
