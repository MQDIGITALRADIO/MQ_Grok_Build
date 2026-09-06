/* MQ Program bus — Web Audio play path with processing, VU, ramps, one-shots */
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
  let rampGain = null;
  let analyser = null;
  let programEl = null;
  let programSrc = null;
  let oneshotEl = null;
  let oneshotSrc = null;
  let oneshotGain = null;
  let procNodes = [];
  let procInput = null;
  let procOutput = null;
  let currentProc = null;
  let currentEventId = null;
  let vuRaf = 0;
  let lastVuLevels = { playing: false, left: 0.02, right: 0.02, source: "idle" };
  let rampsState = { profiles: RAMP_DEFAULTS, active_profile: "default", ai_dj_profile: "overnight" };

  function ensureCtx() {
    if (ctx) return ctx;
    const AC = global.AudioContext || global.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    masterGain = ctx.createGain();
    masterGain.gain.value = 1;
    rampGain = ctx.createGain();
    rampGain.gain.value = 1;
    oneshotGain = ctx.createGain();
    oneshotGain.gain.value = 1;
    analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.75;
    // Program: rampGain → processing → master → analyser → destination
    // Oneshot: oneshotGain → master (after processing? through processing for consistency)
    procInput = ctx.createGain();
    procOutput = ctx.createGain();
    procInput.gain.value = 1;
    procOutput.gain.value = 1;
    rampGain.connect(procInput);
    oneshotGain.connect(procInput);
    rebuildProcessing(currentProc || defaultProc());
    procOutput.connect(masterGain);
    masterGain.connect(analyser);
    analyser.connect(ctx.destination);
    startVuLoop();
    return ctx;
  }

  function defaultProc() {
    return {
      enabled: true,
      template: "FM",
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
    // keep procInput/procOutput objects; rewire below
  }

  function rebuildProcessing(proc) {
    if (!ctx || !procInput || !procOutput) return;
    currentProc = proc || defaultProc();
    disconnectProc();
    let node = procInput;
    const stages = (currentProc && currentProc.stages) || {};
    const enabled = currentProc && currentProc.enabled !== false;
    const insertBypass = !enabled;

    if (!insertBypass && stages.agc && stages.agc.enabled !== false) {
      const agc = ctx.createDynamicsCompressor();
      const drive = Number(stages.agc.drive_db || 6);
      agc.threshold.value = Number(stages.agc.target_db || -16) - drive * 0.35;
      agc.knee.value = 12;
      agc.ratio.value = 3.5 + drive * 0.15;
      agc.attack.value = Math.max(0.005, (Number(stages.agc.attack_ms) || 50) / 1000);
      agc.release.value = Math.max(0.05, (Number(stages.agc.release_ms) || 1000) / 1000);
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
      // Approximate multiband density with a second compressor + mild presence
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

    // Mild stereo enhance via delay on a duplicate is skipped (mono-safe);
    // output path flavour tweaks makeup
    const makeup = ctx.createGain();
    const tmpl = (currentProc.template || "").toUpperCase();
    makeup.gain.value = tmpl === "DIGITAL" ? 0.92 : 1.05;
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

  function scheduleRampIn(profile) {
    if (!ctx || !rampGain) return;
    const now = ctx.currentTime;
    const ms = Math.max(0, Number(profile.fade_in_ms) || 0);
    const peak = Math.max(0.05, Math.min(1.2, Number(profile.peak_gain) || 1));
    rampGain.gain.cancelScheduledValues(now);
    rampGain.gain.setValueAtTime(0.0001, now);
    if (ms <= 0) {
      rampGain.gain.setValueAtTime(peak, now);
    } else if ((profile.curve || "") === "equal_power") {
      rampGain.gain.setValueAtTime(0.0001, now);
      rampGain.gain.linearRampToValueAtTime(peak, now + ms / 1000);
    } else {
      rampGain.gain.linearRampToValueAtTime(peak, now + ms / 1000);
    }
  }

  function scheduleRampOut(profile, onDone) {
    if (!ctx || !rampGain) {
      if (onDone) onDone();
      return;
    }
    const now = ctx.currentTime;
    const ms = Math.max(0, Number(profile.fade_out_ms) || 0);
    const cur = rampGain.gain.value || 0.0001;
    rampGain.gain.cancelScheduledValues(now);
    rampGain.gain.setValueAtTime(cur, now);
    if (ms <= 0) {
      rampGain.gain.setValueAtTime(0.0001, now);
      if (onDone) onDone();
      return;
    }
    rampGain.gain.linearRampToValueAtTime(0.0001, now + ms / 1000);
    setTimeout(() => onDone && onDone(), ms + 20);
  }

  function ensureProgramElement() {
    if (programEl) return programEl;
    programEl = new Audio();
    programEl.crossOrigin = "anonymous";
    programEl.preload = "auto";
    return programEl;
  }

  function ensureOneshotElement() {
    if (oneshotEl) return oneshotEl;
    oneshotEl = new Audio();
    oneshotEl.crossOrigin = "anonymous";
    oneshotEl.preload = "auto";
    return oneshotEl;
  }

  function connectMedia(el, intoNode) {
    ensureCtx();
    // MediaElementSource can only be created once per element
    if (el === programEl) {
      if (!programSrc) {
        programSrc = ctx.createMediaElementSource(el);
      }
      try { programSrc.disconnect(); } catch (_) {}
      programSrc.connect(intoNode);
      return programSrc;
    }
    if (!oneshotSrc) {
      oneshotSrc = ctx.createMediaElementSource(el);
    }
    try { oneshotSrc.disconnect(); } catch (_) {}
    oneshotSrc.connect(intoNode);
    return oneshotSrc;
  }

  async function resume() {
    const c = ensureCtx();
    if (c && c.state === "suspended") {
      try { await c.resume(); } catch (_) {}
    }
  }

  async function playProgram(url, opts) {
    opts = opts || {};
    if (!url) return false;
    await resume();
    const el = ensureProgramElement();
    connectMedia(el, rampGain);
    const profile = resolveRamp(opts.rampProfile, opts.eventType, opts.overnight);
    currentEventId = opts.eventId || null;
    try {
      if (el.src !== url && !(el.src || "").endsWith(url)) {
        el.src = url;
      }
      el.currentTime = 0;
      scheduleRampIn(profile);
      await el.play();
      return true;
    } catch (err) {
      console.warn("program play failed", err);
      return false;
    }
  }

  function stopProgram(opts) {
    opts = opts || {};
    const profile = resolveRamp(opts.rampProfile, opts.eventType, opts.overnight);
    const el = programEl;
    scheduleRampOut(profile, () => {
      if (el) {
        try { el.pause(); } catch (_) {}
      }
    });
    currentEventId = null;
  }

  async function syncFromStatus(st) {
    if (!st) return;
    if (st.processing) applyProcessing(st.processing);
    if (st.ramps) setRamps(st.ramps);
    const onAir = st.now && st.now.status === "ON_AIR" && st.running;
    const url = st.playable_url || (st.now && st.now.playable_url);
    const eventId = onAir ? st.now.id : null;
    const overnight =
      (st.ramp_profile === "overnight") ||
      (st.ramps && st.ramps.active_profile === "overnight");
    if (onAir && url) {
      if (eventId !== currentEventId || !programEl || programEl.paused) {
        await playProgram(url, {
          eventId,
          eventType: st.now.event_type,
          rampProfile: st.ramp_profile,
          overnight,
        });
      }
    } else if (!onAir && currentEventId) {
      stopProgram({ rampProfile: st.ramp_profile, eventType: (st.now || {}).event_type });
    }
  }

  async function playOneShot(url, label) {
    if (!url) return false;
    await resume();
    const el = ensureOneshotElement();
    connectMedia(el, oneshotGain);
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
        flashEndPulse();
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
    if (deck) {
      deck.classList.add("hotkey-pulse");
      setTimeout(() => deck.classList.remove("hotkey-pulse"), 220);
    }
  }

  function flashEndPulse() {
    const deck = document.getElementById("deck-a");
    const meter = document.getElementById("deck-a-meter");
    if (deck) {
      deck.classList.add("end-ramp", "end-ramp-5");
      setTimeout(() => deck.classList.remove("end-ramp", "end-ramp-5"), 400);
    }
    if (meter) {
      meter.classList.add("end-ramp-5");
      setTimeout(() => meter.classList.remove("end-ramp-5"), 400);
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
    // Map to 0..1 desk LEDs (broadcast-ish)
    const level = Math.min(1, Math.pow(rms * 3.2, 0.7) * 1.15);
    const pk = Math.min(1, peak * 1.4);
    const playing =
      (programEl && !programEl.paused) ||
      (oneshotEl && !oneshotEl.paused) ||
      level > 0.02;
    if (!playing) return { playing: false, left: 0.02, right: 0.02, source: "analyser-idle" };
    // Pseudo L/R from phase offset
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
    // Short tone through the chain so template switches are audible
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

  global.MQProgramAudio = {
    ensureCtx,
    resume,
    applyProcessing,
    setRamps,
    playProgram,
    stopProgram,
    syncFromStatus,
    playOneShot,
    getVu,
    flashEndPulse,
    flashFirePulse,
    auditionTemplate,
    get currentProc() { return currentProc; },
  };
})(window);
