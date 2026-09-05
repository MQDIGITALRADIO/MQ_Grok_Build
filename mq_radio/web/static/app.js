/* MQ On-Air desk — timers, end-ramp, audio routing settings */

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

const MOCK_AUDIO_DEVICES = [
  { id: "builtin", label: "Built-in Output" },
  { id: "usb", label: "USB Interface" },
  { id: "aggregate", label: "Aggregate Device" },
  { id: "blackhole", label: "BlackHole 2ch" },
  { id: "none", label: "None" },
];

const AUDIO_ROLES = ["program", "monitor", "headphones", "stream", "record"];
const SETTINGS_LS_KEY = "mq_radio_audio_outputs_v1";

const DEFAULT_AUDIO_ROUTES = {
  program: "builtin",
  monitor: "builtin",
  headphones: "usb",
  stream: "same_as_program",
  record: "none",
};

let playoutMode = "AUTO";
let lastStatus = null;
let lastEvents = null;

/** Local timer extrapolation state synced from /api/status timing */
let timingSnap = {
  playing: false,
  eventId: null,
  duration_ms: 0,
  elapsed_ms: 0,
  remaining_ms: 0,
  progress: 0,
  syncedAt: 0,
};

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

/** Classic air-studio mm:ss.t (tenths) */
function fmtTimer(ms) {
  const n = Math.max(0, Math.floor(Number(ms) || 0));
  const totalTenths = Math.floor(n / 100);
  const tenths = totalTenths % 10;
  const totalSec = Math.floor(totalTenths / 10);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}.${tenths}`;
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

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function endingDisplay(event) {
  if (!event) return "—";
  if (event.ending_label) return event.ending_label;
  const et = event.ending_type || "";
  const outro = Number(event.outro_ms || 0);
  const intro = Number(event.intro_ms || 0);
  const parts = [];
  if (intro > 0) parts.push(`INTRO ${(intro / 1000).toFixed(1)}s`);
  if (et && outro > 0) parts.push(`${et} · ${(outro / 1000).toFixed(1)}s`);
  else if (et) parts.push(et);
  return parts.join(" · ") || "—";
}

function clearEndRamp(deckEl, meterEl) {
  if (deckEl) {
    deckEl.classList.remove(
      "end-ramp",
      "end-ramp-1",
      "end-ramp-2",
      "end-ramp-3",
      "end-ramp-4",
      "end-ramp-5"
    );
  }
  if (meterEl) {
    meterEl.classList.remove(
      "end-ramp-1",
      "end-ramp-2",
      "end-ramp-3",
      "end-ramp-4",
      "end-ramp-5"
    );
  }
}

function applyEndRamp(deckEl, meterEl, remainingMs) {
  clearEndRamp(deckEl, meterEl);
  if (remainingMs == null || remainingMs > 5000 || remainingMs < 0) return;
  // Intensify over last 5s: level 1 at ~5s … level 5 in final second
  const level = Math.min(5, Math.max(1, 6 - Math.ceil(remainingMs / 1000)));
  deckEl.classList.add("end-ramp", `end-ramp-${level}`);
  if (meterEl && !meterEl.classList.contains("idle")) {
    meterEl.classList.add(`end-ramp-${level}`);
  }
}

function fillDeck(prefix, event, stateClass, stateText) {
  const typeEl = document.getElementById(`${prefix}-type`);
  const titleEl = document.getElementById(`${prefix}-title`);
  const artistEl = document.getElementById(`${prefix}-artist`);
  const chainEl = document.getElementById(`${prefix}-chain`);
  const durEl = document.getElementById(`${prefix}-dur`);
  const stateEl = document.getElementById(`${prefix}-state`);
  const meterEl = document.getElementById(`${prefix}-meter`);
  const endingEl = document.getElementById(`${prefix}-ending`);
  const deckEl = document.getElementById(prefix);

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
    if (endingEl) {
      endingEl.textContent = "—";
      endingEl.className = "timer-ending";
    }
    if (prefix === "deck-a") {
      document.getElementById("deck-a-elapsed").textContent = "0:00.0";
      document.getElementById("deck-a-remaining").textContent = "0:00.0";
    }
    clearEndRamp(deckEl, meterEl);
    return;
  }

  const tl = typeLabel(event.event_type);
  typeEl.textContent = tl;
  typeEl.className = `deck-type tag-${event.event_type} tag-${tl}`;
  titleEl.textContent = event.title || event.event_type || "—";
  artistEl.textContent = event.artist || "—";
  chainEl.textContent = `${event.chain_mode || "—"}/${event.timing_mode || "—"}`;
  durEl.textContent = fmtDur(event.duration_ms);
  meterEl.className = stateClass === "onair" ? "meter-bar progressing" : "meter-bar idle";

  if (endingEl) {
    endingEl.textContent = endingDisplay(event);
    endingEl.className = `timer-ending ending-${event.ending_type || ""}`;
  }
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
  return (
    unique.sort(
      (a, b) => Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at)
    )[0] || null
  );
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

function fireHotkey(btn, item) {
  btn.classList.add("fired");
  setTimeout(() => btn.classList.remove("fired"), 180);
  document.getElementById("engine-msg").textContent = `HOTKEY ${item.key}: ${item.label}`;
}

function syncTimingFromStatus(st) {
  const t = st.timing || {};
  const playing = !!(t.playing || st.running);
  const nowEv = st.now;
  const onAir = nowEv && nowEv.status === "ON_AIR";
  timingSnap = {
    playing: playing && !!onAir,
    eventId: onAir ? nowEv.id : null,
    duration_ms: Number(t.duration_ms || (onAir && nowEv.duration_ms) || 0),
    elapsed_ms: Number(t.elapsed_ms || 0),
    remaining_ms: Number(t.remaining_ms || 0),
    progress: Number(t.progress || 0),
    syncedAt: Date.now(),
  };
  // Prefer server remaining when present
  if (timingSnap.playing && timingSnap.duration_ms > 0 && t.elapsed_ms != null) {
    timingSnap.remaining_ms = Math.max(
      0,
      timingSnap.duration_ms - timingSnap.elapsed_ms
    );
  }
}

function liveTiming() {
  if (!timingSnap.playing) {
    return {
      elapsed_ms: 0,
      remaining_ms: timingSnap.duration_ms || 0,
      progress: 0,
      playing: false,
    };
  }
  const delta = Date.now() - timingSnap.syncedAt;
  const elapsed = Math.min(
    timingSnap.duration_ms || Infinity,
    timingSnap.elapsed_ms + delta
  );
  const dur = timingSnap.duration_ms || 0;
  const remaining = Math.max(0, dur - elapsed);
  const progress = dur > 0 ? Math.min(1, elapsed / dur) : 0;
  return { elapsed_ms: elapsed, remaining_ms: remaining, progress, playing: true };
}

function tickTimers() {
  const live = liveTiming();
  const elapsedEl = document.getElementById("deck-a-elapsed");
  const remainEl = document.getElementById("deck-a-remaining");
  const meterEl = document.getElementById("deck-a-meter");
  const deckEl = document.getElementById("deck-a");

  if (!timingSnap.playing) {
    // Show full duration as remaining when next cart is cued but not on air
    if (lastStatus && lastStatus.now && lastStatus.now.status !== "ON_AIR") {
      const dur = Number(lastStatus.now.duration_ms || 0);
      elapsedEl.textContent = "0:00.0";
      remainEl.textContent = fmtTimer(dur);
    }
    clearEndRamp(deckEl, meterEl);
    if (meterEl && meterEl.classList.contains("progressing")) {
      meterEl.style.setProperty("--progress", "0");
    }
    return;
  }

  elapsedEl.textContent = fmtTimer(live.elapsed_ms);
  remainEl.textContent = fmtTimer(live.remaining_ms);
  if (meterEl) {
    meterEl.classList.add("progressing");
    meterEl.classList.remove("idle");
    meterEl.style.setProperty("--progress", String(live.progress));
  }
  applyEndRamp(deckEl, meterEl, live.remaining_ms);

  // When local timer hits zero, refresh so finish_if_due advances the log
  if (live.remaining_ms <= 0 && timingSnap.duration_ms > 0) {
    timingSnap.playing = false;
    refresh();
  }
}

async function refresh() {
  const date = document.getElementById("log-date").value || todayISO();
  const st = await fetch(`/api/status?date=${date}`).then((r) => r.json());
  lastStatus = st;
  const np = st.now;
  const up = st.upcoming || [];

  const onAir = np && np.status === "ON_AIR";
  fillDeck("deck-a", np, onAir ? "onair" : "onair", onAir ? "ON AIR" : "CUED");
  if (!onAir && np) {
    document.getElementById("deck-a-state").className = "deck-state next";
    document.getElementById("deck-a-state").textContent = "CUED";
  }
  fillDeck("deck-b", up[0] || null, "next", "NEXT");
  fillDeck("deck-c", up[1] || null, "ready", "READY");

  syncTimingFromStatus(st);
  tickTimers();

  document.getElementById("lamp-onair").classList.toggle("lit", !!onAir);
  document.getElementById("lamp-ready").classList.toggle("lit", !!up[0]);
  if (st.running && onAir) {
    document.getElementById("engine-msg").textContent =
      document.getElementById("engine-msg").textContent || "playing";
  }

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
    if (e.status === "ON_AIR" || (np && e.id === np.id && e.status === "ON_AIR")) {
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
  tickTimers();
}

function setMode(mode) {
  playoutMode = mode;
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
  document.getElementById("mode-status").textContent = `MODE: ${mode}`;
  document.getElementById("engine-msg").textContent = `Mode → ${mode}`;
}

/* —— Audio output settings —— */
function loadAudioRoutes() {
  try {
    const raw = localStorage.getItem(SETTINGS_LS_KEY);
    if (raw) return { ...DEFAULT_AUDIO_ROUTES, ...JSON.parse(raw) };
  } catch (_) {}
  return { ...DEFAULT_AUDIO_ROUTES };
}

function saveAudioRoutes(routes) {
  localStorage.setItem(SETTINGS_LS_KEY, JSON.stringify(routes));
  // Also persist to server JSON when available
  fetch("/api/settings/audio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(routes),
  }).catch(() => {});
}

function deviceOptionsHtml(includeSameAsProgram) {
  const opts = [];
  if (includeSameAsProgram) {
    opts.push(
      `<option value="same_as_program">Same as Program</option>`
    );
  }
  MOCK_AUDIO_DEVICES.forEach((d) => {
    opts.push(`<option value="${d.id}">${escapeHtml(d.label)}</option>`);
  });
  return opts.join("");
}

function populateSettingsForm(routes) {
  AUDIO_ROLES.forEach((role) => {
    const sel = document.getElementById(`out-${role}`);
    if (!sel) return;
    const same = role === "stream" || role === "record";
    sel.innerHTML = deviceOptionsHtml(same);
    const val = routes[role] || DEFAULT_AUDIO_ROUTES[role];
    if ([...sel.options].some((o) => o.value === val)) sel.value = val;
    else sel.selectedIndex = 0;
  });
}

function readSettingsForm() {
  const routes = {};
  AUDIO_ROLES.forEach((role) => {
    const sel = document.getElementById(`out-${role}`);
    routes[role] = sel ? sel.value : DEFAULT_AUDIO_ROUTES[role];
  });
  return routes;
}

function openSettings() {
  populateSettingsForm(loadAudioRoutes());
  const bd = document.getElementById("settings-backdrop");
  bd.classList.add("open");
  bd.setAttribute("aria-hidden", "false");
}

function closeSettings() {
  const bd = document.getElementById("settings-backdrop");
  bd.classList.remove("open");
  bd.setAttribute("aria-hidden", "true");
}

function initSettings() {
  document.getElementById("btn-settings").onclick = openSettings;
  document.getElementById("btn-settings-close").onclick = closeSettings;
  document.getElementById("btn-settings-cancel").onclick = closeSettings;
  document.getElementById("btn-settings-save").onclick = () => {
    const routes = readSettingsForm();
    saveAudioRoutes(routes);
    document.getElementById("engine-msg").textContent = "Audio outputs saved";
    closeSettings();
  };
  document.getElementById("settings-backdrop").addEventListener("click", (ev) => {
    if (ev.target.id === "settings-backdrop") closeSettings();
  });
  // Prefetch server settings (merge over local if present)
  fetch("/api/settings/audio")
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (data && data.outputs) {
        const merged = { ...loadAudioRoutes(), ...data.outputs };
        localStorage.setItem(SETTINGS_LS_KEY, JSON.stringify(merged));
      }
    })
    .catch(() => {});
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
  if (ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA" || ev.target.tagName === "SELECT")) {
    return;
  }
  if (ev.key === "Escape") {
    const bd = document.getElementById("settings-backdrop");
    if (bd.classList.contains("open")) {
      closeSettings();
      return;
    }
    postAction("/api/stop");
    return;
  }
  if (ev.code === "Space") {
    ev.preventDefault();
    postAction("/api/play");
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

initSettings();
setInterval(tickClock, 250);
tickClock();
refresh();
setInterval(refresh, 5000);
