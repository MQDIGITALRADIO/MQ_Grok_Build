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
  let rampsState = { profiles: RAMP_DEFAULTS, active_profile: "default", ai_dj_profile: "overnight" };

  // Dual decks A/B → per-deck gains → procInput
  const decks = {
    A: { el: null, src: null, gain: null, eventId: null, role: "idle" },
    B: { el: null, src: null, gain: null, eventId: null, role: "idle" },
  };
  let programDeck = "A";
  let crossfadeTimer = 0;

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

  function flashEndPulse(letter) {
    const id = letter === "B" ? "deck-b" : "deck-a";
    const meterId = letter === "B" ? "deck-b-meter" : "deck-a-meter";
    const deck = document.getElementById(id);
    const meter = document.getElementById(meterId);
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

  /** Segue Editor audition: short equal-power duck demo on tones */
  async function auditionSegue(opts) {
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
      const at = now + 0.2 + (ms / 1000) * t;
      gA.gain.linearRampToValueAtTime(Math.max(0.0001, 0.2 * o * duck), at);
      gB.gain.linearRampToValueAtTime(Math.max(0.0001, 0.18 * inn), at);
    }
    oscA.start(now);
    oscB.start(now + 0.15);
    oscA.stop(now + 0.3 + ms / 1000);
    oscB.stop(now + 0.35 + ms / 1000);
    return ms;
  }

  global.MQProgramAudio = {
    ensureCtx,
    resume,
    applyProcessing,
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
    auditionTemplate,
    auditionSegue,
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
