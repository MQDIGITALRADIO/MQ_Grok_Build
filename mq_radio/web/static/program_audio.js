/* MQ Program bus — dual-deck Web Audio with overlapping segue crossfade */
(function (global) {
  "use strict";

  const RAMP_DEFAULTS = {
    default: { fade_in_ms: 40, fade_out_ms: 80, curve: "linear", peak_gain: 1 },
    soft: { fade_in_ms: 800, fade_out_ms: 1600, curve: "equal_power", peak_gain: 1 },
    overnight: { fade_in_ms: 1200, fade_out_ms: 2500, curve: "equal_power", peak_gain: 0.92 },
    imaging: { fade_in_ms: 8, fade_out_ms: 40, curve: "linear", peak_gain: 1 },
    hard: { fade_in_ms: 0, fade_out_ms: 0, curve: "linear", peak_gain: 1 },
  };

  let ctx = null;
  let masterGain = null;
  let analyser = null;
  let oneshotEl = null;
  let oneshotSrc = null;
  let oneshotGain = null;
  let procNodes = [];
  let procInput = null;
  let procOutput = null;
  let currentProc = null;
  let vuRaf = 0;
  let lastVuLevels = { playing: false, left: 0.02, right: 0.02, source: "idle" };
  let audioRouteState = { sink_label: null, device_id: null, source: null, active: false };
  let currentSinkId = "";

  // Mix-minus: program − aux return (browser graph)
  let mmProgGain = null;
  let mmAuxGain = null; // polarity invert (−1) when subtract live
  let mmSum = null;
  let mmOutGain = null;
  let mmAnalyser = null;
  let mmCtx = null; // optional second context for mix-minus sink
  let mmMaster = null;
  let auxStream = null;
  let auxSource = null;
  let auxDeviceId = "";
  let mixMinusState = {
    paired: false,
    subtract_active: false,
    subtract_mode: "idle",
    aux_label: null,
    out_label: null,
    detail: null,
  };
  let lastReportedSubtract = null;

  let rampsState = { profiles: RAMP_DEFAULTS, active_profile: "default", ai_dj_profile: "overnight" };

  // Dual decks A/B → per-deck gains → procInput
  const decks = {
    A: { el: null, src: null, gain: null, eventId: null, role: "idle" },
    B: { el: null, src: null, gain: null, eventId: null, role: "idle" },
  };
  let programDeck = "A";
  let crossfadeTimer = 0;

  function labelsMatch(a, b) {
    const x = String(a || "").trim().toLowerCase();
    const y = String(b || "").trim().toLowerCase();
    if (!x || !y) return false;
    return x === y || x.includes(y) || y.includes(x);
  }

  async function resolveOutputSinkId(label) {
    if (!label || label === "none") return "";
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return "";
    try {
      // Prompt once so labels are populated in Chromium/Electron
      if (navigator.mediaDevices.getUserMedia) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          stream.getTracks().forEach((t) => t.stop());
        } catch (_) { /* permission optional — labels may still match in Electron */ }
      }
      const devices = await navigator.mediaDevices.enumerateDevices();
      const outs = devices.filter((d) => d.kind === "audiooutput");
      const hit = outs.find((d) => labelsMatch(d.label, label));
      return hit ? hit.deviceId : "";
    } catch (_) {
      return "";
    }
  }

  async function resolveInputDeviceId(label) {
    if (!label || label === "none") return "";
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return "";
    try {
      if (navigator.mediaDevices.getUserMedia) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          stream.getTracks().forEach((t) => t.stop());
        } catch (_) {}
      }
      const devices = await navigator.mediaDevices.enumerateDevices();
      const ins = devices.filter((d) => d.kind === "audioinput");
      const hit = ins.find((d) => labelsMatch(d.label, label));
      return hit ? hit.deviceId : "";
    } catch (_) {
      return "";
    }
  }

  function reportMixMinusSubtract() {
    const payload = {
      subtract_active: !!mixMinusState.subtract_active,
      subtract_mode: mixMinusState.subtract_mode || "idle",
      subtract_detail: mixMinusState.detail || null,
    };
    const key = JSON.stringify(payload);
    if (key === lastReportedSubtract) return;
    lastReportedSubtract = key;
    try {
      fetch("/api/audio/mix-minus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {});
    } catch (_) {}
  }

  function ensureMixMinusGraph() {
    // Caller must have ctx (ensureCtx). Do not call ensureCtx here — recursion.
    if (!ctx || !procOutput) return;
    if (mmSum) return;
    mmProgGain = ctx.createGain();
    mmProgGain.gain.value = 1;
    mmAuxGain = ctx.createGain();
    mmAuxGain.gain.value = 0; // silent until aux capture (pairing-only)
    mmSum = ctx.createGain();
    mmSum.gain.value = 1;
    mmOutGain = ctx.createGain();
    mmOutGain.gain.value = 1;
    mmAnalyser = ctx.createAnalyser();
    mmAnalyser.fftSize = 1024;
    procOutput.connect(mmProgGain);
    mmProgGain.connect(mmSum);
    mmAuxGain.connect(mmSum);
    mmSum.connect(mmOutGain);
    mmOutGain.connect(mmAnalyser);
    // Keep graph alive without leaking into program destination by default
    const silent = ctx.createGain();
    silent.gain.value = 0.0001;
    mmAnalyser.connect(silent);
    silent.connect(ctx.destination);
    // Do NOT push mm nodes into procNodes — rebuildProcessing must not tear them down
  }

  async function stopAuxCapture() {
    if (auxSource) {
      try { auxSource.disconnect(); } catch (_) {}
      auxSource = null;
    }
    if (auxStream) {
      try { auxStream.getTracks().forEach((t) => t.stop()); } catch (_) {}
      auxStream = null;
    }
    auxDeviceId = "";
    if (mmAuxGain) mmAuxGain.gain.value = 0;
    mixMinusState.subtract_active = false;
    if (mixMinusState.paired) {
      mixMinusState.subtract_mode = "pairing_only";
      mixMinusState.detail = "No Aux capture — pairing only (program feed to mix-minus path)";
    } else {
      mixMinusState.subtract_mode = "idle";
      mixMinusState.detail = null;
    }
    reportMixMinusSubtract();
  }

  async function startAuxCapture(label) {
    ensureCtx();
    ensureMixMinusGraph();
    if (!label || label === "none") {
      await stopAuxCapture();
      return false;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      mixMinusState.subtract_active = false;
      mixMinusState.subtract_mode = "pairing_only";
      mixMinusState.detail = "getUserMedia unavailable — pairing only";
      reportMixMinusSubtract();
      return false;
    }
    const deviceId = await resolveInputDeviceId(label);
    // Reuse stream if same device
    if (auxStream && auxDeviceId && deviceId && auxDeviceId === deviceId && mixMinusState.subtract_active) {
      return true;
    }
    await stopAuxCapture();
    const constraints = deviceId
      ? { audio: { deviceId: { exact: deviceId } }, video: false }
      : { audio: true, video: false };
    try {
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      auxStream = stream;
      auxDeviceId = deviceId || (stream.getAudioTracks()[0] && stream.getAudioTracks()[0].getSettings().deviceId) || "";
      auxSource = ctx.createMediaStreamSource(stream);
      // Polarity invert: program − aux ≡ program + (−aux)
      mmAuxGain.gain.value = -1;
      auxSource.connect(mmAuxGain);
      mixMinusState.subtract_active = true;
      mixMinusState.subtract_mode = "program_minus_aux";
      mixMinusState.aux_label = label;
      mixMinusState.detail = deviceId
        ? "Web Audio: program_processed − aux_return (live)"
        : "Web Audio: program − default mic (label unmatched; best-effort)";
      reportMixMinusSubtract();
      return true;
    } catch (err) {
      mixMinusState.subtract_active = false;
      mixMinusState.subtract_mode = "pairing_only";
      mixMinusState.detail = "Aux capture failed: " + String(err && err.message || err);
      reportMixMinusSubtract();
      return false;
    }
  }

  async function syncMixMinusFromRoute(route) {
    route = route || {};
    const mm = route.mix_minus || {};
    const paired = !!mm.paired;
    mixMinusState.paired = paired;
    mixMinusState.out_label = mm.out_label || null;
    mixMinusState.aux_label = mm.aux_in_label || null;
    ensureCtx();
    ensureMixMinusGraph();

    // Optional distinct mix-minus sink via second AudioContext
    const outLabel = mm.out_label || null;
    if (outLabel && mm.out && mm.out !== "none") {
      try {
        const sinkId = await resolveOutputSinkId(outLabel);
        if (sinkId && typeof AudioContext !== "undefined") {
          if (!mmCtx) {
            const AC = global.AudioContext || global.webkitAudioContext;
            mmCtx = new AC();
            mmMaster = mmCtx.createGain();
            mmMaster.gain.value = 1;
            mmMaster.connect(mmCtx.destination);
          }
          if (typeof mmCtx.setSinkId === "function") {
            await mmCtx.setSinkId(sinkId);
          }
          // Bridge mmSum into mmCtx via MediaStream — best-effort; silent if unsupported
          // (primary subtract still runs in main ctx for status/honesty)
        }
      } catch (_) {}
    }

    if (paired && mm.aux_in_label) {
      await startAuxCapture(mm.aux_in_label);
    } else if (paired && !mm.aux_in_label) {
      // Paired by id but no label — try generic capture
      await startAuxCapture("default");
    } else {
      await stopAuxCapture();
    }
    return Object.assign({}, mixMinusState);
  }

  async function applyAudioRoute(route) {
    route = route || {};
    const prog = route.program || {};
    const label = route.sink_label || prog.label || null;
    const deviceKey = prog.device_id || route.device_id || null;
    audioRouteState = {
      sink_label: label,
      device_id: deviceKey,
      source: route.source || null,
      active: !!route.active,
      backend: route.backend || null,
      note: route.note || null,
    };
    if (!label || deviceKey === "none") {
      // Reset to default sink when Program is None
      try {
        if (ctx && typeof ctx.setSinkId === "function" && currentSinkId) {
          await ctx.setSinkId("");
          currentSinkId = "";
        }
      } catch (_) {}
      return audioRouteState;
    }
    const sinkId = await resolveOutputSinkId(label);
    if (!sinkId) {
      audioRouteState.sink_match = false;
      return audioRouteState;
    }
    ensureCtx();
    try {
      if (ctx && typeof ctx.setSinkId === "function") {
        await ctx.setSinkId(sinkId);
        currentSinkId = sinkId;
        audioRouteState.sink_match = true;
        audioRouteState.sink_id = sinkId;
      } else {
        // Fallback: setSinkId on media elements (works when not using MediaElementSource)
        const els = [decks.A.el, decks.B.el, oneshotEl].filter(Boolean);
        for (const el of els) {
          if (typeof el.setSinkId === "function") {
            try { await el.setSinkId(sinkId); } catch (_) {}
          }
        }
        currentSinkId = sinkId;
        audioRouteState.sink_match = true;
        audioRouteState.sink_id = sinkId;
        audioRouteState.sink_via = "media_element";
      }
    } catch (err) {
      audioRouteState.sink_match = false;
      audioRouteState.sink_error = String(err && err.message || err);
    }
    try {
      await syncMixMinusFromRoute(route);
      audioRouteState.mix_minus = Object.assign({}, mixMinusState);
    } catch (mmErr) {
      audioRouteState.mix_minus_error = String(mmErr && mmErr.message || mmErr);
    }
    return audioRouteState;
  }

  function ensureCtx() {
    if (ctx) return ctx;
    const AC = global.AudioContext || global.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    masterGain = ctx.createGain();
    masterGain.gain.value = 1;
    oneshotGain = ctx.createGain();
    oneshotGain.gain.value = 1;
    analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.75;
    procInput = ctx.createGain();
    procOutput = ctx.createGain();
    procInput.gain.value = 1;
    procOutput.gain.value = 1;

    ["A", "B"].forEach((letter) => {
      const g = ctx.createGain();
      g.gain.value = 0.0001;
      decks[letter].gain = g;
      g.connect(procInput);
    });

    oneshotGain.connect(procInput);
    rebuildProcessing(currentProc || defaultProc());
    procOutput.connect(masterGain);
    masterGain.connect(analyser);
    analyser.connect(ctx.destination);
    ensureMixMinusGraph();
    startVuLoop();
    return ctx;
  }

  function defaultProc() {
    return {
      enabled: true,
      template: "FM",
      transmission_mode: false,
      stages: {
        agc: { enabled: true, target_db: -15, drive_db: 7 },
        eq: { enabled: true, low_shelf_db: 1.5, presence_db: 1.5, air_db: 0.75 },
        multiband: { enabled: true, drive_db: [3.5, 4.5, 4.0, 3.0] },
        exciter: { enabled: true, amount: 0.3, mix: 0.22 },
        limiter: { enabled: true, ceiling_dbfs: -1 },
      },
      output: { path: "FM", preemphasis: true, stereo_enhance: 0.15 },
    };
  }

  function dbToGain(db) {
    return Math.pow(10, (Number(db) || 0) / 20);
  }

  function disconnectProc() {
    procNodes.forEach((n) => {
      try { n.disconnect(); } catch (_) {}
    });
    procNodes = [];
    try { procInput.disconnect(); } catch (_) {}
  }

  function rebuildProcessing(proc) {
    if (!ctx || !procInput || !procOutput) return;
    currentProc = proc || defaultProc();
    disconnectProc();
    let node = procInput;
    const stages = (currentProc && currentProc.stages) || {};
    const enabled = currentProc && currentProc.enabled !== false;
    const insertBypass = !enabled;

    const txMode = !!(currentProc && currentProc.transmission_mode);
    if (!insertBypass && stages.agc && stages.agc.enabled !== false) {
      const agc = ctx.createDynamicsCompressor();
      let drive = Number(stages.agc.drive_db || 6);
      if (txMode) drive *= 1.45;
      agc.threshold.value = Number(stages.agc.target_db || -16) - drive * 0.35;
      agc.knee.value = txMode ? 8 : 12;
      agc.ratio.value = 3.5 + drive * 0.15;
      agc.attack.value = Math.max(0.005, (Number(stages.agc.attack_ms) || 50) / 1000);
      let rel = Math.max(0.05, (Number(stages.agc.release_ms) || 1000) / 1000);
      if (txMode) rel *= 0.7;
      agc.release.value = rel;
      node.connect(agc);
      procNodes.push(agc);
      node = agc;
    }

    if (!insertBypass && stages.eq && stages.eq.enabled !== false) {
      const low = ctx.createBiquadFilter();
      low.type = "lowshelf";
      low.frequency.value = Number(stages.eq.low_shelf_hz || 120);
      low.gain.value = Number(stages.eq.low_shelf_db || 1.5);
      const mid = ctx.createBiquadFilter();
      mid.type = "peaking";
      mid.frequency.value = Number(stages.eq.presence_hz || 3200);
      mid.Q.value = 0.9;
      mid.gain.value = Number(stages.eq.presence_db || 1.0);
      const air = ctx.createBiquadFilter();
      air.type = "highshelf";
      air.frequency.value = Number(stages.eq.air_hz || 10000);
      air.gain.value = Number(stages.eq.air_db || 0.5);
      const cut = ctx.createBiquadFilter();
      cut.type = "lowpass";
      cut.frequency.value = Number(stages.eq.high_cut_hz || 15000);
      cut.Q.value = 0.7;
      node.connect(low);
      low.connect(mid);
      mid.connect(air);
      air.connect(cut);
      procNodes.push(low, mid, air, cut);
      node = cut;
    }

    if (!insertBypass && stages.multiband && stages.multiband.enabled !== false) {
      const mb = ctx.createDynamicsCompressor();
      const drives = stages.multiband.drive_db || [3, 4, 3.5, 2.5];
      const avgDrive = drives.reduce((a, b) => a + Number(b || 0), 0) / Math.max(1, drives.length);
      mb.threshold.value = -22 - avgDrive * 0.4;
      mb.knee.value = 8;
      mb.ratio.value = 2.8 + avgDrive * 0.2;
      mb.attack.value = 0.012;
      mb.release.value = 0.22;
      const mbEq = ctx.createBiquadFilter();
      mbEq.type = "peaking";
      mbEq.frequency.value = 1800;
      mbEq.Q.value = 0.7;
      mbEq.gain.value = Math.min(3, avgDrive * 0.25);
      node.connect(mb);
      mb.connect(mbEq);
      procNodes.push(mb, mbEq);
      node = mbEq;
    }

    if (!insertBypass && stages.exciter && stages.exciter.enabled !== false) {
      const amount = Math.max(0, Math.min(1, Number(stages.exciter.amount) || 0.2));
      const mix = Math.max(0, Math.min(1, Number(stages.exciter.mix) || 0.15));
      const dry = ctx.createGain();
      const wet = ctx.createGain();
      const shaper = ctx.createWaveShaper();
      const curve = new Float32Array(256);
      for (let i = 0; i < 256; i++) {
        const x = (i / 128) - 1;
        curve[i] = ((1 + amount * 2.5) * x) / (1 + amount * 2.5 * Math.abs(x));
      }
      shaper.curve = curve;
      shaper.oversample = "2x";
      const hip = ctx.createBiquadFilter();
      hip.type = "highpass";
      hip.frequency.value = 2400;
      dry.gain.value = 1 - mix * 0.85;
      wet.gain.value = mix * (0.35 + amount);
      const merge = ctx.createGain();
      node.connect(dry);
      node.connect(hip);
      hip.connect(shaper);
      shaper.connect(wet);
      dry.connect(merge);
      wet.connect(merge);
      procNodes.push(dry, wet, shaper, hip, merge);
      node = merge;
    }

    if (!insertBypass && stages.limiter && stages.limiter.enabled !== false) {
      const lim = ctx.createDynamicsCompressor();
      const ceiling = Number(stages.limiter.ceiling_dbfs || -1);
      lim.threshold.value = ceiling - 0.5;
      lim.knee.value = 0.5;
      lim.ratio.value = 20;
      lim.attack.value = 0.003;
      lim.release.value = Math.max(0.02, (Number(stages.limiter.release_ms) || 40) / 1000);
      const trim = ctx.createGain();
      trim.gain.value = dbToGain(Math.min(0, ceiling + 0.2));
      node.connect(lim);
      lim.connect(trim);
      procNodes.push(lim, trim);
      node = trim;
    }

    // Path flavour: FM pre-emphasis shelf vs Digital cleaner air
    const tmpl = (currentProc.template || "").toUpperCase();
    const tx = !!(currentProc && currentProc.transmission_mode);
    const outCfg = (currentProc && currentProc.output) || {};

    if (!insertBypass && tmpl === "FM" && outCfg.preemphasis !== false) {
      const pre = ctx.createBiquadFilter();
      pre.type = "highshelf";
      // 50/75µs awareness — approximate with mild HF lift (stronger in TX mode)
      const us = Number(outCfg.preemphasis_us) || 50;
      pre.frequency.value = us >= 70 ? 2100 : 3200;
      pre.gain.value = tx ? (us >= 70 ? 4.5 : 3.5) : (us >= 70 ? 2.2 : 1.6);
      node.connect(pre);
      procNodes.push(pre);
      node = pre;
      if (tx) {
        const dens = ctx.createDynamicsCompressor();
        dens.threshold.value = -18;
        dens.knee.value = 6;
        dens.ratio.value = 4.5;
        dens.attack.value = 0.008;
        dens.release.value = 0.12;
        node.connect(dens);
        procNodes.push(dens);
        node = dens;
      }
    } else if (!insertBypass && tmpl === "DIGITAL") {
      // Cleaner path: gentle HF cut + softer ceiling trim in TX mode
      const soft = ctx.createBiquadFilter();
      soft.type = "highshelf";
      soft.frequency.value = 12000;
      soft.gain.value = tx ? -1.8 : -0.6;
      node.connect(soft);
      procNodes.push(soft);
      node = soft;
      if (tx) {
        const softLim = ctx.createDynamicsCompressor();
        softLim.threshold.value = -3.5;
        softLim.knee.value = 2;
        softLim.ratio.value = 12;
        softLim.attack.value = 0.004;
        softLim.release.value = 0.08;
        node.connect(softLim);
        procNodes.push(softLim);
        node = softLim;
      }
    }

    const makeup = ctx.createGain();
    if (tmpl === "DIGITAL") {
      makeup.gain.value = tx ? 0.82 : 0.92;
    } else {
      makeup.gain.value = tx ? 1.18 : 1.05;
    }
    node.connect(makeup);
    makeup.connect(procOutput);
    procNodes.push(makeup);
  }

  function applyProcessing(proc) {
    ensureCtx();
    rebuildProcessing(proc || defaultProc());
    return currentProc;
  }

  function setRamps(state) {
    if (!state) return;
    rampsState = {
      profiles: { ...RAMP_DEFAULTS, ...(state.profiles || {}) },
      active_profile: state.active_profile || "default",
      ai_dj_profile: state.ai_dj_profile || "overnight",
    };
  }

  function resolveRamp(profileId, eventType, overnight) {
    const profiles = rampsState.profiles || RAMP_DEFAULTS;
    if (overnight) {
      return profiles[rampsState.ai_dj_profile] || profiles.overnight || RAMP_DEFAULTS.overnight;
    }
    if (profileId && profiles[profileId]) return profiles[profileId];
    const et = (eventType || "").toUpperCase();
    if (et === "ID" || et === "SWEEPER" || et === "PROMO") return profiles.imaging || RAMP_DEFAULTS.imaging;
    if (et === "VOICE_TRACK") return profiles.soft || RAMP_DEFAULTS.soft;
    return profiles[rampsState.active_profile] || RAMP_DEFAULTS.default;
  }

  function ensureDeckElement(letter) {
    const d = decks[letter];
    if (d.el) return d.el;
    const el = new Audio();
    el.crossOrigin = "anonymous";
    el.preload = "auto";
    d.el = el;
    return el;
  }

  function ensureOneshotElement() {
    if (oneshotEl) return oneshotEl;
    oneshotEl = new Audio();
    oneshotEl.crossOrigin = "anonymous";
    oneshotEl.preload = "auto";
    return oneshotEl;
  }

  function connectDeckMedia(letter) {
    ensureCtx();
    const d = decks[letter];
    const el = ensureDeckElement(letter);
    if (!d.src) {
      d.src = ctx.createMediaElementSource(el);
      d.src.connect(d.gain);
    }
    return d;
  }

  function connectOneshotMedia() {
    ensureCtx();
    const el = ensureOneshotElement();
    if (!oneshotSrc) {
      oneshotSrc = ctx.createMediaElementSource(el);
    }
    try { oneshotSrc.disconnect(); } catch (_) {}
    oneshotSrc.connect(oneshotGain);
    return oneshotSrc;
  }

  async function resume() {
    const c = ensureCtx();
    if (c && c.state === "suspended") {
      try { await c.resume(); } catch (_) {}
    }
  }

  function equalPower(t) {
    // t 0..1 → [outGain, inGain]
    const a = Math.max(0, Math.min(1, t));
    return [Math.cos(a * 0.5 * Math.PI), Math.sin(a * 0.5 * Math.PI)];
  }

  function scheduleDeckGain(letter, value, atTime) {
    const g = decks[letter] && decks[letter].gain;
    if (!g || !ctx) return;
    const v = Math.max(0.0001, value);
    if (atTime == null) {
      g.gain.setValueAtTime(v, ctx.currentTime);
    } else {
      g.gain.linearRampToValueAtTime(v, atTime);
    }
  }

  async function playOnDeck(letter, url, opts) {
    opts = opts || {};
    if (!url) return false;
    await resume();
    connectDeckMedia(letter);
    const d = decks[letter];
    const el = d.el;
    const profile = resolveRamp(opts.rampProfile, opts.eventType, opts.overnight);
    const peak = Math.max(0.05, Math.min(1.2, Number(profile.peak_gain) || 1));
    const fadeIn = Math.max(0, Number(opts.fadeInMs != null ? opts.fadeInMs : profile.fade_in_ms) || 0);
    try {
      if (el.src !== url && !(el.src || "").endsWith(url.replace(/^\//, ""))) {
        el.src = url;
      }
      const startAt = Number(opts.startOffsetSec) || 0;
      try { el.currentTime = startAt; } catch (_) { el.currentTime = 0; }
      const now = ctx.currentTime;
      d.gain.gain.cancelScheduledValues(now);
      d.gain.gain.setValueAtTime(0.0001, now);
      if (fadeIn <= 0) {
        d.gain.gain.setValueAtTime(peak, now);
      } else {
        d.gain.gain.linearRampToValueAtTime(peak, now + fadeIn / 1000);
      }
      await el.play();
      d.eventId = opts.eventId || null;
      d.role = opts.role || "program";
      return true;
    } catch (err) {
      console.warn("deck play failed", letter, err);
      return false;
    }
  }

  function stopDeck(letter, opts) {
    opts = opts || {};
    const d = decks[letter];
    if (!d || !d.el) return;
    const ms = Math.max(0, Number(opts.fadeOutMs) || 0);
    const now = ctx ? ctx.currentTime : 0;
    if (d.gain && ctx && ms > 0) {
      const cur = d.gain.gain.value || 0.0001;
      d.gain.gain.cancelScheduledValues(now);
      d.gain.gain.setValueAtTime(cur, now);
      d.gain.gain.linearRampToValueAtTime(0.0001, now + ms / 1000);
      setTimeout(() => {
        try { d.el.pause(); } catch (_) {}
        d.eventId = null;
        d.role = "idle";
      }, ms + 30);
    } else {
      if (d.gain && ctx) {
        d.gain.gain.cancelScheduledValues(now);
        d.gain.gain.setValueAtTime(0.0001, now);
      }
      try { d.el.pause(); } catch (_) {}
      d.eventId = null;
      d.role = "idle";
    }
  }

  /**
   * Classic overlapping segue: keep outgoing audible while incoming starts
   * on the other deck; equal-power crossfade with optional duck on outgoing.
   */
  function startCrossfade(fromLetter, toLetter, opts) {
    opts = opts || {};
    ensureCtx();
    const ms = Math.max(80, Number(opts.crossfadeMs) || 1500);
    const duckDb = Number(opts.duckDb);
    const duckGain = Number.isFinite(duckDb) ? dbToGain(duckDb) : 1;
    const peakIn = Math.max(0.05, Math.min(1.2, Number(opts.peakGain) || 1));
    const from = decks[fromLetter];
    const to = decks[toLetter];
    if (!from || !to || !from.gain || !to.gain) return ms;

    const now = ctx.currentTime;
    const steps = Math.max(4, Math.min(48, Math.round(ms / 40)));
    const fromStart = Math.max(from.gain.gain.value, 0.0001);
    // Optionally duck outgoing bed immediately (VT under music)
    const fromTargetStart = Math.min(fromStart, Math.max(0.0001, fromStart * Math.min(1, duckGain * 1.15)));

    from.gain.gain.cancelScheduledValues(now);
    to.gain.gain.cancelScheduledValues(now);
    from.gain.gain.setValueAtTime(fromStart, now);
    if (fromTargetStart < fromStart * 0.98) {
      from.gain.gain.linearRampToValueAtTime(fromTargetStart, now + Math.min(0.12, ms / 4000));
    }
    to.gain.gain.setValueAtTime(0.0001, now);

    for (let i = 1; i <= steps; i++) {
      const t = i / steps;
      const [outG, inG] = equalPower(t);
      const at = now + (ms / 1000) * t;
      const outVal = Math.max(0.0001, fromTargetStart * outG * (duckGain < 1 ? Math.max(duckGain, 0.15) : 1));
      const inVal = Math.max(0.0001, peakIn * inG);
      from.gain.gain.linearRampToValueAtTime(outVal, at);
      to.gain.gain.linearRampToValueAtTime(inVal, at);
    }

    from.role = "fading";
    to.role = "program";
    programDeck = toLetter;

    if (crossfadeTimer) clearTimeout(crossfadeTimer);
    crossfadeTimer = setTimeout(() => {
      stopDeck(fromLetter, { fadeOutMs: 0 });
      flashEndPulse(fromLetter);
    }, ms + 40);

    return ms;
  }

  async function playProgram(url, opts) {
    opts = opts || {};
    const letter = opts.deck || programDeck || "A";
    programDeck = letter;
    const ok = await playOnDeck(letter, url, { ...opts, role: "program" });
    // Silence other deck unless overlapping
    if (ok && !opts.keepOther) {
      const other = letter === "A" ? "B" : "A";
      if (decks[other].role !== "fading") stopDeck(other, { fadeOutMs: 40 });
    }
    return ok;
  }

  function stopProgram(opts) {
    opts = opts || {};
    const profile = resolveRamp(opts.rampProfile, opts.eventType, opts.overnight);
    const ms = Number(profile.fade_out_ms) || 80;
    stopDeck("A", { fadeOutMs: ms });
    stopDeck("B", { fadeOutMs: ms });
    programDeck = "A";
  }

  async function syncFromStatus(st) {
    if (!st) return;
    if (st.processing) applyProcessing(st.processing);
    if (st.ramps) setRamps(st.ramps);
    if (st.audio_route) {
      try { await applyAudioRoute(st.audio_route); } catch (_) {}
    } else if (st.mix_minus) {
      try { await syncMixMinusFromRoute({ mix_minus: st.mix_minus }); } catch (_) {}
    }

    const onAir = st.now && st.now.status === "ON_AIR" && st.running;
    const active = (st.active_deck || (st.decks && st.decks.active) || programDeck || "A").toUpperCase();
    const segue = st.segue || (st.decks && st.decks.segue) || {};
    const overlap = !!(st.overlap_active || (st.decks && st.decks.overlap_active));
    const programUrl = st.playable_url || (st.now && st.now.playable_url);
    const fading = (st.decks && st.decks.fading) || null;
    const fadingUrl =
      st.fading_playable_url ||
      (fading && fading.playable_url) ||
      null;
    const eventId = onAir ? st.now.id : null;
    const overnight =
      st.ramp_profile === "overnight" ||
      (st.ramps && st.ramps.active_profile === "overnight");
    const other = active === "A" ? "B" : "A";

    if (!onAir) {
      if (decks.A.eventId || decks.B.eventId) {
        stopProgram({ rampProfile: st.ramp_profile, eventType: (st.now || {}).event_type });
      }
      return;
    }

    if (!programUrl) return;

    const programChanged = decks[active].eventId !== eventId;
    const needOverlap =
      overlap &&
      fading &&
      fading.event_id &&
      (programChanged || decks[other].role !== "fading");

    if (needOverlap && fadingUrl) {
      // Ensure outgoing is on the fading deck letter
      const fadeLetter = (fading.deck || other).toUpperCase();
      const inLetter = active;
      // If outgoing isn't already playing on fadeLetter, start it briefly (muted path) — usually already there
      if (decks[fadeLetter].eventId !== fading.event_id) {
        await playOnDeck(fadeLetter, fadingUrl, {
          eventId: fading.event_id,
          eventType: fading.event_type,
          rampProfile: fading.ramp_profile,
          role: "fading",
          fadeInMs: 0,
        });
        // Jump near end-pulse so we don't replay from top
        try {
          const el = decks[fadeLetter].el;
          const durSec = (Number(fading.duration_ms) || 0) / 1000;
          const elapsedSec = (Number(fading.elapsed_ms) || 0) / 1000;
          if (el && durSec > 0) el.currentTime = Math.min(durSec - 0.05, Math.max(0, elapsedSec));
        } catch (_) {}
        if (decks[fadeLetter].gain) {
          const now = ctx.currentTime;
          decks[fadeLetter].gain.gain.setValueAtTime(1, now);
        }
      }
      await playOnDeck(inLetter, programUrl, {
        eventId,
        eventType: st.now.event_type,
        rampProfile: st.ramp_profile,
        overnight,
        role: "program",
        fadeInMs: 0,
      });
      startCrossfade(fadeLetter, inLetter, {
        crossfadeMs: Number(segue.crossfade_ms) || 1500,
        duckDb: segue.duck_db,
        peakGain: 1,
      });
      programDeck = inLetter;
      return;
    }

    // Steady-state: keep program deck in sync
    if (programChanged || !decks[active].el || decks[active].el.paused) {
      await playProgram(programUrl, {
        deck: active,
        eventId,
        eventType: st.now.event_type,
        rampProfile: st.ramp_profile,
        overnight,
        keepOther: overlap,
      });
      programDeck = active;
    }
  }

  async function playOneShot(url, label) {
    if (!url) return false;
    await resume();
    connectOneshotMedia();
    const el = oneshotEl;
    const profile = resolveRamp("imaging", "SWEEPER", false);
    try {
      el.src = url;
      el.currentTime = 0;
      const now = ctx.currentTime;
      oneshotGain.gain.cancelScheduledValues(now);
      oneshotGain.gain.setValueAtTime(0.0001, now);
      oneshotGain.gain.linearRampToValueAtTime(
        Number(profile.peak_gain) || 1,
        now + Math.max(0.005, (profile.fade_in_ms || 8) / 1000)
      );
      el.onended = () => {
        flashEndPulse("A");
        clearDeckPulse("A");
        // brief end flash then clear so desk doesn't stick red
        const deck = document.getElementById("deck-a");
        if (deck) {
          deck.classList.add("end-ramp", "end-ramp-5", "pulse-fired");
          setTimeout(() => {
            deck.classList.remove("end-ramp", "end-ramp-5", "pulse-fired");
          }, 350);
        }
      };
      await el.play();
      flashFirePulse();
      return true;
    } catch (err) {
      console.warn("oneshot failed", err);
      return false;
    }
  }

  function flashFirePulse() {
    const deck = document.getElementById("deck-a");
    const panel = document.getElementById("hotkey-panel");
    if (deck) {
      deck.classList.remove("hotkey-pulse");
      // reflow so re-fire retriggers animation
      void deck.offsetWidth;
      deck.classList.add("hotkey-pulse");
      setTimeout(() => deck.classList.remove("hotkey-pulse"), 280);
    }
    if (panel) {
      panel.classList.add("hk-firing");
      setTimeout(() => panel.classList.remove("hk-firing"), 280);
    }
  }

  function clearDeckPulse(letter) {
    const id = letter === "B" ? "deck-b" : letter === "C" ? "deck-c" : "deck-a";
    const meterId = letter === "B" ? "deck-b-meter" : letter === "C" ? "deck-c-meter" : "deck-a-meter";
    const deck = document.getElementById(id);
    const meter = document.getElementById(meterId);
    if (deck) {
      deck.classList.remove(
        "end-ramp", "end-ramp-1", "end-ramp-2", "end-ramp-3", "end-ramp-4", "end-ramp-5",
        "hotkey-pulse", "pulse-fired"
      );
    }
    if (meter) {
      meter.classList.remove("end-ramp-1", "end-ramp-2", "end-ramp-3", "end-ramp-4", "end-ramp-5");
    }
  }

  function flashEndPulse(letter) {
    const id = letter === "B" ? "deck-b" : "deck-a";
    const meterId = letter === "B" ? "deck-b-meter" : "deck-a-meter";
    const deck = document.getElementById(id);
    const meter = document.getElementById(meterId);
    clearDeckPulse(letter || "A");
    if (deck) {
      deck.classList.add("end-ramp", "end-ramp-5", "pulse-fired");
      setTimeout(() => {
        deck.classList.remove("end-ramp", "end-ramp-5", "pulse-fired");
      }, 420);
    }
    if (meter) {
      meter.classList.add("end-ramp-5");
      setTimeout(() => meter.classList.remove("end-ramp-5"), 420);
    }
  }

  function readAnalyserVu() {
    if (!analyser) return null;
    const buf = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    let peak = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = buf[i];
      sum += v * v;
      peak = Math.max(peak, Math.abs(v));
    }
    const rms = Math.sqrt(sum / buf.length);
    const level = Math.min(1, Math.pow(rms * 3.2, 0.7) * 1.15);
    const pk = Math.min(1, peak * 1.4);
    const playing =
      (decks.A.el && !decks.A.el.paused) ||
      (decks.B.el && !decks.B.el.paused) ||
      (oneshotEl && !oneshotEl.paused) ||
      level > 0.02;
    if (!playing) return { playing: false, left: 0.02, right: 0.02, source: "analyser-idle" };
    const left = Math.min(1, level * (0.92 + 0.08 * (pk > level ? 1 : 0.6)));
    const right = Math.min(1, level * (0.88 + 0.12 * Math.sin(Date.now() / 180)));
    return { playing: true, left, right, peak_left: pk, peak_right: pk * 0.98, source: "analyser" };
  }

  function startVuLoop() {
    if (vuRaf) return;
    const tick = () => {
      const vu = readAnalyserVu();
      if (vu) lastVuLevels = vu;
      vuRaf = requestAnimationFrame(tick);
    };
    vuRaf = requestAnimationFrame(tick);
  }

  function getVu() {
    return lastVuLevels;
  }

  async function auditionTemplate(proc) {
    await resume();
    applyProcessing(proc);
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = "sawtooth";
    osc.frequency.value = 440;
    g.gain.value = 0.0001;
    osc.connect(g);
    g.connect(procInput);
    const now = ctx.currentTime;
    g.gain.linearRampToValueAtTime(0.18, now + 0.05);
    g.gain.linearRampToValueAtTime(0.0001, now + 0.85);
    osc.start(now);
    osc.stop(now + 0.9);
    setTimeout(() => {
      try { osc.disconnect(); g.disconnect(); } catch (_) {}
    }, 1000);
  }

  function decodeAudioUrl(url) {
    return fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error("media " + r.status);
        return r.arrayBuffer();
      })
      .then((buf) => ctx.decodeAudioData(buf.slice(0)));
  }

  /** Segue Editor audition: real outgoing/incoming(/VT) media with duck + crossfade */
  async function auditionSegue(opts) {
    opts = opts || {};
    await resume();
    const ms = Math.max(200, Number(opts.crossfadeMs) || 1500);
    const duckDb = Number(opts.duckDb);
    const duck = Number.isFinite(duckDb) ? dbToGain(duckDb) : dbToGain(-11);
    const outUrl = opts.outgoingUrl || opts.fromUrl || null;
    const inUrl = opts.incomingUrl || opts.toUrl || null;
    const vtUrl = opts.vtUrl || null;
    const outroMarkMs = Math.max(0, Number(opts.outroMarkMs) || 0);
    const introMarkMs = Math.max(0, Number(opts.introMarkMs) || 0);
    const vtInMs = Math.max(0, Number(opts.vtInMs) || 0);

    // Prefer real library media; fall back to tones if URLs missing/fail
    let outBuf = null;
    let inBuf = null;
    let vtBuf = null;
    try {
      if (outUrl) outBuf = await decodeAudioUrl(outUrl);
    } catch (e) { console.warn("audition out", e); }
    try {
      if (inUrl) inBuf = await decodeAudioUrl(inUrl);
    } catch (e) { console.warn("audition in", e); }
    try {
      if (vtUrl) vtBuf = await decodeAudioUrl(vtUrl);
    } catch (e) { console.warn("audition vt", e); }

    if (!outBuf && !inBuf) {
      return auditionSegueTones({ crossfadeMs: ms, duckDb: Number.isFinite(duckDb) ? duckDb : -11 });
    }

    const gOut = ctx.createGain();
    const gIn = ctx.createGain();
    const gVt = ctx.createGain();
    gOut.gain.value = 0.0001;
    gIn.gain.value = 0.0001;
    gVt.gain.value = 0.0001;
    gOut.connect(procInput);
    gIn.connect(procInput);
    gVt.connect(procInput);

    const now = ctx.currentTime;
    const leadIn = 0.35; // hear outgoing bed before crossfade
    const xfadeSec = ms / 1000;
    const nodes = [];

    function playBuffer(buf, gainNode, when, offsetSec, durationSec) {
      if (!buf) return null;
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(gainNode);
      const off = Math.max(0, Math.min(offsetSec || 0, Math.max(0, buf.duration - 0.05)));
      const dur = durationSec != null
        ? Math.min(durationSec, Math.max(0.05, buf.duration - off))
        : Math.max(0.05, buf.duration - off);
      try {
        src.start(when, off, dur);
      } catch (_) {
        src.start(when, off);
      }
      nodes.push(src);
      return src;
    }

    // Start near end-pulse / outro mark so audition mirrors on-air overlap
    const outOffset = outBuf
      ? Math.max(0, outBuf.duration - Math.max(xfadeSec + leadIn, (outroMarkMs || ms) / 1000 + leadIn))
      : 0;
    const inOffset = inBuf ? Math.min(introMarkMs / 1000, Math.max(0, inBuf.duration * 0.15)) : 0;
    const vtOffset = vtBuf ? Math.min(vtInMs / 1000, Math.max(0, vtBuf.duration * 0.2)) : 0;

    playBuffer(outBuf, gOut, now, outOffset, leadIn + xfadeSec + 0.15);
    gOut.gain.linearRampToValueAtTime(0.85, now + 0.05);

    const xf0 = now + leadIn;
    if (vtBuf) {
      playBuffer(vtBuf, gVt, xf0 - 0.05, vtOffset, xfadeSec + 0.4);
      gVt.gain.setValueAtTime(0.0001, xf0 - 0.05);
      gVt.gain.linearRampToValueAtTime(0.55, xf0 + 0.08);
      gVt.gain.linearRampToValueAtTime(0.0001, xf0 + xfadeSec + 0.25);
    }
    playBuffer(inBuf, gIn, xf0, inOffset, xfadeSec + 0.6);

    const steps = 24;
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const [o, inn] = equalPower(t);
      const at = xf0 + xfadeSec * t;
      const outVal = Math.max(0.0001, 0.85 * o * (duck < 1 ? Math.max(duck, 0.12) : 1));
      gOut.gain.linearRampToValueAtTime(outVal, at);
      gIn.gain.linearRampToValueAtTime(Math.max(0.0001, 0.9 * inn), at);
    }
    gOut.gain.linearRampToValueAtTime(0.0001, xf0 + xfadeSec + 0.05);

    const totalMs = Math.round((leadIn + xfadeSec + 0.45) * 1000);
    setTimeout(() => {
      nodes.forEach((n) => {
        try { n.stop(); } catch (_) {}
        try { n.disconnect(); } catch (_) {}
      });
      [gOut, gIn, gVt].forEach((g) => {
        try { g.disconnect(); } catch (_) {}
      });
      flashEndPulse("A");
    }, totalMs);
    flashFirePulse();
    return totalMs;
  }

  /** Tone fallback when library media is unavailable */
  async function auditionSegueTones(opts) {
    opts = opts || {};
    await resume();
    const ms = Math.max(200, Number(opts.crossfadeMs) || 1500);
    const duck = dbToGain(Number(opts.duckDb) || -11);
    const oscA = ctx.createOscillator();
    const oscB = ctx.createOscillator();
    const gA = ctx.createGain();
    const gB = ctx.createGain();
    oscA.type = "sine";
    oscB.type = "triangle";
    oscA.frequency.value = 220;
    oscB.frequency.value = 330;
    gA.gain.value = 0.0001;
    gB.gain.value = 0.0001;
    oscA.connect(gA);
    oscB.connect(gB);
    gA.connect(procInput);
    gB.connect(procInput);
    const now = ctx.currentTime;
    gA.gain.linearRampToValueAtTime(0.2, now + 0.05);
    const steps = 20;
    for (let i = 1; i <= steps; i++) {
      const t = i / steps;
      const [o, inn] = equalPower(t);
      const at = now + 0.25 + (ms / 1000) * t;
      gA.gain.linearRampToValueAtTime(Math.max(0.0001, 0.2 * o * duck), at);
      gB.gain.linearRampToValueAtTime(Math.max(0.0001, 0.18 * inn), at);
    }
    oscA.start(now);
    oscB.start(now + 0.2);
    oscA.stop(now + 0.35 + ms / 1000);
    oscB.stop(now + 0.4 + ms / 1000);
    return ms;
  }

  global.MQProgramAudio = {
    ensureCtx,
    resume,
    applyProcessing,
    applyAudioRoute,
    syncMixMinusFromRoute,
    startAuxCapture,
    stopAuxCapture,
    setRamps,
    playProgram,
    stopProgram,
    playOnDeck,
    stopDeck,
    startCrossfade,
    syncFromStatus,
    playOneShot,
    getVu,
    flashEndPulse,
    flashFirePulse,
    clearDeckPulse,
    auditionTemplate,
    auditionSegue,
    getAudioRoute() { return Object.assign({}, audioRouteState); },
    getMixMinus() { return Object.assign({}, mixMinusState); },
    get currentProc() { return currentProc; },
    get programDeck() { return programDeck; },
    getDeckState() {
      return {
        programDeck,
        A: { eventId: decks.A.eventId, role: decks.A.role },
        B: { eventId: decks.B.eventId, role: decks.B.role },
      };
    },
  };
})(window);
