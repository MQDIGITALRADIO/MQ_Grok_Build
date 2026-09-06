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
  { id: "zoom_virtual", label: "ZoomAudioDevice (mock)" },
  { id: "phone_hybrid", label: "Phone Hybrid (mock)" },
  { id: "none", label: "None" },
];

const MOCK_INPUT_DEVICES = [
  { id: "none", label: "None" },
  { id: "usb_in", label: "USB Interface In" },
  { id: "builtin_in", label: "Built-in Mic / Line" },
  { id: "zoom_return", label: "Zoom Return (mock)" },
  { id: "phone_return", label: "Phone Hybrid Return (mock)" },
  { id: "aggregate_in", label: "Aggregate Input" },
];

const INSERT_OPTIONS = [
  { id: "none", label: "(none) — Native processing" },
  { id: "native_only", label: "Native only (force MQ chain)" },
];

const AUDIO_ROLES = [
  "program",
  "monitor",
  "headphones",
  "aux1",
  "aux2",
  "mix_minus",
  "stream",
  "record",
];
const AUDIO_INPUT_ROLES = ["aux_in", "mic"];
const SETTINGS_LS_KEY = "mq_radio_audio_outputs_v2";
const WELCOME_LS_KEY = "mq_radio_welcome_dismissed_v1";
const DESKTOP_VERSION_FALLBACK = "0.1.2";
const VOCLONER_LS_KEY = "mq_radio_vocloner_v1";
const VOCLONER_URL = "https://vocloner.com/";

const DEFAULT_AUDIO_ROUTES = {
  program: "builtin",
  monitor: "builtin",
  headphones: "usb",
  aux1: "none",
  aux2: "none",
  mix_minus: "usb",
  stream: "same_as_program",
  record: "none",
};

const DEFAULT_AUDIO_INPUTS = {
  aux_in: "none",
  mic: "none",
};

const DEFAULT_INSERT = {
  slot: "none",
  mode: "native_when_empty",
  label: "(none) — Native processing",
};

/** Live device catalogue from /api/audio/devices (CoreAudio on Mac, mock elsewhere). */
let liveAudioDevices = {
  source: "mock",
  devices: MOCK_AUDIO_DEVICES,
  input_devices: MOCK_INPUT_DEVICES,
  insert_options: INSERT_OPTIONS,
  note: "",
};

const DEFAULT_VOCLONER = {
  voice_renderer: "vocloner",
  preferred_model: "",
  notes:
    "Matt Vocloner Basic Yearly (~1.2M chars/year). Default voice renderer — no public API; paste approved script in Vocloner, export WAV, drop into library/VT slot.",
  url: VOCLONER_URL,
};

let playoutMode = "AUTO";
let lastStatus = null;
let lastEvents = null;
let selectedEventId = null;
let selectedPosition = null;
/** Living Log presentation filter — does not mutate committed log */
let logFilter = { type: "", artist: "", title: "", chain: "" };
/** Brief "NOW" flash after intro countdown hits zero (ASSIST/LIVE only) */
let vocalsHitUntil = 0;
window.mqSelectedEventId = null;
window.mqSelectedPosition = null;
window.mqLastEvents = null;

/** Local timer extrapolation state synced from /api/status timing */
let timingSnap = {
  playing: false,
  eventId: null,
  duration_ms: 0,
  elapsed_ms: 0,
  remaining_ms: 0,
  progress: 0,
  intro_ms: 0,
  event_type: "",
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

  if (stateEl) {
    stateEl.className = `deck-state ${stateClass || ""}`;
    stateEl.textContent = stateText || "—";
  }

  if (!event) {
    if (typeEl) { typeEl.textContent = "—"; typeEl.className = "deck-type"; }
    if (titleEl) {
      titleEl.textContent = prefix === "deck-a" ? "No cart cued (import + generate)" : "No next cart";
      titleEl.title = "Import audio + Clocks → Generate hour to fill decks";
    }
    if (artistEl) artistEl.textContent = "Import audio · Clocks → Generate";
    if (chainEl) chainEl.textContent = "—";
    if (durEl) durEl.textContent = "0:00";
    if (meterEl) meterEl.className = "meter-bar idle";
    if (endingEl) {
      endingEl.textContent = "—";
      endingEl.className = "timer-ending";
    }
    if (prefix === "deck-a") {
      const elE = document.getElementById("deck-a-elapsed");
      const elR = document.getElementById("deck-a-remaining");
      if (elE) elE.textContent = "0:00.0";
      if (elR) elR.textContent = "0:00.0";
    }
    clearEndRamp(deckEl, meterEl);
    return;
  }

  const tl = typeLabel(event.event_type);
  if (typeEl) {
    typeEl.textContent = tl;
    typeEl.className = `deck-type tag-${event.event_type || ""} tag-${tl}`;
  }
  if (titleEl) {
    titleEl.textContent = event.title || "—";
    titleEl.title = event.title || "";
  }
  if (artistEl) {
    artistEl.textContent = event.artist || "—";
    artistEl.title = [event.artist, event.title, fmtDur(event.duration_ms)].filter(Boolean).join(" — ");
  }
  if (chainEl) chainEl.textContent = `${event.chain_mode || "—"}/${event.timing_mode || "—"}`;
  if (durEl) durEl.textContent = fmtDur(event.duration_ms);
  if (meterEl) {
    meterEl.className = (stateClass === "onair" || stateClass === "fading") ? "meter-bar progressing" : "meter-bar idle";
  }

  if (endingEl) {
    endingEl.textContent = endingDisplay(event);
    endingEl.className = `timer-ending ending-${event.ending_type || ""}`;
  }
}

/**
 * Studio clock TO TIME / ETM — mirrors mq_radio.living_log.to_time_payload.
 *
 * Assumptions:
 * - Prefer next Living Log ETM (zero-duration HIT from hour clock).
 * - Else next future HIT/HARD timing_mode event (top-of-hour ID, stopset, …).
 * - scheduled_at is naive local wall time matching the studio clock.
 * - 2s grace keeps the marker stable across the exact second.
 */
function parseSchedMs(iso) {
  if (!iso) return NaN;
  let t = String(iso).trim();
  if (t.endsWith("Z")) t = t.slice(0, -1);
  // Treat as local wall time (no timezone) — matches generator / studio clock
  const m = t.match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})/
  );
  if (m) {
    return new Date(
      Number(m[1]),
      Number(m[2]) - 1,
      Number(m[3]),
      Number(m[4]),
      Number(m[5]),
      Number(m[6])
    ).getTime();
  }
  return Date.parse(iso);
}

function pickNextHardMarker(events, upcoming, nowMs) {
  const now = nowMs != null ? nowMs : Date.now();
  const grace = 2000;
  const pool = [];
  const seen = new Set();
  for (const e of [].concat(events || []).concat(upcoming || [])) {
    if (!e) continue;
    if (e.id != null && seen.has(e.id)) continue;
    if (e.id != null) seen.add(e.id);
    pool.push(e);
  }
  function collect(pred) {
    return pool
      .filter(pred)
      .map((e) => ({ e, t: parseSchedMs(e.scheduled_at) }))
      .filter((x) => !Number.isNaN(x.t) && x.t >= now - grace)
      .sort((a, b) => a.t - b.t);
  }
  const etms = collect((e) => e.event_type === "ETM");
  if (etms.length) return { marker: etms[0].e, at: etms[0].t, kind: "ETM" };
  const hits = collect(
    (e) =>
      e.event_type !== "ETM" &&
      (e.timing_mode === "HIT" || e.timing_mode === "HARD")
  );
  if (hits.length) {
    const kind = hits[0].e.timing_mode || "HIT";
    return { marker: hits[0].e, at: hits[0].t, kind };
  }
  return null;
}

function formatToTime(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "--:--";
  const late = seconds < 0;
  const abs = Math.abs(seconds);
  const h = Math.floor(abs / 3600);
  const m = Math.floor((abs % 3600) / 60);
  const s = abs % 60;
  const body =
    h > 0
      ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
      : `${m}:${String(s).padStart(2, "0")}`;
  return late ? `LATE ${body}` : body;
}

function updateETM(events, upcoming) {
  const etmEl = document.getElementById("etm-readout");
  const toEl = document.getElementById("to-time");
  const kindEl = document.getElementById("etm-kind");
  const sub = document.querySelector(".clock-sub");
  const picked = pickNextHardMarker(events, upcoming);
  if (sub) {
    sub.classList.remove("late", "hit-fallback");
  }
  if (!picked) {
    if (etmEl) etmEl.textContent = "NONE";
    if (toEl) toEl.textContent = "--:--";
    if (kindEl) kindEl.textContent = "—";
    return;
  }
  const { marker, at, kind } = picked;
  const now = Date.now();
  const seconds = Math.floor((at - now) / 1000);
  const air = fmtAirtime(marker.scheduled_at);
  if (etmEl) {
    etmEl.textContent = kind === "ETM" ? air : `${kind} ${air}`;
  }
  if (toEl) toEl.textContent = formatToTime(seconds);
  if (kindEl) {
    const label = marker.title || marker.notes || marker.event_type || kind;
    kindEl.textContent = label;
    kindEl.title = `${kind} @ ${air} — ${label}`;
  }
  if (sub) {
    if (seconds < 0) sub.classList.add("late");
    if (kind !== "ETM") sub.classList.add("hit-fallback");
  }
}

/** @deprecated name kept for callers — delegates to hard-marker picker */
function pickNextEtm(events, upcoming) {
  const p = pickNextHardMarker(events, upcoming);
  return p ? p.marker : null;
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
  if (!st || typeof st !== "object") return;
  const t = st.timing || {};
  const playing = !!(t.playing || st.running);
  const nowEv = st.now;
  const onAir = nowEv && nowEv.status === "ON_AIR";
  const nextId = onAir ? nowEv.id : null;
  const sameCart = timingSnap && timingSnap.eventId === nextId;
  timingSnap = {
    playing: playing && !!onAir,
    eventId: nextId,
    duration_ms: Number(t.duration_ms || (onAir && nowEv.duration_ms) || 0),
    elapsed_ms: Number(t.elapsed_ms || 0),
    remaining_ms: Number(t.remaining_ms || 0),
    progress: Number(t.progress || 0),
    intro_ms: Number(
      (t.intro_ms != null && t.intro_ms !== "" ? t.intro_ms : null) ??
        (onAir && nowEv && nowEv.intro_ms) ??
        0
    ),
    end_pulse_ms: Number(
      t.end_pulse_ms != null
        ? t.end_pulse_ms
        : (onAir && nowEv.outro_ms) || 0
    ),
    event_type: (t.event_type || (onAir && nowEv.event_type) || "").toUpperCase(),
    in_intro: !!t.in_intro,
    talk_up_remaining_ms: Number(t.talk_up_remaining_ms || 0),
    vocals_in: !!t.vocals_in,
    talk_up_applicable: t.talk_up_applicable !== undefined ? !!t.talk_up_applicable : undefined,
    syncedAt: Date.now(),
    _pulseSent: sameCart ? !!timingSnap._pulseSent : false,
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


function updateVocalsInPopup(live) {
  const popup = document.getElementById("vocals-in-popup");
  const countEl = document.getElementById("vocals-in-count");
  const modeEl = document.getElementById("vocals-in-mode");
  const subEl = document.getElementById("vocals-in-sub");
  if (!popup || !countEl) return;

  // Talk-up is ASSIST / LIVE only — never in AUTO (Maestro-style intro countdown)
  const assistLike = playoutMode === "ASSIST" || playoutMode === "LIVE";
  const introMs = Number(timingSnap.intro_ms || 0);
  const et = (timingSnap.event_type || "").toUpperCase();
  const talkUpTypes =
    timingSnap.talk_up_applicable === true
      ? true
      : timingSnap.talk_up_applicable === false
        ? false
        : et === "MUSIC" || et === "PROMO" || et === "VOICE_TRACK" || et === "VT" || et === "";
  const inIntro =
    assistLike &&
    timingSnap.playing &&
    talkUpTypes &&
    introMs > 0 &&
    live.elapsed_ms < introMs;

  if (modeEl) {
    modeEl.textContent = playoutMode === "LIVE" ? "LIVE" : "ASSIST";
    modeEl.classList.toggle("mode-live", playoutMode === "LIVE");
  }

  // Just crossed intro → brief NOW flash (ASSIST/LIVE only)
  if (
    assistLike &&
    timingSnap.playing &&
    talkUpTypes &&
    introMs > 0 &&
    live.elapsed_ms >= introMs &&
    live.elapsed_ms < introMs + 400 &&
    vocalsHitUntil < Date.now()
  ) {
    vocalsHitUntil = Date.now() + 900;
  }

  const hitNow = assistLike && Date.now() < vocalsHitUntil;
  if (!inIntro && !hitNow) {
    popup.hidden = true;
    popup.classList.remove("urgent", "critical", "hit-now");
    return;
  }

  popup.hidden = false;
  if (hitNow && !inIntro) {
    countEl.textContent = "NOW";
    popup.classList.remove("urgent", "critical");
    popup.classList.add("hit-now");
    if (subEl) subEl.textContent = "VOCALS · INTRO END";
    return;
  }

  // Prefer server talk-up remaining when present (same clock as end-pulse)
  const serverLeft = Number(timingSnap.talk_up_remaining_ms);
  const leftMs =
    timingSnap.in_intro && Number.isFinite(serverLeft) && serverLeft >= 0
      ? Math.max(0, serverLeft - Math.max(0, live.elapsed_ms - timingSnap.elapsed_ms))
      : Math.max(0, introMs - live.elapsed_ms);
  // Maestro-style one-decimal countdown (tenths), never negative
  const tenths = Math.max(0, leftMs / 1000);
  countEl.textContent = tenths.toFixed(1);
  const whole = Math.ceil(tenths);
  popup.classList.remove("hit-now");
  popup.classList.toggle("urgent", whole <= 5 && whole > 2);
  popup.classList.toggle("critical", whole <= 2);
  if (subEl) {
    const introSec = (introMs / 1000).toFixed(1);
    subEl.textContent = `TALK UP · INTRO ${introSec}s · cart intro_ms`;
  }
}


let lastVu = { left: 0, right: 0, playing: false };

let vuPeakHold = { left: 0, right: 0, at: 0 };

function _paintVuLeds(containerId, level, peak) {
  const root = document.getElementById(containerId);
  if (!root) return;
  const leds = root.querySelectorAll(".vu-led");
  const n = leds.length || 20;
  const lit = Math.round(Math.max(0, Math.min(1, level)) * n);
  const peakIdx = Math.round(Math.max(0, Math.min(1, peak)) * n) - 1;
  leds.forEach((el, i) => {
    el.classList.remove("on", "g", "y", "r", "peak");
    if (i < lit) {
      el.classList.add("on");
      const pct = (i + 1) / n;
      if (pct >= 0.9) el.classList.add("r");
      else if (pct >= 0.75) el.classList.add("y");
      else el.classList.add("g");
    }
    if (i === peakIdx && peakIdx >= 0) el.classList.add("peak");
  });
}

function applyVu(vu) {
  if (!vu) return;
  // Idle must be fully dark — never paint synthetic glow when not playing
  const playing = !!vu.playing;
  const normalized = playing
    ? vu
    : { playing: false, left: 0, right: 0, peak_left: 0, peak_right: 0 };
  lastVu = normalized;
  const panel = document.getElementById("vu-panel");
  const l = playing ? Math.max(0, Math.min(1, Number(vu.left) || 0)) : 0;
  const r = playing ? Math.max(0, Math.min(1, Number(vu.right) || 0)) : 0;
  const now = Date.now();
  if (l >= vuPeakHold.left || now - vuPeakHold.at > 1200) vuPeakHold.left = l;
  if (r >= vuPeakHold.right || now - vuPeakHold.at > 1200) vuPeakHold.right = r;
  if (l >= vuPeakHold.left || r >= vuPeakHold.right) vuPeakHold.at = now;
  // Slow peak fall
  if (now - vuPeakHold.at > 400) {
    vuPeakHold.left = Math.max(l, vuPeakHold.left * 0.92);
    vuPeakHold.right = Math.max(r, vuPeakHold.right * 0.92);
  }
  if (!playing) {
    vuPeakHold.left = 0;
    vuPeakHold.right = 0;
  }
  _paintVuLeds("vu-left-leds", playing ? l : 0, playing ? vuPeakHold.left : 0);
  _paintVuLeds("vu-right-leds", playing ? r : 0, playing ? vuPeakHold.right : 0);
  const peakEl = document.getElementById("vu-peak-read");
  if (peakEl) {
    const db = (x) => (x <= 0.001 ? "-∞" : `${(20 * Math.log10(x)).toFixed(1)}dB`);
    peakEl.textContent = playing
      ? `PK ${db(Math.max(vuPeakHold.left, vuPeakHold.right))}`
      : "IDLE";
  }
  if (panel) panel.classList.toggle("playing", playing);
}

function synthVuLocal(playing) {
  if (!playing) {
    return { playing: false, left: 0, right: 0 };
  }
  const t = Date.now() / 1000;
  const env = 0.55 + 0.35 * Math.sin((timingSnap.progress || 0.5) * Math.PI);
  const left = Math.min(1, env * (0.72 + 0.28 * Math.sin(t * 9.3)));
  const right = Math.min(1, env * (0.70 + 0.30 * Math.sin(t * 11.1 + 0.7)));
  return { playing: true, left, right };
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
    applyVu(lastStatus && lastStatus.vu ? lastStatus.vu : synthVuLocal(false));
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
  const analyserVu =
    window.MQProgramAudio && typeof window.MQProgramAudio.getVu === "function"
      ? window.MQProgramAudio.getVu()
      : null;
  if (analyserVu && analyserVu.source === "analyser" && analyserVu.playing) {
    applyVu(analyserVu);
  } else if (lastStatus && lastStatus.vu && lastStatus.vu.playing) {
    applyVu({
      playing: true,
      left: synthVuLocal(true).left,
      right: synthVuLocal(true).right,
    });
  } else {
    applyVu(synthVuLocal(true));
  }

  // End-pulse: AUTO advances when remaining enters pulse window (not only EOF)
  const pulseMs = Number(
    (timingSnap.end_pulse_ms != null
      ? timingSnap.end_pulse_ms
      : lastStatus && lastStatus.timing && lastStatus.timing.end_pulse_ms) || 0
  );
  // Treat missing pulse as EOF-only (0); tiny pulses get a 50ms floor so AUTO still chains
  const pulseWindow = pulseMs > 0 ? Math.max(50, pulseMs) : 0;
  if (
    timingSnap.playing &&
    timingSnap.duration_ms > 0 &&
    live.remaining_ms <= pulseWindow &&
    (pulseWindow > 0 || live.remaining_ms <= 0) &&
    !timingSnap._pulseSent
  ) {
    timingSnap._pulseSent = true;
    // Flash once, then clear so deck doesn't stick in end-ramp red after fire
    if (window.MQProgramAudio) {
      if (window.MQProgramAudio.flashEndPulse) window.MQProgramAudio.flashEndPulse("A");
      setTimeout(() => {
        if (window.MQProgramAudio.clearDeckPulse) window.MQProgramAudio.clearDeckPulse("A");
        const deckEl = document.getElementById("deck-a");
        const meterEl = document.getElementById("deck-a-meter");
        if (typeof clearEndRamp === "function") clearEndRamp(deckEl, meterEl);
      }, 450);
    }
    if (playoutMode === "AUTO") {
      fetch("/api/pulse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: false }),
      })
        .then(() => refresh())
        .catch(() => refresh());
    } else {
      // ASSIST/LIVE: arm GO on next deck (flash already fired above)
      fetch("/api/pulse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: false }),
      })
        .then(() => refresh())
        .catch(() => refresh());
    }
  }

  // When local timer hits zero, refresh so finish_if_due advances the log
  if (live.remaining_ms <= 0 && timingSnap.duration_ms > 0) {
    timingSnap.playing = false;
    refresh();
  }
}

async function refresh() {
  const dateEl = document.getElementById("log-date");
  const date = (dateEl && dateEl.value) || todayISO();
  let st = null;
  try {
    const r = await fetch(`/api/status?date=${date}`);
    if (!r.ok) throw new Error(`status HTTP ${r.status}`);
    st = await r.json();
  } catch (err) {
    const msg = document.getElementById("engine-msg");
    if (msg) setEngineMsgOperator("status poll failed — engine offline?", { kind: "error" });
    return;
  }
  if (!st || typeof st !== "object") {
    const msg = document.getElementById("engine-msg");
    if (msg) setEngineMsgOperator("status incomplete", { kind: "error" });
    return;
  }

  try {
    lastStatus = st;
    const np = st.now || null;
    const up = Array.isArray(st.upcoming) ? st.upcoming : [];

    const onAir = !!(np && np.status === "ON_AIR");
    const decks = st.decks && typeof st.decks === "object" ? st.decks : {};
    const active = String(st.active_deck || decks.active || "A").toUpperCase();
    const overlap = !!(st.overlap_active || decks.overlap_active);
    const assistGo = !!(st.assist_go_ready || decks.assist_go_ready);
    const fading = decks.fading || null;

    // Build display events for A/B from dual-deck session when present
    function deckEventFromSlot(slot, fallback) {
      if (!slot) return fallback;
      return {
        id: slot.event_id,
        title: slot.title,
        artist: slot.artist,
        event_type: slot.event_type,
        duration_ms: slot.duration_ms,
        intro_ms: slot.intro_ms,
        outro_ms: slot.end_pulse_ms,
        ending_type: slot.role === "fading" ? "FADE" : undefined,
        ending_label: slot.role === "fading" ? "SEGUE FADE" : undefined,
        chain_mode: slot.role === "fading" ? "XFADE" : "SEQ",
        timing_mode: overlap ? "OVERLAP" : "AUTO",
        status: slot.role === "program" ? "ON_AIR" : slot.role === "fading" ? "FADING" : "",
        playable_url: slot.playable_url,
      };
    }

    let evA;
    let evB;
    let stateA;
    let stateB;
    let labelA;
    let labelB;

    if (onAir && (decks.a || decks.b || decks.program)) {
      evA = deckEventFromSlot(decks.a, active === "A" ? np : null);
      evB = deckEventFromSlot(decks.b, active === "B" ? np : null);
      if (active === "A") {
        stateA = "onair"; labelA = "ON AIR";
        if (overlap && fading && (fading.deck || "").toUpperCase() === "B") {
          stateB = "fading"; labelB = "FADING";
        } else if (assistGo) {
          stateB = "go"; labelB = "GO";
          evB = evB || up[0] || null;
        } else {
          stateB = "next"; labelB = "NEXT";
          evB = evB || up[0] || null;
        }
      } else {
        stateB = "onair"; labelB = "ON AIR";
        if (overlap && fading && (fading.deck || "").toUpperCase() === "A") {
          stateA = "fading"; labelA = "FADING";
        } else if (assistGo) {
          stateA = "go"; labelA = "GO";
          evA = evA || up[0] || null;
        } else {
          stateA = "next"; labelA = "NEXT";
          evA = evA || up[0] || null;
        }
      }
    } else {
      evA = np;
      evB = up[0] || null;
      stateA = onAir ? "onair" : "onair";
      labelA = onAir ? "ON AIR" : "CUED";
      stateB = assistGo ? "go" : "next";
      labelB = assistGo ? "GO" : "NEXT";
    }

    fillDeck("deck-a", evA, stateA, labelA);
    if (!onAir && np && stateA !== "fading") {
      const aState = document.getElementById("deck-a-state");
      if (aState) {
        aState.className = "deck-state next";
        aState.textContent = "CUED";
      }
    }
    fillDeck("deck-b", evB, stateB, labelB);
    // READY: when B is fading/GO, promote upcoming[0] into C
    let cEv = up[1] || null;
    if (overlap && fading) {
      cEv = up[0] || null;
    } else if (assistGo) {
      cEv = up[1] || null;
    }
    fillDeck("deck-c", cEv, "ready", "READY");

    // Visual overlap / GO classes
    const deckAEl = document.getElementById("deck-a");
    const deckBEl = document.getElementById("deck-b");
    if (deckAEl) {
      deckAEl.classList.toggle("is-program", active === "A" && onAir);
      deckAEl.classList.toggle("is-fading", stateA === "fading");
      deckAEl.classList.toggle("assist-go", stateA === "go");
    }
    if (deckBEl) {
      deckBEl.classList.toggle("is-program", active === "B" && onAir);
      deckBEl.classList.toggle("is-fading", stateB === "fading");
      deckBEl.classList.toggle("assist-go", stateB === "go");
    }

    const xfadeEl = document.getElementById("segue-status");
    if (xfadeEl) {
      if (overlap && st.segue) {
        const ms = st.segue.crossfade_ms || 0;
        const duck = st.segue.duck_db;
        xfadeEl.textContent = `SEGUE ${ms}ms` + (duck != null ? ` · duck ${duck}dB` : "");
      } else if (assistGo) {
        xfadeEl.textContent = "ASSIST GO — press NEXT / Space";
      } else {
        xfadeEl.textContent = "";
      }
    }

    syncTimingFromStatus(st);
    if (window.MQProgramAudio) {
      window.MQProgramAudio.syncFromStatus(st).catch(() => {});
      const av = window.MQProgramAudio.getVu && window.MQProgramAudio.getVu();
      if (av && av.playing && av.source === "analyser") applyVu(av);
      else if (st.vu) applyVu(st.vu);
    } else if (st.vu) {
      applyVu(st.vu);
    }
    tickTimers();

    const lampOn = document.getElementById("lamp-onair");
    const lampReady = document.getElementById("lamp-ready");
    if (lampOn) lampOn.classList.toggle("lit", !!onAir);
    if (lampReady) lampReady.classList.toggle("lit", !!up[0]);
    const procSt = document.getElementById("proc-status");
    if (procSt && st.processing) {
      procSt.textContent = `PROC: ${st.processing.summary || st.processing.template || "—"}`;
      procSt.title = st.processing.topology || "On-air processing";
    }
    // Mix-minus subtract status (from audio_route; browser reports live graph)
    const mm = (st.audio_route && st.audio_route.mix_minus) || {};
    const mmHint = document.getElementById("mix-minus-hint");
    if (mmHint) {
      if (mm.subtract_active) {
        mmHint.textContent = "Subtract live (program − aux)";
      } else if (mm.paired) {
        mmHint.textContent = "Paired — waiting Aux capture";
      } else {
        mmHint.textContent = "Program − Aux when capture live";
      }
    }
    if (window.MQProgramAudio && window.MQProgramAudio.getMixMinus) {
      const localMm = window.MQProgramAudio.getMixMinus();
      if (localMm && localMm.subtract_active && !mm.subtract_active) {
        // local graph ahead of next status poll — keep honest
        if (mmHint) mmHint.textContent = "Subtract live (local graph)";
      }
    }
    const engMsg = document.getElementById("engine-msg");
    if (st.running && onAir && engMsg) {
      // Don't clobber media-missing / operator hints; only fill idle text
      const cur = (engMsg.textContent || "").trim();
      if (!cur || cur === "Engine idle" || cur.startsWith("Engine idle")) {
        setEngineMsgOperator("playing", { kind: "ok" });
      }
    } else if (!st.running && engMsg) {
      const cur = (engMsg.textContent || "").trim();
      // First-run: if idle with no carts, nudge once without clobbering richer hints
      const noCart = !(st.now) && !(Array.isArray(st.upcoming) && st.upcoming.length);
      if (noCart && (!cur || cur === "Engine idle" || cur === "ON AIR — playing" || cur === "playing")) {
        setEngineMsgOperator("Engine idle", { kind: "hint" });
      }
    }

    let events = [];
    try {
      const log = await fetch(`/api/log?date=${date}`).then((r) => r.json());
      events = (log && Array.isArray(log.events)) ? log.events : [];
    } catch (_) {
      events = lastEvents || [];
    }
    lastEvents = events;
    window.mqLastEvents = events;
    const logCount = document.getElementById("log-count");
    if (logCount) logCount.textContent = `${events.length} events`;

    updateETM(events, up);
    if (typeof window.renderHotkeyBank === "function") window.renderHotkeyBank(up);
    else buildHotkeys(up);

    renderLivingLog(events, np, up);
  } catch (err) {
    console.warn("status poll apply failed", err);
    const msg = document.getElementById("engine-msg");
    if (msg) setEngineMsgOperator("status partial — desk kept alive", { kind: "error" });
  }
}


function eventMatchesLogFilter(e) {
  const t = (logFilter.type || "").toUpperCase();
  const artist = (logFilter.artist || "").trim().toLowerCase();
  const title = (logFilter.title || "").trim().toLowerCase();
  const chain = (logFilter.chain || "").trim().toLowerCase();
  if (t) {
    const et = String(e.event_type || "").toUpperCase();
    if (t === "VT" || t === "VOICE_TRACK") {
      if (et !== "VOICE_TRACK") return false;
    } else if (et !== t) {
      return false;
    }
  }
  if (artist && !String(e.artist || "").toLowerCase().includes(artist)) return false;
  if (title && !String(e.title || "").toLowerCase().includes(title)) return false;
  if (chain && !String(e.chain_mode || "").toLowerCase().includes(chain)) return false;
  return true;
}

function readLogFilterFromDom() {
  const typeEl = document.getElementById("log-filter-type");
  const artistEl = document.getElementById("log-filter-artist");
  const titleEl = document.getElementById("log-filter-title");
  const chainEl = document.getElementById("log-filter-chain");
  logFilter = {
    type: typeEl ? typeEl.value : "",
    artist: artistEl ? artistEl.value : "",
    title: titleEl ? titleEl.value : "",
    chain: chainEl ? chainEl.value : "",
  };
}

function renderLivingLog(events, np, up) {
  const body = document.getElementById("log-body");
  if (!body) return;
  const all = events || lastEvents || [];
  const filtered = all.filter(eventMatchesLogFilter);
  const countEl = document.getElementById("log-filter-count");
  if (countEl) {
    const active =
      logFilter.type || logFilter.artist || logFilter.title || logFilter.chain;
    countEl.textContent = active
      ? `showing ${filtered.length} / ${all.length}`
      : "";
  }
  body.innerHTML = "";
  const nextPos = up && up[0] ? up[0].position : null;
  const nowPlaying = np || (lastStatus && lastStatus.now) || null;

  if (!all.length) {
    const tr = document.createElement("tr");
    tr.className = "log-row log-empty-hint";
    tr.innerHTML = `<td colspan="10" class="log-empty">Living Log is empty (normal on first run) — <strong>Import audio</strong>, open <strong>Clocks</strong> → Generate hour (or Sample hour), <strong>Settings</strong> → audio route, then <strong>PLAY</strong>. Mac ZIP blocked or “damaged”? Run <code>Open MQ Radio.command</code> once (Gatekeeper), then reopen — see README-INSTALL.txt.</td>`;
    body.appendChild(tr);
    return;
  }
  if (!filtered.length) {
    const tr = document.createElement("tr");
    tr.className = "log-row log-empty-hint";
    tr.innerHTML = `<td colspan="10" class="log-empty">No events match this filter — clear filters above to see ${all.length} event(s).</td>`;
    body.appendChild(tr);
    return;
  }

  filtered.forEach((e) => {
    const tr = document.createElement("tr");
    tr.className = "log-row";
    if (
      e.status === "ON_AIR" ||
      (nowPlaying && e.id === nowPlaying.id && e.status === "ON_AIR")
    ) {
      tr.classList.add("on-air");
    } else if (nextPos != null && e.position === nextPos) {
      tr.classList.add("next-up");
    } else if (e.status === "COMPLETED" || e.status === "SKIPPED") {
      tr.classList.add("completed");
    }

    const tl = typeLabel(e.event_type);
    const isVt = e.event_type === "VOICE_TRACK";
    if (isVt) tr.classList.add("vt-row");
    const scriptPreview = e.vt_preview || e.vt_script || "";
    const vtStatus = e.vt_status ? ` [${e.vt_status}]` : "";
    tr.innerHTML = `
      <td class="col-pos">${e.position}</td>
      <td class="col-time">${fmtAirtime(e.scheduled_at)}</td>
      <td class="col-type"><span class="type-tag ${e.event_type} ${tl}">${tl}</span></td>
      <td class="col-chain">${e.chain_mode || ""}</td>
      <td class="col-timing">${e.timing_mode || ""}</td>
      <td class="col-artist">${escapeHtml(e.artist || "")}</td>
      <td class="col-title">${escapeHtml(e.title || "")}</td>
      <td class="col-script" title="${escapeHtml(e.vt_script || scriptPreview)}">${
        isVt ? escapeHtml((scriptPreview || "—") + vtStatus) : ""
      }</td>
      <td class="col-dur">${fmtDur(e.duration_ms)}</td>
      <td class="col-status">${e.status || ""}</td>`;
    tr.dataset.eventId = e.id;
    tr.dataset.position = e.position;
    if (selectedEventId != null && String(e.id) === String(selectedEventId)) {
      tr.classList.add("selected");
    }
    tr.addEventListener("click", () => {
      selectedEventId = e.id;
      selectedPosition = e.position;
      window.mqSelectedEventId = e.id;
      window.mqSelectedPosition = e.position;
      body.querySelectorAll("tr.selected").forEach((r) => r.classList.remove("selected"));
      tr.classList.add("selected");
      const msg = document.getElementById("engine-msg");
      if (msg)
        msg.textContent = `Selected #${e.position} ${e.event_type || ""} ${e.title || ""}`;
    });
    tr.addEventListener("dblclick", () => openVtStudio(e, all));
    body.appendChild(tr);
  });

  const onAirRow = body.querySelector("tr.on-air");
  if (onAirRow) {
    onAirRow.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

function applyLogFilterFromDom() {
  readLogFilterFromDom();
  const up = (lastStatus && lastStatus.upcoming) || [];
  const np = lastStatus && lastStatus.now;
  renderLivingLog(lastEvents || [], np, up);
}

function initLogFilters() {
  const typeEl = document.getElementById("log-filter-type");
  const artistEl = document.getElementById("log-filter-artist");
  const titleEl = document.getElementById("log-filter-title");
  const chainEl = document.getElementById("log-filter-chain");
  const clearEl = document.getElementById("log-filter-clear");
  const onChange = () => applyLogFilterFromDom();
  if (typeEl) typeEl.addEventListener("change", onChange);
  [artistEl, titleEl, chainEl].forEach((el) => {
    if (!el) return;
    let timer = null;
    el.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(onChange, 120);
    });
  });
  if (clearEl) {
    clearEl.addEventListener("click", () => {
      if (typeEl) typeEl.value = "";
      if (artistEl) artistEl.value = "";
      if (titleEl) titleEl.value = "";
      if (chainEl) chainEl.value = "";
      applyLogFilterFromDom();
    });
  }
}

async function postAction(path) {
  if (window.MQProgramAudio) window.MQProgramAudio.resume();
  const dateEl = document.getElementById("log-date");
  const date = (dateEl && dateEl.value) || todayISO();
  let res = {};
  try {
    const r = await fetch(`${path}?date=${date}`, { method: "POST" });
    res = await r.json().catch(() => ({}));
  } catch (err) {
    setEngineMsgOperator("action failed", { kind: "error" });
    return;
  }
  const msgEl = document.getElementById("engine-msg");
  if (msgEl) {
    // Map terse engine codes; clear stale when empty so play can flow
    if (res.message != null && String(res.message).trim()) {
      setEngineMsgOperator(res.message);
    } else {
      setEngineMsgOperator("");
    }
  }
  try {
    await refresh();
  } catch (_) {
    /* refresh already self-guards */
  }
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
  fetch("/api/mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  }).catch(() => {});
  tickTimers();
}

/* —— Vocloner voice renderer (default) —— */
function loadVoclonerSettings() {
  try {
    const raw = localStorage.getItem(VOCLONER_LS_KEY);
    if (raw) return { ...DEFAULT_VOCLONER, ...JSON.parse(raw), voice_renderer: "vocloner" };
  } catch (_) {}
  return { ...DEFAULT_VOCLONER };
}

function saveVoclonerSettings(cfg) {
  const cleaned = {
    voice_renderer: "vocloner",
    preferred_model: (cfg.preferred_model || "").trim(),
    notes: (cfg.notes || "").trim(),
    url: (cfg.url || VOCLONER_URL).trim() || VOCLONER_URL,
  };
  localStorage.setItem(VOCLONER_LS_KEY, JSON.stringify(cleaned));
  fetch("/api/settings/vocloner", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cleaned),
  }).catch(() => {});
  return cleaned;
}

function populateVoclonerForm(cfg) {
  const model = document.getElementById("vocloner-model");
  const notes = document.getElementById("vocloner-notes");
  if (model) model.value = cfg.preferred_model || "";
  if (notes) notes.value = cfg.notes || "";
  const hint = document.getElementById("vt-vocloner-model");
  if (hint) {
    hint.textContent = cfg.preferred_model
      ? `· preferred: ${cfg.preferred_model}`
      : "";
  }
}

function readVoclonerForm() {
  const model = document.getElementById("vocloner-model");
  const notes = document.getElementById("vocloner-notes");
  return {
    voice_renderer: "vocloner",
    preferred_model: model ? model.value : "",
    notes: notes ? notes.value : "",
    url: VOCLONER_URL,
  };
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (_) {}
  document.body.removeChild(ta);
  return ok;
}

async function renderInVocloner(scriptText) {
  const cfg = loadVoclonerSettings();
  const script = (scriptText || "").trim();
  if (!script) {
    document.getElementById("engine-msg").textContent =
      "No script to render — open a VT or generate/approve first";
    return;
  }
  const copied = await copyTextToClipboard(script);
  const url = cfg.url || VOCLONER_URL;
  window.open(url, "_blank", "noopener,noreferrer");
  const modelTip = cfg.preferred_model
    ? ` Prefer model/voice: ${cfg.preferred_model}.`
    : "";
  document.getElementById("engine-msg").textContent = copied
    ? `Script copied → Vocloner opened.${modelTip} Paste → generate WAV → drop into library/VT slot.`
    : `Vocloner opened (copy failed — paste manually).${modelTip}`;
}

/* —— Audio output settings —— */
function loadAudioRoutes() {
  try {
    const raw = localStorage.getItem(SETTINGS_LS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      // v2 shape or legacy flat outputs
      if (parsed.outputs) {
        return {
          outputs: { ...DEFAULT_AUDIO_ROUTES, ...parsed.outputs },
          inputs: { ...DEFAULT_AUDIO_INPUTS, ...(parsed.inputs || {}) },
          insert: { ...DEFAULT_INSERT, ...(parsed.insert || {}) },
        };
      }
      return {
        outputs: { ...DEFAULT_AUDIO_ROUTES, ...parsed },
        inputs: { ...DEFAULT_AUDIO_INPUTS },
        insert: { ...DEFAULT_INSERT },
      };
    }
  } catch (_) {}
  return {
    outputs: { ...DEFAULT_AUDIO_ROUTES },
    inputs: { ...DEFAULT_AUDIO_INPUTS },
    insert: { ...DEFAULT_INSERT },
  };
}

function saveAudioRoutes(bundle) {
  const payload = {
    outputs: bundle.outputs || bundle,
    inputs: bundle.inputs || DEFAULT_AUDIO_INPUTS,
    insert: bundle.insert || DEFAULT_INSERT,
  };
  localStorage.setItem(SETTINGS_LS_KEY, JSON.stringify(payload));
  return fetch("/api/settings/audio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (data && data.audio_route && window.MQProgramAudio && window.MQProgramAudio.applyAudioRoute) {
        window.MQProgramAudio.applyAudioRoute(data.audio_route).catch(() => {});
      }
      return data;
    })
    .catch(() => null);
}

function deviceOptionsHtml(includeSameAsProgram, devices) {
  const list = devices || MOCK_AUDIO_DEVICES;
  const opts = [];
  if (includeSameAsProgram) {
    opts.push(`<option value="same_as_program">Same as Program</option>`);
  }
  list.forEach((d) => {
    if (!d || d.id == null) return;
    opts.push(`<option value="${escapeHtml(String(d.id))}">${escapeHtml(d.label || d.id)}</option>`);
  });
  return opts.join("");
}

function outSelectId(role) {
  if (role === "mix_minus") return "out-mix-minus";
  return `out-${role}`;
}

async function refreshAuInsertStatus(slot) {
  try {
    const r = await fetch("/api/settings/au-insert");
    if (!r.ok) return;
    const data = await r.json();
    const au = data.au_insert || data;
    updateAuInsertBanner(slot || au.slot, au);
  } catch (_) {}
}

async function loadMasterControlStatus() {
  const line = document.getElementById("mc-status-line");
  const detail = document.getElementById("mc-status-detail");
  if (!line) return;
  try {
    const r = await fetch("/api/settings/master-control");
    const data = r.ok ? await r.json() : null;
    if (!data) {
      line.textContent = "Master Control: status unavailable";
      return;
    }
    const bin = data.liquidsoap && data.liquidsoap.available ? "binary found" : "binary missing";
    line.textContent = `Master Control: ${data.status || "operator_pack"} · ${bin} · live Harbor: no`;
    if (detail) {
      detail.textContent = data.operator_message || "";
    }
  } catch (_) {
    line.textContent = "Master Control: status poll failed";
  }
}

async function runMasterControlDryRun() {
  const line = document.getElementById("mc-status-line");
  const detail = document.getElementById("mc-status-detail");
  setEngineMsgOperator("Master Control dry-run…", { kind: "hint" });
  try {
    const r = await fetch("/api/settings/master-control/dry-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh: false }),
    });
    const data = await r.json();
    if (line) {
      line.textContent = data.ok
        ? `Dry-run OK · ${data.status} · Harbor wired: no`
        : `Dry-run failed · ${(data.errors && data.errors[0]) || data.status}`;
    }
    if (detail) {
      detail.textContent = data.operator_message || (data.warnings || []).slice(0, 2).join(" · ");
    }
    setEngineMsgOperator(data.operator_message || (data.ok ? "Master Control dry-run OK" : "Dry-run failed"), {
      kind: data.ok ? "hint" : "error",
    });
  } catch (e) {
    setEngineMsgOperator("Master Control dry-run failed — engine offline?", { kind: "error" });
  }
}

async function runMasterControlEnsure() {
  setEngineMsgOperator("Refreshing Master Control templates…", { kind: "hint" });
  try {
    const r = await fetch("/api/settings/master-control/ensure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await r.json();
    setEngineMsgOperator(
      data.ok
        ? `Templates refreshed (${(data.written || []).length} files) — live Harbor still not wired`
        : `Template refresh failed: ${data.error || "unknown"}`,
      { kind: data.ok ? "ok" : "error" }
    );
    loadMasterControlStatus();
  } catch (_) {
    setEngineMsgOperator("Template refresh failed — engine offline?", { kind: "error" });
  }
}

async function runMasterControlStartStop(kind) {
  const path = kind === "start" ? "/api/settings/master-control/start" : "/api/settings/master-control/stop";
  setEngineMsgOperator(kind === "start" ? "Master Control start (stub)…" : "Master Control stop (stub)…", {
    kind: "hint",
  });
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await r.json();
    setEngineMsgOperator(data.operator_message || data.error || `${kind} done`, {
      kind: data.started ? "ok" : kind === "start" ? "error" : "hint",
    });
    loadMasterControlStatus();
  } catch (_) {
    setEngineMsgOperator(`Master Control ${kind} failed — engine offline?`, { kind: "error" });
  }
}

async function exportLiquidsoapHandoff() {
  setEngineMsgOperator("Exporting Liquidsoap handoff…", { kind: "hint" });
  try {
    const r = await fetch("/api/settings/processing/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await r.json();
    setEngineMsgOperator(
      data.ok
        ? `Handoff v${data.version || "?"} written — live Harbor: no`
        : `Handoff export failed: ${data.error || "unknown"}`,
      { kind: data.ok ? "ok" : "error" }
    );
    loadMasterControlStatus();
  } catch (_) {
    setEngineMsgOperator("Handoff export failed — engine offline?", { kind: "error" });
  }
}

function updateAuInsertBanner(slot, statusPayload) {
  const banner = document.getElementById("au-insert-banner");
  if (!banner) return;
  const s = String(slot || "none");
  const wantsAu = s.startsWith("au:") || (s !== "none" && s !== "native_only" && s !== "");
  const titleEl = document.getElementById("au-insert-banner-title");
  const bodyEl = document.getElementById("au-insert-banner-body");
  if (wantsAu) {
    banner.hidden = false;
    banner.removeAttribute("hidden");
    const st = statusPayload || {};
    const op =
      st.operator_message ||
      st.unavailable_message ||
      "Native chain active — AU host not loaded";
    if (titleEl) titleEl.textContent = op;
    if (bodyEl) {
      const reason = st.unavailable_reason ? ` Reason: ${st.unavailable_reason}.` : "";
      bodyEl.innerHTML =
        `Selected Audio Unit is <strong>unavailable</strong> until a real Mac AU host ships.` +
        ` Program audio continues through the <strong>native</strong> MQ chain — the plugin is` +
        ` <em>not</em> processing buffers.${reason} Real AU hosting is <strong>not</strong> Done. ` +
        `<a id="au-insert-docs-link" href="https://github.com/MQDIGITALRADIO/MQ_Grok_Build/blob/main/desktop/au_insert/README.md" target="_blank" rel="noopener noreferrer">AU insert docs</a>`;
    }
  } else {
    banner.hidden = true;
    banner.setAttribute("hidden", "");
  }
}

function populateSettingsForm(bundle, devicesPayload) {
  const routes = bundle.outputs || bundle;
  const inputs = bundle.inputs || DEFAULT_AUDIO_INPUTS;
  const insert = bundle.insert || DEFAULT_INSERT;
  const cat = devicesPayload || liveAudioDevices || {};
  const outDevices = cat.devices || MOCK_AUDIO_DEVICES;
  const inDevices = cat.input_devices || MOCK_INPUT_DEVICES;
  const insertOpts = cat.insert_options || INSERT_OPTIONS;

  AUDIO_ROLES.forEach((role) => {
    const sel = document.getElementById(outSelectId(role));
    if (!sel) return;
    const same = role === "stream" || role === "record";
    // stream/record already get Same as Program via deviceOptionsHtml flag;
    // strip duplicate same_as_program from device list when flag adds it.
    const list = same
      ? outDevices.filter((d) => d.id !== "same_as_program")
      : outDevices;
    sel.innerHTML = deviceOptionsHtml(same, list);
    const val = routes[role] || DEFAULT_AUDIO_ROUTES[role];
    if ([...sel.options].some((o) => o.value === val)) sel.value = val;
    else sel.selectedIndex = 0;
  });

  const inAux = document.getElementById("in-aux");
  if (inAux) {
    inAux.innerHTML = deviceOptionsHtml(false, inDevices);
    const v = inputs.aux_in || "none";
    if ([...inAux.options].some((o) => o.value === v)) inAux.value = v;
  }
  const inMic = document.getElementById("in-mic");
  if (inMic) {
    inMic.innerHTML = deviceOptionsHtml(false, inDevices);
    const v = inputs.mic || "none";
    if ([...inMic.options].some((o) => o.value === v)) inMic.value = v;
  }

  const ins = document.getElementById("prog-insert");
  if (ins) {
    ins.innerHTML = insertOpts
      .map((o) => `<option value="${o.id}">${escapeHtml(o.label)}</option>`)
      .join("");
    const slot = insert.slot || "none";
    if ([...ins.options].some((o) => o.value === slot)) ins.value = slot;
    else ins.value = "none";
    updateAuInsertBanner(ins.value);
    if (!ins.dataset.auBannerBound) {
      ins.dataset.auBannerBound = "1";
      ins.addEventListener("change", () => {
        updateAuInsertBanner(ins.value);
        refreshAuInsertStatus(ins.value);
      });
    }
    refreshAuInsertStatus(ins.value);
  }

  const badge = document.getElementById("audio-device-source");
  if (badge) {
    const src = cat.source || "mock";
    const backend = cat.backend ? ` · ${cat.backend}` : "";
    badge.textContent =
      src === "coreaudio"
        ? `Devices: CoreAudio${backend}`
        : `Devices: mock (Linux/CI/web)${backend}`;
    badge.dataset.source = src;
    badge.title = cat.note || "";
  }
}

function readSettingsForm() {
  const outputs = {};
  AUDIO_ROLES.forEach((role) => {
    const sel = document.getElementById(outSelectId(role));
    outputs[role] = sel ? sel.value : DEFAULT_AUDIO_ROUTES[role];
  });
  const inputs = {
    aux_in: document.getElementById("in-aux")?.value || "none",
    mic: document.getElementById("in-mic")?.value || "none",
  };
  const slot = document.getElementById("prog-insert")?.value || "none";
  const insertOpts = (liveAudioDevices && liveAudioDevices.insert_options) || INSERT_OPTIONS;
  const insertLabel = insertOpts.find((o) => o.id === slot)?.label || slot;
  const insert = {
    slot,
    mode: slot === "native_only" ? "force_native" : slot.startsWith("au:") ? "au_insert" : "native_when_empty",
    label: insertLabel,
    name: insertLabel,
  };
  return { outputs, inputs, insert };
}


function populateProcessingForm(p) {
  if (!p) return;
  const en = document.getElementById("proc-enabled");
  if (en) en.value = p.enabled === false ? "0" : "1";
  const tmpl = document.getElementById("proc-template");
  if (tmpl) tmpl.value = (p.template || "FM").toUpperCase() === "DIGITAL" ? "DIGITAL" : "FM";
  const txEl = document.getElementById("proc-tx-mode");
  if (txEl) txEl.value = p.transmission_mode ? "1" : "0";
  const st = p.stages || {};
  const map = [
    ["proc-agc", "agc"],
    ["proc-eq", "eq"],
    ["proc-mb", "multiband"],
    ["proc-exc", "exciter"],
    ["proc-lim", "limiter"],
  ];
  map.forEach(([id, key]) => {
    const el = document.getElementById(id);
    if (el) el.checked = !st[key] || st[key].enabled !== false;
  });
  const ceil = document.getElementById("proc-ceiling");
  if (ceil && st.limiter) ceil.value = st.limiter.ceiling_dbfs ?? -1;
  const agcT = document.getElementById("proc-agc-target");
  if (agcT && st.agc) agcT.value = st.agc.target_db ?? -16;
  const pre = document.getElementById("proc-preemph");
  if (pre && p.output) {
    if (!p.output.preemphasis) pre.value = "0";
    else pre.value = String(p.output.preemphasis_us || 50);
  }
  const topo = document.getElementById("proc-topology");
  if (topo) topo.textContent = p.topology || "AGC → EQ → Multiband → Exciter → Peak Limiter";
}

function readProcessingForm() {
  const template = (document.getElementById("proc-template")?.value || "FM").toUpperCase();
  const pre = document.getElementById("proc-preemph")?.value || "50";
  return {
    enabled: document.getElementById("proc-enabled")?.value !== "0",
    template,
    transmission_mode: document.getElementById("proc-tx-mode")?.value === "1",
    output: {
      path: template,
      preemphasis: pre !== "0",
      preemphasis_us: pre === "0" ? 50 : Number(pre),
    },
    stages: {
      agc: {
        enabled: !!document.getElementById("proc-agc")?.checked,
        target_db: Number(document.getElementById("proc-agc-target")?.value || -16),
      },
      eq: { enabled: !!document.getElementById("proc-eq")?.checked },
      multiband: { enabled: !!document.getElementById("proc-mb")?.checked },
      exciter: { enabled: !!document.getElementById("proc-exc")?.checked },
      limiter: {
        enabled: !!document.getElementById("proc-lim")?.checked,
        ceiling_dbfs: Number(document.getElementById("proc-ceiling")?.value || -1),
      },
    },
  };
}

async function loadProcessingSettings() {
  try {
    const data = await fetch("/api/settings/processing").then((r) => (r.ok ? r.json() : null));
    if (data) populateProcessingForm(data);
    return data;
  } catch (e) {
    return null;
  }
}

async function applyProcessingTemplate(name) {
  const res = await fetch("/api/settings/processing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apply_template: name, template: name }),
  }).then((r) => r.json());
  if (res && res.ok !== false) {
    populateProcessingForm(res);
    const st = document.getElementById("proc-status");
    if (st) st.textContent = `PROC: ${res.summary || name}`;
    if (window.MQProgramAudio) {
      window.MQProgramAudio.applyProcessing(res);
      window.MQProgramAudio.auditionTemplate(res).catch(() => {});
    }
    document.getElementById("engine-msg").textContent =
      `Loaded ${name} processing template (audition on program bus)`;
  }
}

async function fetchAudioDevices() {
  try {
    const data = await fetch("/api/audio/devices").then((r) => (r.ok ? r.json() : null));
    if (data && Array.isArray(data.devices)) {
      liveAudioDevices = {
        source: data.source || "mock",
        devices: data.devices,
        input_devices: data.input_devices || MOCK_INPUT_DEVICES,
        insert_options: data.insert_options || INSERT_OPTIONS,
        note: data.note || "",
        backend: data.backend || data.source || "",
        platform: data.platform || "",
      };
    }
  } catch (_) {
    /* keep last / mock */
  }
  return liveAudioDevices;
}

async function openSettings() {
  await fetchAudioDevices();
  populateSettingsForm(loadAudioRoutes(), liveAudioDevices);
  populateVoclonerForm(loadVoclonerSettings());
  loadProcessingSettings();
  fetch("/api/settings/vt-inbox")
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      const el = document.getElementById("vt-inbox-path");
      if (el && data && data.path) el.value = data.path;
    })
    .catch(() => {});
  fetch("/api/settings/library-root")
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      const el = document.getElementById("library-root-path");
      if (el && data && data.path) el.value = data.path;
    })
    .catch(() => {});
  const bd = document.getElementById("settings-backdrop");
  if (!bd) return;
  bd.classList.add("open");
  bd.setAttribute("aria-hidden", "false");
}

function closeSettings() {
  const bd = document.getElementById("settings-backdrop");
  if (!bd) return;
  bd.classList.remove("open");
  bd.setAttribute("aria-hidden", "true");
}

function initSettings() {
  const btnSettings = document.getElementById("btn-settings");
  if (btnSettings) btnSettings.onclick = openSettings;
  const btnClose = document.getElementById("btn-settings-close");
  if (btnClose) btnClose.onclick = closeSettings;
  const btnCancel = document.getElementById("btn-settings-cancel");
  if (btnCancel) btnCancel.onclick = closeSettings;
  const btnSave = document.getElementById("btn-settings-save");
  if (btnSave) btnSave.onclick = async () => {
    const msgEl = document.getElementById("engine-msg");
    const issues = [];
    const routes = readSettingsForm();
    try {
      const audioSaved = await saveAudioRoutes(routes);
      if (!audioSaved) issues.push("audio route not confirmed by server");
    } catch (e) {
      issues.push("audio route save failed");
    }
    try {
      const voc = saveVoclonerSettings(readVoclonerForm());
      populateVoclonerForm(voc);
    } catch (e) {
      issues.push("Vocloner settings");
    }
    const inboxEl = document.getElementById("vt-inbox-path");
    if (inboxEl && inboxEl.value.trim()) {
      try {
        const r = await fetch("/api/settings/vt-inbox", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: inboxEl.value.trim() }),
        });
        if (!r.ok) issues.push("VT inbox path");
      } catch (e) {
        issues.push("VT inbox path");
      }
    }
    const libEl = document.getElementById("library-root-path");
    if (libEl && libEl.value.trim()) {
      try {
        const r = await fetch("/api/settings/library-root", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: libEl.value.trim() }),
        });
        if (!r.ok) issues.push("library root");
      } catch (e) {
        issues.push("library root");
      }
    }
    try {
      const procPayload = readProcessingForm();
      const savedProc = await fetch("/api/settings/processing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(procPayload),
      }).then((r) => r.json());
      if (savedProc) {
        populateProcessingForm(savedProc);
        const st = document.getElementById("proc-status");
        if (st) st.textContent = `PROC: ${savedProc.summary || savedProc.template || "FM"}`;
        if (window.MQProgramAudio) window.MQProgramAudio.applyProcessing(savedProc);
      } else {
        issues.push("processing");
      }
    } catch (e) {
      issues.push("processing");
    }
    if (msgEl) {
      msgEl.textContent = issues.length
        ? `Settings saved with issues: ${issues.join(", ")}`
        : "Settings saved (audio + Vocloner + VT inbox + processing)";
    }
    closeSettings();
  };
  const settingsBd = document.getElementById("settings-backdrop");
  if (settingsBd) {
    settingsBd.addEventListener("click", (ev) => {
      if (ev.target.id === "settings-backdrop") closeSettings();
    });
  }
  // Prefetch device catalogue + server settings (merge over local if present)
  fetchAudioDevices().catch(() => {});
  fetch("/api/settings/audio")
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (!data) return;
      if (Array.isArray(data.devices)) {
        liveAudioDevices = {
          source: data.device_source || data.source_devices || liveAudioDevices.source,
          devices: data.devices,
          input_devices: data.input_devices || liveAudioDevices.input_devices,
          insert_options: data.insert_options || liveAudioDevices.insert_options,
          note: data.device_note || liveAudioDevices.note || "",
          backend: data.device_backend || "",
          platform: data.device_platform || "",
        };
        // Prefer dedicated device_source field from settings envelope
        if (data.device_source) liveAudioDevices.source = data.device_source;
      }
      if (data.outputs) {
        const cur = loadAudioRoutes();
        const merged = {
          outputs: { ...cur.outputs, ...data.outputs },
          inputs: { ...cur.inputs, ...(data.inputs || {}) },
          insert: { ...cur.insert, ...(data.insert || {}) },
        };
        localStorage.setItem(SETTINGS_LS_KEY, JSON.stringify(merged));
      }
    })
    .catch(() => {});
  fetch("/api/settings/vocloner")
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (data && data.voice_renderer) {
        const merged = { ...loadVoclonerSettings(), ...data, voice_renderer: "vocloner" };
        delete merged.source;
        localStorage.setItem(VOCLONER_LS_KEY, JSON.stringify(merged));
        populateVoclonerForm(merged);
      }
    })
    .catch(() => {});
  document.getElementById("btn-proc-fm")?.addEventListener("click", () => applyProcessingTemplate("FM"));
  document.getElementById("btn-proc-digital")?.addEventListener("click", () => applyProcessingTemplate("DIGITAL"));
  document.getElementById("btn-proc-export")?.addEventListener("click", () => exportLiquidsoapHandoff());
  document.getElementById("btn-mc-dry-run")?.addEventListener("click", () => runMasterControlDryRun());
  document.getElementById("btn-mc-ensure")?.addEventListener("click", () => runMasterControlEnsure());
  document.getElementById("btn-mc-start")?.addEventListener("click", () => runMasterControlStartStop("start"));
  document.getElementById("btn-mc-stop")?.addEventListener("click", () => runMasterControlStartStop("stop"));
  loadProcessingSettings();
  loadMasterControlStatus();
}



/** Map terse engine codes to first-run operator English (Mac + web). */
function operatorEngineMessage(raw) {
  const t = raw == null ? "" : String(raw).trim();
  if (!t) return "";
  const key = t.toLowerCase();
  const map = {
    "log empty": "Living Log empty — open Clocks → Generate hour (or Sample hour), or Import audio then Insert",
    "no log": "No log for this date — open Clocks → Generate hour, then PLAY",
    "mock idle": "Engine idle — Import audio, then Clocks → Generate hour",
    "engine idle": "Engine idle — Import audio, then Clocks → Generate hour",
    "stopped": "Stopped — READY for next PLAY",
    "playing": "ON AIR — playing",
    "action failed": "Action failed — is the engine running? Mac ZIP: try Open MQ Radio.command, then Refresh",
    "status incomplete": "Status incomplete — Refresh; if Mac ZIP just opened, wait for engine then Refresh",
    "status poll failed — engine offline?": "Engine offline — Mac ZIP: run Open MQ Radio.command (Gatekeeper), reopen app, then Refresh",
    "status partial — desk kept alive": "Status partial — desk kept alive; Refresh if transport looks stuck",
    "damaged": "macOS ‘damaged’ usually means quarantine — run Open MQ Radio.command, or xattr -cr the .app (README-INSTALL.txt)",
  };
  if (map[key]) return map[key];
  if (map[t]) return map[t];
  // Preserve already-friendly sentences
  if (t.length > 28 || t.includes("—") || t.includes("Import") || t.includes("Clocks")) return t;
  return t;
}

function setEngineMsgOperator(raw, opts) {
  const el = document.getElementById("engine-msg");
  if (!el) return;
  const text = operatorEngineMessage(raw);
  el.textContent = text;
  el.classList.remove("is-error", "is-hint", "is-ok");
  const kind = (opts && opts.kind) || "";
  if (kind === "error" || /offline|failed|empty|no log|no audio|missing/i.test(text)) {
    el.classList.add("is-error");
  } else if (kind === "hint" || /Import|Clocks|Generate|Gatekeeper|first/i.test(text)) {
    el.classList.add("is-hint");
  } else if (kind === "ok" || /ON AIR|playing|Stopped|playing/i.test(text)) {
    el.classList.add("is-ok");
  }
}

function setEngineMsg(text) {
  setEngineMsgOperator(text);
}

function initWelcomeTip() {
  const tip = document.getElementById("welcome-tip");
  const btn = document.getElementById("welcome-tip-dismiss");
  if (!tip) return;
  try {
    if (localStorage.getItem(WELCOME_LS_KEY) === "1") {
      tip.hidden = true;
      return;
    }
  } catch (_) {}
  tip.hidden = false;
  if (btn) {
    btn.onclick = () => {
      tip.hidden = true;
      try {
        localStorage.setItem(WELCOME_LS_KEY, "1");
      } catch (_) {}
    };
  }
}

async function initVersionBadge() {
  const el = document.getElementById("sys-build");
  if (!el) return;
  try {
    const r = await fetch("/api/version");
    const data = await r.json();
    if (data && data.label) {
      el.textContent = data.label;
      el.title = `MQ Radio ${data.version || ""} · ${data.sha || ""}`;
      return;
    }
    if (data && data.version) {
      el.textContent = data.sha ? `${data.version} · ${data.sha}` : String(data.version);
      return;
    }
  } catch (_) {}
  el.textContent = DESKTOP_VERSION_FALLBACK;
}

document.getElementById("log-date").value = todayISO();
document.getElementById("btn-refresh").onclick = refresh;
document.getElementById("btn-play").onclick = async () => {
  await postAction("/api/play");
  // Trustworthy feedback: confirm media after play
  try {
    const st = lastStatus;
    const onAir = st && st.now && st.now.status === "ON_AIR";
    const url = st && (st.playable_url || (st.now && st.now.playable_url));
    const msg = document.getElementById("engine-msg");
    if (onAir && !url && msg) {
      setEngineMsgOperator("Playing log row — no audio file on this cart (Import audio / Replace)", { kind: "error" });
    } else if (onAir && url && msg && !(msg.textContent || "").trim()) {
      setEngineMsgOperator("playing", { kind: "ok" });
    }
  } catch (_) {}
};
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
    const vtBd = document.getElementById("vt-backdrop");
    if (vtBd && vtBd.classList.contains("open")) {
      closeVtStudio();
      return;
    }
    for (const id of ["lib-backdrop", "segue-backdrop", "segment-backdrop", "hk-edit-backdrop", "settings-backdrop"]) {
      const el = document.getElementById(id);
      if (el && el.classList.contains("open")) {
        el.classList.remove("open");
        el.setAttribute("aria-hidden", "true");
        return;
      }
    }
    postAction("/api/stop");
    return;
  }
  if (ev.code === "Space") {
    ev.preventDefault();
    if (
      (playoutMode === "ASSIST" || playoutMode === "LIVE") &&
      lastStatus &&
      (lastStatus.assist_go_ready || (lastStatus.decks && lastStatus.decks.assist_go_ready))
    ) {
      fetch("/api/pulse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ go: true, force: true }),
      })
        .then(() => refresh())
        .catch(() => refresh());
      return;
    }
    postAction("/api/play");
    return;
  }
  // F-keys handled by desk_programming.js (full hotkey bank)
});

initSettings();
initVtStudio();
initLogFilters();
initWelcomeTip();
initVersionBadge();
window.mqRefresh = refresh;
window.mqSetEngineMsg = setEngineMsg;
window.mqOperatorEngineMessage = operatorEngineMessage;
window.mqOpenVtStudio = openVtStudio;
window.mqPostAction = postAction;
setInterval(tickClock, 250);
tickClock();
refresh();
setInterval(refresh, 5000);


/* —— Voice Track studio stub + AI breaks —— */
let vtContext = null;

function findNeighborMusic(events, position, dir) {
  if (!events) return null;
  const sorted = [...events].sort((a, b) => a.position - b.position);
  const idx = sorted.findIndex((e) => e.position === position);
  if (idx < 0) return null;
  if (dir < 0) {
    for (let i = idx - 1; i >= 0; i--) {
      if (sorted[i].event_type === "MUSIC") return sorted[i];
    }
  } else {
    for (let i = idx + 1; i < sorted.length; i++) {
      if (sorted[i].event_type === "MUSIC") return sorted[i];
    }
  }
  return null;
}

function openVtStudio(event, events) {
  // Click a VT row, or a transition after music (open studio on any row)
  const prev = findNeighborMusic(events, event.position, -1);
  const next =
    event.event_type === "MUSIC"
      ? event
      : findNeighborMusic(events, event.position, 1);
  const prevForScript =
    event.event_type === "MUSIC"
      ? findNeighborMusic(events, event.position, -1)
      : prev;
  const nextForScript =
    event.event_type === "MUSIC"
      ? findNeighborMusic(events, event.position, 1)
      : next;

  let hour = 12;
  try {
    hour = Number(String(event.scheduled_at).split("T")[1].split(":")[0]);
  } catch (_) {}
  const dayparts = [
    [5, 10, "morning"],
    [10, 15, "day"],
    [15, 19, "afternoon"],
    [19, 23, "evening"],
  ];
  let daypart = "overnight";
  for (const [a, b, name] of dayparts) {
    if (hour >= a && hour < b) daypart = name;
  }

  vtContext = {
    event,
    prev: prevForScript,
    next: nextForScript,
    daypart,
  };
  window.mqVtEventId = event && event.id;
  window.vtContext = vtContext;

  const fromLabel = prevForScript
    ? `${prevForScript.artist || ""} — ${prevForScript.title || ""}`
    : "(top)";
  const toLabel = nextForScript
    ? `${nextForScript.artist || ""} — ${nextForScript.title || ""}`
    : "(end)";
  document.getElementById("vt-transition").textContent = `${fromLabel}  →  ${toLabel}`;
  document.getElementById("vt-daypart").textContent = daypart;
  document.getElementById("vt-variation").textContent =
    event.vt_variation || (event.event_type === "VOICE_TRACK" ? "—" : "new");
  document.getElementById("vt-script").value =
    event.vt_script || event.vt_preview || "";
  populateVoclonerForm(loadVoclonerSettings());

  const bd = document.getElementById("vt-backdrop");
  bd.classList.add("open");
  bd.setAttribute("aria-hidden", "false");
}

function closeVtStudio() {
  const bd = document.getElementById("vt-backdrop");
  bd.classList.remove("open");
  bd.setAttribute("aria-hidden", "true");
  vtContext = null;
}

async function vtGenerateScript() {
  if (!vtContext) return;
  const payload = {
    prev_track: vtContext.prev
      ? { title: vtContext.prev.title, artist: vtContext.prev.artist }
      : null,
    next_track: vtContext.next
      ? { title: vtContext.next.title, artist: vtContext.next.artist }
      : null,
    daypart: vtContext.daypart,
    station_name: "MQ Digital",
    style: "warm",
    scheduled_at: vtContext.event.scheduled_at,
  };
  const res = await fetch("/api/vt/generate-script", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then((r) => r.json());
  document.getElementById("vt-script").value = res.script || "";
  document.getElementById("vt-variation").textContent = res.variation || "—";
  document.getElementById("engine-msg").textContent = res.skipped
    ? "AI script: silence/skip"
    : `AI script (${res.variation})`;
}

async function generateAiBreaksUi() {
  const date = document.getElementById("log-date").value || todayISO();
  document.getElementById("engine-msg").textContent = "Generating AI breaks…";
  const res = await fetch(`/api/ai-breaks/generate?date=${date}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ station_name: "MQ Digital", style: "warm" }),
  }).then((r) => r.json());
  document.getElementById("engine-msg").textContent = res.ok
    ? `AI breaks: filled ${res.filled}, inserted ${res.inserted}, drafts ${res.drafts}`
    : res.error || "AI breaks failed";
  await refresh();
}

async function approveAiBreaksUi() {
  const date = document.getElementById("log-date").value || todayISO();
  document.getElementById("engine-msg").textContent = "Approving drafts…";
  const res = await fetch(`/api/ai-breaks/approve?date=${date}`, {
    method: "POST",
  }).then((r) => r.json());
  document.getElementById("engine-msg").textContent = res.ok
    ? `Approved ${res.approved} VT draft(s) — next: Placeholder → Log (playable) or Render in Vocloner → drop WAV`
    : res.error || "Approve failed";
  await refresh();
}

async function renderPlaceholderFromLog() {
  const date = document.getElementById("log-date").value || todayISO();
  const eid = window.mqVtEventId;
  document.getElementById("engine-msg").textContent = eid
    ? `Placeholder render for event ${eid}…`
    : "Placeholder render for approved VTs…";
  const body = eid ? { event_id: eid } : { date };
  const res = await fetch(`/api/vt/render-placeholder?date=${date}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json()).catch((e) => ({ ok: false, error: String(e) }));
  if (res.ok) {
    const n = res.rendered != null ? res.rendered : res.skipped ? 0 : 1;
    const skip = res.skipped ? ` (skipped: ${res.reason || res.skipped})` : "";
    document.getElementById("engine-msg").textContent =
      res.message ||
      `Placeholder → Log: ${n} attached${skip}. Replace with Vocloner WAV when ready.`;
  } else {
    document.getElementById("engine-msg").textContent =
      res.error || "Placeholder render failed — approve drafts first";
  }
  await refresh();
}

async function runPdAssistPathUi() {
  const date = document.getElementById("log-date").value || todayISO();
  document.getElementById("engine-msg").textContent =
    "PD assist path (AI upstairs only): generate → approve → placeholder…";
  const res = await fetch(`/api/ai-breaks/operator-path?date=${date}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      station_name: "MQ Digital",
      style: "warm",
      approve: true,
      render_placeholders: true,
    }),
  }).then((r) => r.json()).catch((e) => ({ ok: false, error: String(e) }));
  document.getElementById("engine-msg").textContent = res.ok
    ? res.message ||
      `PD assist ok — placeholders ${
        (res.placeholder_render && res.placeholder_render.rendered) || 0
      }. Vocloner still the real voice.`
    : res.error || "PD assist path failed";
  await refresh();
}

async function renderVoclonerFromLog() {
  // Prefer open studio script; else first APPROVED VT with script on the date
  const studio = document.getElementById("vt-script");
  if (studio && studio.value.trim()) {
    await renderInVocloner(studio.value);
    return;
  }
  const date = document.getElementById("log-date").value || todayISO();
  const rows = await fetch(`/api/vt?date=${date}`).then((r) => r.json()).catch(() => null);
  const list = (rows && rows.voice_tracks) || [];
  const textOf = (r) =>
    (r && (r.script_text || r.script || r.body || r.vt_script || "")) || "";
  const hit =
    list.find((r) => (r.status || "").toUpperCase() === "APPROVED" && textOf(r).trim()) ||
    list.find((r) => textOf(r).trim());
  const script =
    textOf(hit) ||
    (lastEvents || [])
      .filter((e) => e.event_type === "VOICE_TRACK")
      .map((e) => e.vt_script || e.vt_preview || "")
      .find((s) => s && s.trim());
  await renderInVocloner(script || "");
}

function initVtStudio() {
  const gen = document.getElementById("btn-gen-ai");
  const appr = document.getElementById("btn-approve-ai");
  const phLog = document.getElementById("btn-render-placeholder");
  const pd = document.getElementById("btn-pd-assist");
  const renderLog = document.getElementById("btn-render-vocloner");
  if (gen) gen.onclick = generateAiBreaksUi;
  if (appr) appr.onclick = approveAiBreaksUi;
  if (phLog) phLog.onclick = renderPlaceholderFromLog;
  if (pd) pd.onclick = runPdAssistPathUi;
  if (renderLog) renderLog.onclick = renderVoclonerFromLog;
  const close = document.getElementById("btn-vt-close");
  const done = document.getElementById("btn-vt-done");
  const ai = document.getElementById("btn-vt-ai");
  const voc = document.getElementById("btn-vt-vocloner");
  const phStudio = document.getElementById("btn-vt-placeholder");
  if (close) close.onclick = closeVtStudio;
  if (done) done.onclick = closeVtStudio;
  if (ai) ai.onclick = vtGenerateScript;
  if (phStudio) phStudio.onclick = renderPlaceholderFromLog;
  if (voc) {
    voc.onclick = () =>
      renderInVocloner(document.getElementById("vt-script").value || "");
  }
  const bd = document.getElementById("vt-backdrop");
  if (bd) {
    bd.addEventListener("click", (ev) => {
      if (ev.target.id === "vt-backdrop") closeVtStudio();
    });
  }
  populateVoclonerForm(loadVoclonerSettings());
}

