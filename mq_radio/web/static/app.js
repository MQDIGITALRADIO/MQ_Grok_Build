/* MQ On-Air desk — wired to existing /api/* stubs */

const HOTKEY_DEFAULTS = [
  { key: "F1", label: "Top of Hour ID", type: "ID" },
  { key: "F2", label: "Legal ID", type: "ID" },
  { key: "F3", label: "Sweeper — More Music", type: "SWEEPER" },
  { key: "F4", label: "Sweeper — Brand", type: "SWEEPER" },
  { key: "F5", label: "Weekend Promo", type: "PROMO" },
  { key: "F6", label: "Contest Promo", type: "PROMO" },
  { key: "F7", label: "VT Bed", type: "VT" },
  { key: "F8", label: "Emergency Fill", type: "MUSIC" },
];

let playoutMode = "AUTO";
let lastStatus = null;
let lastEvents = null;

function todayISO() {
  const d = new Date();
  const z = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

function fmtDur(ms) {
  if (ms == null || ms === "") return "—";
  const s = Math.round(Number(ms) / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function fmtAirtime(iso) {
  if (!iso) return "—";
  const t = String(iso).includes("T") ? String(iso).split("T")[1] : String(iso);
  return t.slice(0, 8);
}

function typeLabel(t) {
  if (!t) return "—";
  if (t === "VOICE_TRACK") return "VT";
  return t;
}

function fillDeck(prefix, event, stateClass, stateText) {
  const typeEl = document.getElementById(`${prefix}-type`);
  const titleEl = document.getElementById(`${prefix}-title`);
  const artistEl = document.getElementById(`${prefix}-artist`);
  const chainEl = document.getElementById(`${prefix}-chain`);
  const durEl = document.getElementById(`${prefix}-dur`);
  const stateEl = document.getElementById(`${prefix}-state`);
  const meterEl = document.getElementById(`${prefix}-meter`);

  stateEl.className = `deck-state ${stateClass}`;
  stateEl.textContent = stateText;

  if (!event) {
    typeEl.textContent = "—";
    typeEl.className = "deck-type";
    titleEl.textContent = "(empty)";
    artistEl.textContent = "—";
    chainEl.textContent = "—";
    durEl.textContent = "0:00";
    meterEl.className = "meter-bar idle";
    return;
  }

  const tl = typeLabel(event.event_type);
  typeEl.textContent = tl;
  typeEl.className = `deck-type tag-${event.event_type} tag-${tl}`;
  titleEl.textContent = event.title || event.event_type || "—";
  artistEl.textContent = event.artist || "—";
  chainEl.textContent = `${event.chain_mode || "—"}/${event.timing_mode || "—"}`;
  durEl.textContent = fmtDur(event.duration_ms);
  meterEl.className = stateClass === "onair" ? "meter-bar" : "meter-bar idle";
}

function pickNextEtm(events, upcoming) {
  const now = Date.now();
  const pool = []
    .concat(upcoming || [])
    .concat(events || [])
    .filter((e) => e && e.event_type === "ETM");
  const seen = new Set();
  const unique = [];
  for (const e of pool) {
    if (seen.has(e.id)) continue;
    seen.add(e.id);
    unique.push(e);
  }
  const future = unique
    .filter((e) => {
      const t = Date.parse(e.scheduled_at);
      return !Number.isNaN(t) && t >= now - 2000;
    })
    .sort((a, b) => Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at));
  if (future.length) return future[0];
  return unique.sort(
    (a, b) => Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at)
  )[0] || null;
}

function updateETM(events, upcoming) {
  const etm = pickNextEtm(events, upcoming);
  const etmEl = document.getElementById("etm-readout");
  const toEl = document.getElementById("to-time");
  if (!etm) {
    etmEl.textContent = "NONE";
    toEl.textContent = "--:--";
    return;
  }
  etmEl.textContent = fmtAirtime(etm.scheduled_at);
  const target = new Date(etm.scheduled_at);
  const now = new Date();
  let diff = Math.floor((target - now) / 1000);
  if (Number.isNaN(diff)) {
    toEl.textContent = "--:--";
    return;
  }
  const sign = diff < 0 ? "-" : "+";
  diff = Math.abs(diff);
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = diff % 60;
  toEl.textContent =
    h > 0
      ? `${sign}${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
      : `${sign}${m}:${String(s).padStart(2, "0")}`;
}

function buildHotkeys(upcoming) {
  const grid = document.getElementById("hotkey-grid");
  grid.innerHTML = "";
  const fromLog = (upcoming || [])
    .filter((e) =>
      ["ID", "SWEEPER", "PROMO", "VOICE_TRACK", "MUSIC"].includes(e.event_type)
    )
    .slice(0, 8);

  const items = HOTKEY_DEFAULTS.map((def, i) => {
    const ev = fromLog[i];
    return {
      key: def.key,
      label: ev ? ev.title || def.label : def.label,
      type: ev ? typeLabel(ev.event_type) : def.type,
    };
  });

  items.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "hotkey";
    btn.innerHTML = `
      <span class="hk-key">${item.key}</span>
      <span class="hk-label">${escapeHtml(item.label)}</span>
      <span class="hk-type">${item.type}</span>`;
    btn.onclick = () => fireHotkey(btn, item);
    grid.appendChild(btn);
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fireHotkey(btn, item) {
  btn.classList.add("fired");
  setTimeout(() => btn.classList.remove("fired"), 180);
  const msg = document.getElementById("engine-msg");
  msg.textContent = `HOTKEY ${item.key}: ${item.label}`;
}

async function refresh() {
  const date = document.getElementById("log-date").value || todayISO();
  const st = await fetch(`/api/status?date=${date}`).then((r) => r.json());
  lastStatus = st;
  const np = st.now;
  const up = st.upcoming || [];

  fillDeck("deck-a", np, "onair", "ON AIR");
  fillDeck("deck-b", up[0] || null, "next", "NEXT");
  fillDeck("deck-c", up[1] || null, "ready", "READY");

  const onAir = np && np.status === "ON_AIR";
  document.getElementById("lamp-onair").classList.toggle("lit", !!onAir || !!np);
  document.getElementById("lamp-ready").classList.toggle("lit", !!up[0]);

  const log = await fetch(`/api/log?date=${date}`).then((r) => r.json());
  const events = log.events || [];
  lastEvents = events;
  document.getElementById("log-count").textContent = `${events.length} events`;

  updateETM(events, up);
  buildHotkeys(up);

  const body = document.getElementById("log-body");
  body.innerHTML = "";
  const nextPos = up[0] ? up[0].position : null;

  events.forEach((e) => {
    const tr = document.createElement("tr");
    tr.className = "log-row";
    if (e.status === "ON_AIR" || (np && e.id === np.id && e.status !== "COMPLETED")) {
      tr.classList.add("on-air");
    } else if (nextPos != null && e.position === nextPos) {
      tr.classList.add("next-up");
    } else if (e.status === "COMPLETED" || e.status === "SKIPPED") {
      tr.classList.add("completed");
    }

    const tl = typeLabel(e.event_type);
    tr.innerHTML = `
      <td class="col-pos">${e.position}</td>
      <td class="col-time">${fmtAirtime(e.scheduled_at)}</td>
      <td class="col-type"><span class="type-tag ${e.event_type} ${tl}">${tl}</span></td>
      <td class="col-chain">${e.chain_mode || ""}</td>
      <td class="col-timing">${e.timing_mode || ""}</td>
      <td class="col-artist">${escapeHtml(e.artist || "")}</td>
      <td class="col-title">${escapeHtml(e.title || "")}</td>
      <td class="col-dur">${fmtDur(e.duration_ms)}</td>
      <td class="col-status">${e.status || ""}</td>`;
    body.appendChild(tr);
  });

  // Keep ON AIR row visible
  const onAirRow = body.querySelector("tr.on-air");
  if (onAirRow) {
    onAirRow.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

async function postAction(path) {
  const date = document.getElementById("log-date").value || todayISO();
  const res = await fetch(`${path}?date=${date}`, { method: "POST" }).then((r) =>
    r.json()
  );
  document.getElementById("engine-msg").textContent = res.message || "";
  await refresh();
}

function tickClock() {
  const now = new Date();
  const z = (n) => String(n).padStart(2, "0");
  const hms = `${z(now.getHours())}:${z(now.getMinutes())}:${z(now.getSeconds())}`;
  document.getElementById("wallclock").textContent = hms;
  document.getElementById("footer-clock").textContent = now.toLocaleString();
  if (lastStatus) {
    updateETM(lastEvents, lastStatus.upcoming || []);
  }
}

function setMode(mode) {
  playoutMode = mode;
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
  document.getElementById("mode-status").textContent = `MODE: ${mode}`;
  document.getElementById("engine-msg").textContent = `Mode → ${mode}`;
}

document.getElementById("log-date").value = todayISO();
document.getElementById("btn-refresh").onclick = refresh;
document.getElementById("btn-play").onclick = () => postAction("/api/play");
document.getElementById("btn-stop").onclick = () => postAction("/api/stop");
document.getElementById("btn-skip").onclick = () => postAction("/api/skip");
document.getElementById("btn-step").onclick = () => postAction("/api/step");
document.getElementById("log-date").onchange = refresh;

document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.onclick = () => setMode(btn.dataset.mode);
});

document.addEventListener("keydown", (ev) => {
  if (ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA")) {
    return;
  }
  if (ev.code === "Space") {
    ev.preventDefault();
    postAction("/api/play");
    return;
  }
  if (ev.key === "Escape") {
    postAction("/api/stop");
    return;
  }
  const m = /^F([1-8])$/.exec(ev.key);
  if (m) {
    ev.preventDefault();
    const idx = Number(m[1]) - 1;
    const btn = document.querySelectorAll(".hotkey")[idx];
    if (btn) btn.click();
  }
});

setInterval(tickClock, 250);
tickClock();
refresh();
setInterval(refresh, 5000);
