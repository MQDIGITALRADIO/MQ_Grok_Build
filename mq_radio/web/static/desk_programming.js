/* Living Log edit, library picker, VT record, Segue Editor, editable hotkeys */

(function () {
  "use strict";

  let libMode = null; // insert | replace
  let libSelectedTrack = null;
  let hotkeysState = { hotkeys: [], pages: 2, slots_per_page: 16, page: 0, editMode: false };
  let hkEditSlot = null;
  let segueCtx = null;
  let mediaRecorder = null;
  let recordedChunks = [];
  let recordedBlob = null;
  let recordedUrl = null;
  let waveData = [];
  let lastVtTakeTrackId = null;
  let lastVtTakeEventId = null;

  function dateVal() {
    const el = document.getElementById("log-date");
    if (el && el.value) return el.value;
    const d = new Date();
    const z = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
  }

  function msg(t) {
    const el = document.getElementById("engine-msg");
    if (el) el.textContent = t;
  }

  function selectedEvent() {
    const id = window.mqSelectedEventId;
    const events = window.mqLastEvents || [];
    return events.find((e) => String(e.id) === String(id)) || null;
  }

  async function refresh() {
    if (typeof window.mqRefresh === "function") await window.mqRefresh();
  }

  /* —— Library picker —— */
  function openLib(mode) {
    libMode = mode;
    libSelectedTrack = null;
    const bd = document.getElementById("lib-backdrop");
    document.getElementById("lib-title").textContent =
      mode === "replace" ? "Replace from Library" : "Insert from Library";
    document.getElementById("lib-search").value = "";
    bd.classList.add("open");
    bd.setAttribute("aria-hidden", "false");
    loadLibrary("");
  }

  function closeLib() {
    const bd = document.getElementById("lib-backdrop");
    bd.classList.remove("open");
    bd.setAttribute("aria-hidden", "true");
    libMode = null;
  }

  async function loadLibrary(q) {
    const data = await fetch(`/api/library?q=${encodeURIComponent(q || "")}`).then((r) => r.json());
    const list = document.getElementById("lib-list");
    list.innerHTML = "";
    (data.tracks || []).forEach((t) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "lib-item";
      row.innerHTML = `<span class="lib-cat">${escapeHtml(t.category || t.event_type || "")}</span>
        <span class="lib-main">${escapeHtml(t.artist || "")} — ${escapeHtml(t.title || "")}</span>
        <span class="lib-dur">${fmtDur(t.duration_ms)}</span>`;
      row.onclick = () => {
        list.querySelectorAll(".lib-item.selected").forEach((x) => x.classList.remove("selected"));
        row.classList.add("selected");
        libSelectedTrack = t;
      };
      list.appendChild(row);
    });
    if (!(data.tracks || []).length) {
      list.innerHTML = `<div class="lib-empty">No tracks — run seed-demo</div>`;
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtDur(ms) {
    if (ms == null || ms === "") return "—";
    const s = Math.round(Number(ms) / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  async function confirmLib() {
    if (libMode === "replace") {
      const ev = selectedEvent();
      if (!ev) {
        msg("Select a log row first");
        return;
      }
      if (!libSelectedTrack) {
        msg("Pick a library track");
        return;
      }
      const res = await fetch("/api/log/replace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_id: ev.id, track_id: libSelectedTrack.id }),
      }).then((r) => r.json());
      msg(res.ok ? `Replaced → ${res.artist} — ${res.title}` : res.error || "Replace failed");
      closeLib();
      await refresh();
      return;
    }
    // insert
    const after =
      window.mqSelectedPosition != null ? window.mqSelectedPosition : -1;
    const body = {
      date: dateVal(),
      after_position: after,
    };
    if (libSelectedTrack) {
      body.track_id = libSelectedTrack.id;
      body.event_type = document.getElementById("lib-event-type").value || libSelectedTrack.event_type;
    } else {
      const et = document.getElementById("lib-event-type").value || "VOICE_TRACK";
      body.event_type = et;
      body.title = et === "VOICE_TRACK" ? "Manual VT" : et;
      body.artist = "MQ Digital";
    }
    const res = await fetch("/api/log/insert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());
    msg(res.ok ? `Inserted #${res.position} ${res.event_type} ${res.title || ""}` : res.error || "Insert failed");
    closeLib();
    await refresh();
  }

  async function deleteSelected() {
    const ev = selectedEvent();
    if (!ev) {
      msg("Select a log row to delete");
      return;
    }
    if (!confirm(`Delete #${ev.position} ${ev.title || ev.event_type}?`)) return;
    const res = await fetch("/api/log/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_id: ev.id }),
    }).then((r) => r.json());
    msg(res.ok ? `Deleted event ${res.deleted_id}` : res.error || "Delete failed");
    window.mqSelectedEventId = null;
    window.mqSelectedPosition = null;
    await refresh();
  }

  async function loadSampleHour() {
    msg("Loading sample hour…");
    const res = await fetch(`/api/log/sample-hour?date=${dateVal()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: dateVal(), hour: 12, clear_day: true }),
    }).then((r) => r.json());
    msg(
      res.ok
        ? `Sample hour loaded — ${res.inserted} MANUAL events (editable)`
        : res.error || "Sample hour failed"
    );
    await refresh();
  }

  /* —— VT Record —— */
  function drawWave(samples) {
    const canvas = document.getElementById("vt-wave");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#0a120a";
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "#33ff66";
    ctx.beginPath();
    const n = samples.length || 1;
    for (let i = 0; i < n; i++) {
      const x = (i / n) * w;
      const v = samples[i] || 0;
      const y = h / 2 - v * (h / 2 - 2);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    // trim markers
    const tin = Number(document.getElementById("vt-trim-in").value || 0);
    const tout = document.getElementById("vt-trim-out").value;
    const dur = recordedBlob ? guessDurationMs() : 10000;
    const x0 = (tin / Math.max(dur, 1)) * w;
    ctx.strokeStyle = "#ffb000";
    ctx.beginPath();
    ctx.moveTo(x0, 0);
    ctx.lineTo(x0, h);
    ctx.stroke();
    if (tout !== "" && tout != null) {
      const x1 = (Number(tout) / Math.max(dur, 1)) * w;
      ctx.strokeStyle = "#ff2222";
      ctx.beginPath();
      ctx.moveTo(x1, 0);
      ctx.lineTo(x1, h);
      ctx.stroke();
    }
  }

  function guessDurationMs() {
    const audio = document.getElementById("vt-playback");
    if (audio && audio.duration && isFinite(audio.duration)) return Math.round(audio.duration * 1000);
    return Math.max(waveData.length * 50, 1000);
  }

  async function startRecord() {
    const status = document.getElementById("vt-record-status");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      msg("Mic recording not available in this browser");
      status.textContent = "Unavailable";
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recordedChunks = [];
      waveData = [];
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
      mediaRecorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size) recordedChunks.push(ev.data);
      };
      mediaRecorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        recordedBlob = new Blob(recordedChunks, { type: mime });
        if (recordedUrl) URL.revokeObjectURL(recordedUrl);
        recordedUrl = URL.createObjectURL(recordedBlob);
        const audio = document.getElementById("vt-playback");
        audio.src = recordedUrl;
        audio.onloadedmetadata = () => {
          document.getElementById("vt-trim-out").value = String(Math.round(audio.duration * 1000));
          drawWave(waveData);
        };
        status.textContent = `Recorded ${(recordedBlob.size / 1024).toFixed(1)} KB`;
        document.getElementById("btn-vt-stop-rec").hidden = true;
        drawWave(waveData.length ? waveData : [0, 0.2, -0.1, 0.4, -0.3, 0.1]);
      };
      // crude level meter via Analyser
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      const src = ac.createMediaStreamSource(stream);
      const anal = ac.createAnalyser();
      anal.fftSize = 256;
      src.connect(anal);
      const buf = new Uint8Array(anal.frequencyBinCount);
      const tick = () => {
        if (!mediaRecorder || mediaRecorder.state !== "recording") {
          ac.close().catch(() => {});
          return;
        }
        anal.getByteTimeDomainData(buf);
        let peak = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          peak = Math.max(peak, Math.abs(v));
        }
        waveData.push(peak);
        if (waveData.length > 240) waveData.shift();
        drawWave(waveData);
        requestAnimationFrame(tick);
      };
      mediaRecorder.start(100);
      status.textContent = "Recording…";
      document.getElementById("btn-vt-stop-rec").hidden = false;
      requestAnimationFrame(tick);
      msg("VT mic recording…");
    } catch (err) {
      status.textContent = "Mic denied";
      msg(`Mic error: ${err.message || err}`);
    }
  }

  function stopRecord() {
    if (mediaRecorder && mediaRecorder.state === "recording") mediaRecorder.stop();
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  async function saveRecording() {
    if (!recordedBlob) {
      msg("Nothing recorded yet");
      return;
    }
    const ev = (window.vtContext && window.vtContext.event) || selectedEvent();
    // vtContext is local in app.js — use selected or studio event id from dataset
    let eventId = window.mqSelectedEventId;
    const studioOpen = document.getElementById("vt-backdrop")?.classList.contains("open");
    if (studioOpen && window.mqVtEventId) eventId = window.mqVtEventId;
    if (!eventId) {
      msg("Open/select a VT log row first");
      return;
    }
    const b64 = await blobToBase64(recordedBlob);
    const script = document.getElementById("vt-script")?.value || "";
    const res = await fetch("/api/vt/record", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_id: eventId,
        audio_b64: b64,
        mime: recordedBlob.type || "audio/webm",
        trim_in_ms: Number(document.getElementById("vt-trim-in").value || 0),
        trim_out_ms: document.getElementById("vt-trim-out").value
          ? Number(document.getElementById("vt-trim-out").value)
          : null,
        script_text: script,
      }),
    }).then((r) => r.json());
    if (res.ok) {
      lastVtTakeTrackId = res.track_id || null;
      lastVtTakeEventId = eventId;
      const cleaned = res.cleaned ? " · cleaned cut" : "";
      const cart = res.track_id ? ` · cart #${res.track_id}` : "";
      msg(`Saved VT take → ${res.audio_path}${cleaned}${cart}`);
      document.getElementById("vt-record-status").textContent =
        `Saved${cleaned || ""} — ready for Segment Editor`;
      await refresh();
    } else {
      msg(res.error || "Save failed");
    }
  }

  /** Record → Segment Editor on this take (manual announcer path). */
  async function openSegmentEditorForVtTake() {
    let eventId = window.mqVtEventId || window.mqSelectedEventId;
    // Ensure take is saved first so we have a library cart to segment
    if (recordedBlob && !lastVtTakeTrackId) {
      msg("Saving take before Segment Editor…");
      await saveRecording();
    }
    if (!lastVtTakeTrackId) {
      // Fall back: open Segment Editor filtered to VOICE_TRACK
      openSegmentEditor();
      const search = document.getElementById("seg-track-search");
      if (search) {
        search.value = "VOICE_TRACK";
        loadSegLibrary("VOICE_TRACK");
      }
      msg("Pick your VT take in Segment Editor (save a take first for auto-select)");
      return;
    }
    openSegmentEditor();
    // Pre-select the take cart
    const data = await fetch(`/api/library/track?id=${lastVtTakeTrackId}`).then((r) => r.json());
    if (data && data.ok && data.track) {
      const t = data.track;
      segSelected = t;
      document.getElementById("seg-selected").textContent =
        `VT TAKE #${t.id} ${t.artist} — ${t.title} (${fmtDur(t.duration_ms)})`;
      const tin = Number(document.getElementById("vt-trim-in")?.value || 0);
      const tout = document.getElementById("vt-trim-out")?.value;
      document.getElementById("seg-in-ms").value = String(tin);
      document.getElementById("seg-out-ms").value = String(
        tout !== "" && tout != null ? Number(tout) : t.duration_ms || 0
      );
      document.getElementById("seg-title").value = (document.getElementById("vt-script")?.value || t.title || "Voice Track").slice(0, 80);
      document.getElementById("seg-artist").value = t.artist || "Announcer";
      const et = document.getElementById("seg-event-type");
      if (et) et.value = "VOICE_TRACK";
      if (typeof updateSegLen === "function") updateSegLen();
      document.getElementById("seg-msg").textContent =
        "VT take loaded — adjust IN/OUT, then Save segment cart (attaches to log VT).";
    }
    // Also list library with this track highlighted via search
    loadSegLibrary(String(lastVtTakeTrackId));
  }

  /* —— Segue Editor —— */
  async function openSegue() {
    const ev = selectedEvent();
    if (!ev) {
      msg("Select outgoing (or VT) log row for Segue Editor");
      return;
    }
    const ctx = await fetch(`/api/segue?event_id=${ev.id}`).then((r) => r.json());
    if (!ctx.ok) {
      msg(ctx.error || "Segue context failed");
      return;
    }
    segueCtx = ctx;
    const s = ctx.segue || {};
    const lab = (e) => (e ? `${e.artist || ""} — ${e.title || e.event_type}` : "(none)");
    document.getElementById("segue-out-label").textContent = lab(ctx.outgoing);
    document.getElementById("segue-vt-label").textContent = lab(ctx.voice_track);
    document.getElementById("segue-in-label").textContent = lab(ctx.incoming);
    document.getElementById("segue-outro-mark").value = s.from_outro_mark_ms ?? ctx.defaults?.from_outro_mark_ms ?? 0;
    document.getElementById("segue-intro-mark").value = s.to_intro_mark_ms ?? ctx.defaults?.to_intro_mark_ms ?? 0;
    document.getElementById("segue-vt-in").value = s.vt_in_ms ?? 0;
    document.getElementById("segue-vt-out").value = s.vt_out_ms ?? "";
    document.getElementById("segue-duck").value = s.duck_db ?? -11;
    document.getElementById("segue-xfade").value = s.crossfade_ms ?? 0;
    document.getElementById("segue-audition-msg").textContent = "";
    const bd = document.getElementById("segue-backdrop");
    bd.classList.add("open");
    bd.setAttribute("aria-hidden", "false");
  }

  function closeSegue() {
    const bd = document.getElementById("segue-backdrop");
    bd.classList.remove("open");
    bd.setAttribute("aria-hidden", "true");
  }

  async function saveSegueUi() {
    if (!segueCtx || !segueCtx.outgoing || !segueCtx.incoming) {
      msg("Need outgoing + incoming carts");
      return;
    }
    const payload = {
      from_event_id: segueCtx.outgoing.id,
      to_event_id: segueCtx.incoming.id,
      vt_event_id: segueCtx.voice_track ? segueCtx.voice_track.id : null,
      from_outro_mark_ms: Number(document.getElementById("segue-outro-mark").value || 0),
      to_intro_mark_ms: Number(document.getElementById("segue-intro-mark").value || 0),
      vt_in_ms: Number(document.getElementById("segue-vt-in").value || 0),
      vt_out_ms: document.getElementById("segue-vt-out").value
        ? Number(document.getElementById("segue-vt-out").value)
        : null,
      duck_db: Number(document.getElementById("segue-duck").value || -11),
      crossfade_ms: Number(document.getElementById("segue-xfade").value || 0),
    };
    const res = await fetch("/api/segue/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => r.json());
    msg(res.ok ? `Segue saved (duck ${payload.duck_db} dB)` : res.error || "Segue save failed");
    if (res.ok) closeSegue();
  }

  function auditionSegue() {
    const duck = Number(document.getElementById("segue-duck").value || -11);
    const el = document.getElementById("segue-audition-msg");
    el.textContent = `Audition stub: OUT outro → duck ${duck} dB → VT → IN intro (demo tones silent OK)`;
    // Web Audio beep stub
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      const beep = (t, f, g) => {
        const o = ac.createOscillator();
        const gain = ac.createGain();
        o.frequency.value = f;
        gain.gain.value = g;
        o.connect(gain);
        gain.connect(ac.destination);
        o.start(t);
        o.stop(t + 0.18);
      };
      const now = ac.currentTime;
      beep(now, 440, 0.08);
      beep(now + 0.25, 330, 0.08 * Math.pow(10, duck / 20));
      beep(now + 0.55, 523, 0.09);
      setTimeout(() => ac.close().catch(() => {}), 1200);
    } catch (_) {}
    msg("Segue audition (stub)");
  }

  /* —— Hotkeys bank —— */
  async function loadHotkeys() {
    const data = await fetch("/api/hotkeys").then((r) => r.json()).catch(() => null);
    if (!data) return;
    hotkeysState.hotkeys = data.hotkeys || [];
    hotkeysState.pages = data.pages || 2;
    hotkeysState.slots_per_page = data.slots_per_page || 16;
    renderHotkeyBank();
  }

  async function persistHotkeys() {
    const res = await fetch("/api/hotkeys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hotkeys: hotkeysState.hotkeys }),
    }).then((r) => r.json());
    if (res.hotkeys) hotkeysState.hotkeys = res.hotkeys;
    msg(res.ok ? "Hotkeys saved" : "Hotkeys save failed");
    renderHotkeyBank();
  }

  function renderHotkeyBank() {
    const grid = document.getElementById("hotkey-grid");
    if (!grid) return;
    const spp = hotkeysState.slots_per_page || 16;
    const page = hotkeysState.page || 0;
    const start = page * spp;
    const slice = (hotkeysState.hotkeys || []).slice(start, start + spp);
    document.getElementById("hk-page-label").textContent = `Page ${page + 1}/${hotkeysState.pages}`;
    grid.innerHTML = "";
    grid.classList.toggle("edit-mode", !!hotkeysState.editMode);
    slice.forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "hotkey" + (item.empty ? " empty" : "");
      btn.draggable = !!hotkeysState.editMode;
      const keyLabel = item.key || `#${item.slot + 1}`;
      btn.innerHTML = `
        <span class="hk-key">${escapeHtml(keyLabel)}</span>
        <span class="hk-label">${escapeHtml(item.label || (item.empty ? "(empty)" : ""))}</span>
        <span class="hk-type">${escapeHtml(item.type || "")}</span>`;
      btn.onclick = () => {
        if (hotkeysState.editMode) openHkEdit(item.slot);
        else fireHotkeySlot(item, btn);
      };
      if (hotkeysState.editMode) {
        btn.ondragstart = (ev) => {
          ev.dataTransfer.setData("text/plain", String(item.slot));
        };
        btn.ondragover = (ev) => ev.preventDefault();
        btn.ondrop = (ev) => {
          ev.preventDefault();
          const from = Number(ev.dataTransfer.getData("text/plain"));
          const to = item.slot;
          swapHotkeys(from, to);
        };
      }
      grid.appendChild(btn);
    });
  }

  window.renderHotkeyBank = function () {
    if (!hotkeysState.hotkeys.length) loadHotkeys();
    else renderHotkeyBank();
  };

  async function fireHotkeySlot(item, btn) {
    if (item.empty) {
      msg(`Hotkey slot ${item.slot + 1} empty`);
      return;
    }
    if (btn) {
      btn.classList.add("fired");
      setTimeout(() => btn.classList.remove("fired"), 180);
    }
    try {
      if (window.MQProgramAudio) window.MQProgramAudio.resume();
      const res = await fetch("/api/hotkey/fire", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: item.label,
          type: item.type,
          target: item.target,
          path: item.path || null,
        }),
      }).then((r) => r.json());
      let played = false;
      if (res && res.playable_url && window.MQProgramAudio) {
        played = await window.MQProgramAudio.playOneShot(res.playable_url, res.label || item.label);
      }
      msg(
        res.message ||
          `HOTKEY ${item.key || "#" + (item.slot + 1)}: ${item.label}` +
            (played ? " · audio" : "")
      );
    } catch (e) {
      msg(`HOTKEY ${item.key || "#" + (item.slot + 1)}: ${item.label} [${item.type}]`);
    }
  }

  function swapHotkeys(a, b) {
    if (a === b) return;
    const ha = hotkeysState.hotkeys[a];
    const hb = hotkeysState.hotkeys[b];
    if (!ha || !hb) return;
    const tmp = { ...ha, slot: b };
    hotkeysState.hotkeys[b] = { ...hb, slot: a };
    hotkeysState.hotkeys[a] = tmp;
    // fix keys for page 0 F-keys
    rekeyPage0();
    persistHotkeys();
  }

  function rekeyPage0() {
    const spp = hotkeysState.slots_per_page;
    for (let i = 0; i < spp; i++) {
      const h = hotkeysState.hotkeys[i];
      if (!h) continue;
      h.key = i < 12 ? `F${i + 1}` : "";
      h.slot = i;
    }
    for (let i = spp; i < hotkeysState.hotkeys.length; i++) {
      if (hotkeysState.hotkeys[i]) {
        hotkeysState.hotkeys[i].key = "";
        hotkeysState.hotkeys[i].slot = i;
      }
    }
  }

  function openHkEdit(slot) {
    hkEditSlot = slot;
    const item = hotkeysState.hotkeys[slot] || { slot, label: "", type: "", target: null, macro: null };
    document.getElementById("hk-edit-slot").textContent = String(slot);
    document.getElementById("hk-edit-label").value = item.label || "";
    document.getElementById("hk-edit-type").value = item.type || "";
    document.getElementById("hk-edit-target").value = item.target || "";
    const pathEl = document.getElementById("hk-edit-path");
    if (pathEl) pathEl.value = item.path || "";
    document.getElementById("hk-edit-macro").value = item.macro || "";
    const bd = document.getElementById("hk-edit-backdrop");
    bd.classList.add("open");
    bd.setAttribute("aria-hidden", "false");
  }

  function closeHkEdit() {
    const bd = document.getElementById("hk-edit-backdrop");
    bd.classList.remove("open");
    bd.setAttribute("aria-hidden", "true");
    hkEditSlot = null;
  }

  function saveHkEdit() {
    if (hkEditSlot == null) return;
    const label = document.getElementById("hk-edit-label").value.trim();
    const type = document.getElementById("hk-edit-type").value;
    const target = document.getElementById("hk-edit-target").value.trim() || null;
    const pathRef = document.getElementById("hk-edit-path")?.value.trim() || null;
    const macro = document.getElementById("hk-edit-macro").value.trim() || null;
    const empty = !label && !type && !target && !pathRef && !macro;
    const key = hkEditSlot < 12 ? `F${hkEditSlot + 1}` : "";
    hotkeysState.hotkeys[hkEditSlot] = {
      slot: hkEditSlot,
      key: hkEditSlot < hotkeysState.slots_per_page ? key : "",
      label,
      type,
      target,
      path: pathRef, // one-shot absolute path — no library ingest
      macro,
      empty,
    };
    closeHkEdit();
    persistHotkeys();
  }

  function clearHkSlot() {
    if (hkEditSlot == null) return;
    document.getElementById("hk-edit-label").value = "";
    document.getElementById("hk-edit-type").value = "";
    document.getElementById("hk-edit-target").value = "";
    const hp = document.getElementById("hk-edit-path");
    if (hp) hp.value = "";
    document.getElementById("hk-edit-macro").value = "";
  }

  function moveHk(dir) {
    if (hkEditSlot == null) return;
    const to = hkEditSlot + dir;
    if (to < 0 || to >= hotkeysState.hotkeys.length) return;
    swapHotkeys(hkEditSlot, to);
    hkEditSlot = to;
    document.getElementById("hk-edit-slot").textContent = String(to);
  }


  /* —— Library ingest (drag-drop wav/mp3/flac/mp4) —— */
  const INGEST_EXTS = new Set([".wav", ".mp3", ".flac", ".mp4", ".m4a", ".ogg", ".aac", ".mov", ".mkv", ".webm"]);
  let segSelected = null;

  function ingestStatus(t) {
    const el = document.getElementById("ingest-status");
    if (el) el.textContent = t || "";
    msg(t || "");
  }

  function fileExt(name) {
    const i = String(name || "").lastIndexOf(".");
    return i >= 0 ? String(name).slice(i).toLowerCase() : "";
  }

  async function ingestFileBlob(file) {
    const ext = fileExt(file.name);
    if (!INGEST_EXTS.has(ext)) {
      return { ok: false, error: `unsupported ${ext || "type"} — use wav/mp3/flac/mp4` };
    }
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("title", file.name.replace(/\.[^.]+$/, ""));
    fd.append("artist", "Imported");
    // Long concerts / interviews stay MUSIC; VT-ish names → VOICE_TRACK
    const lower = file.name.toLowerCase();
    const et =
      /vocloner|voice.?track|\bvt[_-]|\bvt\b/.test(lower) ? "VOICE_TRACK" : "MUSIC";
    fd.append("event_type", et);
    const res = await fetch("/api/library/ingest", { method: "POST", body: fd }).then((r) => r.json());
    return res;
  }

  async function ingestFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    ingestStatus(`Ingesting ${files.length} file(s)…`);
    let ok = 0;
    const errors = [];
    for (const f of files) {
      try {
        const res = await ingestFileBlob(f);
        if (res && res.ok) ok += 1;
        else errors.push((res && res.error) || f.name);
      } catch (e) {
        errors.push(String(e));
      }
    }
    ingestStatus(
      errors.length
        ? `Ingested ${ok}; errors: ${errors.slice(0, 2).join("; ")}`
        : `Ingested ${ok} cart(s) into library`
    );
    await refresh();
  }

  function wireDropZone() {
    const zone = document.getElementById("drop-zone");
    const overlay = document.getElementById("desk-drop-overlay");
    const desk = document.getElementById("desk-root") || document.querySelector(".desk");
    const input = document.getElementById("ingest-file-input");
    const browse = document.getElementById("btn-ingest-browse");

    function showOverlay(on) {
      if (!overlay) return;
      if (on) overlay.hidden = false;
      else overlay.hidden = true;
    }

    function hasFiles(ev) {
      const dt = ev.dataTransfer;
      if (!dt) return false;
      if (dt.types && Array.from(dt.types).includes("Files")) return true;
      return dt.files && dt.files.length > 0;
    }

    if (browse && input) {
      browse.onclick = () => input.click();
      input.onchange = () => {
        ingestFiles(input.files);
        input.value = "";
      };
    }

    let dragDepth = 0;
    const targets = [desk, zone].filter(Boolean);
    targets.forEach((el) => {
      el.addEventListener("dragenter", (ev) => {
        if (!hasFiles(ev)) return;
        ev.preventDefault();
        dragDepth += 1;
        showOverlay(true);
        zone && zone.classList.add("dragover");
      });
      el.addEventListener("dragover", (ev) => {
        if (!hasFiles(ev)) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "copy";
        zone && zone.classList.add("dragover");
      });
      el.addEventListener("dragleave", (ev) => {
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0) {
          showOverlay(false);
          zone && zone.classList.remove("dragover");
        }
      });
      el.addEventListener("drop", (ev) => {
        if (!hasFiles(ev)) return;
        ev.preventDefault();
        dragDepth = 0;
        showOverlay(false);
        zone && zone.classList.remove("dragover");
        ingestFiles(ev.dataTransfer.files);
      });
    });
  }

  /* —— Segment Editor —— */

  function updateSegLen() {
    const a = Number(document.getElementById("seg-in-ms")?.value || 0);
    const b = Number(document.getElementById("seg-out-ms")?.value || 0);
    const el = document.getElementById("seg-len");
    if (el) el.textContent = `LEN ${fmtDur(Math.max(0, b - a))}`;
  }

  function openSegmentEditor() {
    segSelected = null;
    document.getElementById("seg-selected").textContent = "No source selected";
    document.getElementById("seg-in-ms").value = "0";
    document.getElementById("seg-out-ms").value = "0";
    document.getElementById("seg-title").value = "";
    document.getElementById("seg-artist").value = "";
    document.getElementById("seg-msg").textContent = "";
    document.getElementById("seg-track-search").value = "";
    const bd = document.getElementById("segment-backdrop");
    bd.classList.add("open");
    bd.setAttribute("aria-hidden", "false");
    loadSegLibrary("");
  }

  function closeSegmentEditor() {
    const bd = document.getElementById("segment-backdrop");
    bd.classList.remove("open");
    bd.setAttribute("aria-hidden", "true");
  }

  async function loadSegLibrary(q) {
    const data = await fetch(`/api/library?q=${encodeURIComponent(q || "")}`).then((r) => r.json());
    const list = document.getElementById("seg-track-list");
    list.innerHTML = "";
    (data.tracks || []).forEach((t) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "lib-item";
      row.innerHTML = `<span class="lib-cat">${escapeHtml(t.event_type || "")}</span>
        <span class="lib-main">${escapeHtml(t.artist || "")} — ${escapeHtml(t.title || "")}</span>
        <span class="lib-dur">${fmtDur(t.duration_ms)}</span>`;
      row.onclick = () => {
        list.querySelectorAll(".lib-item.selected").forEach((x) => x.classList.remove("selected"));
        row.classList.add("selected");
        segSelected = t;
        document.getElementById("seg-selected").textContent =
          `#${t.id} ${t.artist} — ${t.title} (${fmtDur(t.duration_ms)}) · markers ready`;
        document.getElementById("seg-out-ms").value = String(t.duration_ms || 0);
        document.getElementById("seg-in-ms").value = "0";
        document.getElementById("seg-title").value = `${t.title} (part)`;
        document.getElementById("seg-artist").value = t.artist || "";
        const et = document.getElementById("seg-event-type");
        if (et) et.value = t.event_type || "MUSIC";
        updateSegLen();
      };
      list.appendChild(row);
    });
    if (!(data.tracks || []).length) {
      list.innerHTML = `<div class="lib-empty">No tracks — drop audio onto the desk first</div>`;
    }
  }

  async function saveSegmentCart() {
    if (!segSelected) {
      document.getElementById("seg-msg").textContent = "Select a source cart first";
      return;
    }
    const inMs = Number(document.getElementById("seg-in-ms").value || 0);
    const outMs = Number(document.getElementById("seg-out-ms").value || 0);
    const title = document.getElementById("seg-title").value.trim();
    const artist = document.getElementById("seg-artist").value.trim();
    document.getElementById("seg-msg").textContent = "Cutting segment (ffmpeg)…";
    const res = await fetch("/api/library/segment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        track_id: segSelected.id,
        in_ms: inMs,
        out_ms: outMs,
        title: title || undefined,
        artist: artist || undefined,
        event_type: document.getElementById("seg-event-type")?.value || "MUSIC",
      }),
    }).then((r) => r.json());
    if (res.ok) {
      let attachMsg = "";
      if (lastVtTakeEventId) {
        try {
          const attach = await fetch("/api/vt/attach-cart", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              event_id: lastVtTakeEventId,
              track_id: res.track_id,
            }),
          }).then((r) => r.json());
          if (attach && attach.ok) {
            attachMsg = ` · attached to VT event ${lastVtTakeEventId}`;
          }
        } catch (e) {
          attachMsg = "";
        }
      }
      document.getElementById("seg-msg").textContent =
        `Saved cart #${res.track_id}: ${res.artist} — ${res.title} (${fmtDur(res.duration_ms)})${attachMsg}`;
      ingestStatus(`Segment cart #${res.track_id} saved${attachMsg}`);
      await refresh();
    } else {
      document.getElementById("seg-msg").textContent = res.error || "Segment save failed";
    }
  }

  async function importVtInbox() {
    const ev = selectedEvent();
    const attach =
      ev && (ev.event_type === "VOICE_TRACK" || (ev.title || "").toLowerCase().includes("vt"))
        ? ev.id
        : null;
    ingestStatus("Importing from Downloads / VT inbox…");
    const res = await fetch("/api/vt/import-inbox", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_id: attach, move: false }),
    }).then((r) => r.json());
    if (!res.ok) {
      ingestStatus(res.error || "VT inbox import failed");
      return;
    }
    const n = res.count || 0;
    const att = res.attached && res.attached.ok ? ` · attached to event ${res.attached.log_event_id}` : "";
    ingestStatus(`Imported ${n} from ${res.inbox || "inbox"}${att}`);
    await refresh();
  }

  /* —— Wire UI —— */
  function init() {
    const del = document.getElementById("btn-log-delete");
    const ins = document.getElementById("btn-log-insert");
    const rep = document.getElementById("btn-log-replace");
    const sample = document.getElementById("btn-sample-hour");
    const segue = document.getElementById("btn-segue");
    if (del) del.onclick = deleteSelected;
    if (ins) ins.onclick = () => openLib("insert");
    if (rep) rep.onclick = () => openLib("replace");
    if (sample) sample.onclick = loadSampleHour;
    if (segue) segue.onclick = openSegue;

    document.getElementById("btn-lib-close")?.addEventListener("click", closeLib);
    document.getElementById("btn-lib-cancel")?.addEventListener("click", closeLib);
    document.getElementById("btn-lib-ok")?.addEventListener("click", confirmLib);
    document.getElementById("lib-backdrop")?.addEventListener("click", (ev) => {
      if (ev.target.id === "lib-backdrop") closeLib();
    });
    let searchTimer = null;
    document.getElementById("lib-search")?.addEventListener("input", (ev) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadLibrary(ev.target.value), 200);
    });

    document.getElementById("btn-segue-close")?.addEventListener("click", closeSegue);
    document.getElementById("btn-segue-cancel")?.addEventListener("click", closeSegue);
    document.getElementById("btn-segue-save")?.addEventListener("click", saveSegueUi);
    document.getElementById("btn-segue-audition")?.addEventListener("click", auditionSegue);
    document.getElementById("segue-backdrop")?.addEventListener("click", (ev) => {
      if (ev.target.id === "segue-backdrop") closeSegue();
    });

    // VT record
    const rec = document.getElementById("btn-vt-record");
    if (rec) {
      rec.disabled = false;
      rec.onclick = startRecord;
    }
    document.getElementById("btn-vt-stop-rec")?.addEventListener("click", stopRecord);
    document.getElementById("btn-vt-save-rec")?.addEventListener("click", saveRecording);
    document.getElementById("btn-vt-segment")?.addEventListener("click", openSegmentEditorForVtTake);
    ["vt-trim-in", "vt-trim-out"].forEach((id) => {
      document.getElementById(id)?.addEventListener("change", () => drawWave(waveData));
    });

    // Patch openVtStudio to stash event id — wrap after load
    const origInterval = setInterval(() => {
      if (typeof window.mqOpenVtStudio === "function" && !window._mqVtWrapped) {
        const orig = window.mqOpenVtStudio;
        window.mqOpenVtStudio = function (event, events) {
          window.mqVtEventId = event && event.id;
          return orig(event, events);
        };
        // also wrap global openVtStudio if accessible — rebind from app by replacing button handlers
        window._mqVtWrapped = true;
        clearInterval(origInterval);
      }
    }, 200);

    // Hotkeys
    document.getElementById("btn-hk-page-prev")?.addEventListener("click", () => {
      hotkeysState.page = Math.max(0, hotkeysState.page - 1);
      renderHotkeyBank();
    });
    document.getElementById("btn-hk-page-next")?.addEventListener("click", () => {
      hotkeysState.page = Math.min(hotkeysState.pages - 1, hotkeysState.page + 1);
      renderHotkeyBank();
    });
    document.getElementById("btn-hk-edit")?.addEventListener("click", () => {
      hotkeysState.editMode = !hotkeysState.editMode;
      document.getElementById("btn-hk-edit").classList.toggle("active", hotkeysState.editMode);
      msg(hotkeysState.editMode ? "Hotkey EDIT mode — click slot to edit, drag to reorder" : "Hotkey fire mode");
      renderHotkeyBank();
    });
    document.getElementById("btn-hk-expand")?.addEventListener("click", () => {
      document.getElementById("hotkey-panel")?.classList.toggle("expanded");
    });
    document.getElementById("btn-hk-edit-close")?.addEventListener("click", closeHkEdit);
    document.getElementById("btn-hk-edit-cancel")?.addEventListener("click", closeHkEdit);
    document.getElementById("btn-hk-edit-save")?.addEventListener("click", saveHkEdit);
    document.getElementById("btn-hk-clear")?.addEventListener("click", clearHkSlot);
    document.getElementById("btn-hk-up")?.addEventListener("click", () => moveHk(-1));
    document.getElementById("btn-hk-down")?.addEventListener("click", () => moveHk(1));

    // F-keys: fire page-1 slots (extend to F12)
    document.addEventListener("keydown", (ev) => {
      if (ev.target && ["INPUT", "TEXTAREA", "SELECT"].includes(ev.target.tagName)) return;
      const m = /^F([1-9]|1[0-2])$/.exec(ev.key);
      if (!m) return;
      if (hotkeysState.page !== 0) return;
      ev.preventDefault();
      const idx = Number(m[1]) - 1;
      const item = hotkeysState.hotkeys[idx];
      const btn = document.querySelectorAll("#hotkey-grid .hotkey")[idx];
      if (item) fireHotkeySlot(item, btn);
    });


    // Ingest / Segment / VT inbox
    wireDropZone();
    document.getElementById("btn-segment-editor")?.addEventListener("click", openSegmentEditor);
    document.getElementById("btn-segment-close")?.addEventListener("click", closeSegmentEditor);
    document.getElementById("btn-segment-cancel")?.addEventListener("click", closeSegmentEditor);
    document.getElementById("btn-segment-save")?.addEventListener("click", saveSegmentCart);
    document.getElementById("segment-backdrop")?.addEventListener("click", (ev) => {
      if (ev.target.id === "segment-backdrop") closeSegmentEditor();
    });
    let segSearchTimer = null;
    document.getElementById("seg-track-search")?.addEventListener("input", (ev) => {
      clearTimeout(segSearchTimer);
      segSearchTimer = setTimeout(() => loadSegLibrary(ev.target.value), 200);
    });
    document.getElementById("btn-import-vt-inbox")?.addEventListener("click", importVtInbox);
    // Drop file onto hotkey grid → assign absolute path as-is (NO library copy)
    const hkGrid = document.getElementById("hotkey-grid");
    if (hkGrid) {
      hkGrid.addEventListener("dragover", (ev) => {
        if (ev.dataTransfer && ev.dataTransfer.types.includes("Files")) {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = "link";
        }
      });
      hkGrid.addEventListener("drop", async (ev) => {
        const files = ev.dataTransfer && ev.dataTransfer.files;
        if (!files || !files.length) return;
        ev.preventDefault();
        ev.stopPropagation();
        const f = files[0];
        // Browser cannot expose real absolute path for security — store name +
        // instruct operator to paste full path, OR use webkitRelativePath hint.
        // Prefer File.path when Electron/desktop provides it.
        const abs = f.path || f.webkitRelativePath || "";
        const slot = hotkeysState.page * (hotkeysState.slots_per_page || 16);
        const item = hotkeysState.hotkeys[slot] || { slot, label: "", type: "", target: null, path: null };
        item.label = item.label || f.name.replace(/\.[^.]+$/, "");
        item.type = item.type || "ID";
        item.path = abs || null; // Electron: real path; browser: null → open edit
        item.empty = false;
        hotkeysState.hotkeys[slot] = item;
        await persistHotkeys();
        renderHotkeyBank();
        if (abs) {
          msg(`Hotkey slot ${slot + 1}: path ref ${abs} (no library copy)`);
        } else {
          openHkEdit(slot);
          const pe = document.getElementById("hk-edit-path");
          if (pe) pe.placeholder = `Paste full path for ${f.name} (plays in place)`;
          msg("Paste absolute file path for one-shot hotkey (web cannot see disk path)");
        }
      });
    }

    document.getElementById("seg-in-ms")?.addEventListener("input", updateSegLen);
    document.getElementById("seg-out-ms")?.addEventListener("input", updateSegLen);
    document.getElementById("btn-seg-in-here")?.addEventListener("click", () => {
      document.getElementById("seg-in-ms").value = "0";
      updateSegLen();
    });
    document.getElementById("btn-seg-out-end")?.addEventListener("click", () => {
      if (segSelected) document.getElementById("seg-out-ms").value = String(segSelected.duration_ms || 0);
      updateSegLen();
    });
    document.getElementById("btn-seg-plus-30")?.addEventListener("click", () => {
      const el = document.getElementById("seg-out-ms");
      el.value = String(Number(el.value || 0) + 30000);
      updateSegLen();
    });
    document.getElementById("btn-seg-plus-60")?.addEventListener("click", () => {
      const el = document.getElementById("seg-out-ms");
      el.value = String(Number(el.value || 0) + 60000);
      updateSegLen();
    });


    loadHotkeys();
    drawWave([]);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
