/* MQ Category Clock Editor + Daypart Designer — Maestro-dense */
(function () {
  const EVENT_TYPES = [
    "MUSIC", "ID", "SWEEPER", "PROMO", "VOICE_TRACK", "ETM", "BREAK", "FILLER", "BED",
  ];
  const TIMINGS = ["FLOAT", "HIT", "HARD", "SOFT"];
  const CHAINS = ["AUTO", "MIX", "SEQ", "CUT", "HOLD", "MANUAL"];
  const CANONICAL = new Set(["GENERAL", "OVERNIGHT"]);
  const DEFAULT_HOUR_CLOCK = {
    0: "OVERNIGHT", 1: "OVERNIGHT", 2: "OVERNIGHT", 3: "OVERNIGHT", 4: "OVERNIGHT",
    5: "GENERAL", 6: "GENERAL", 7: "GENERAL", 8: "GENERAL", 9: "GENERAL",
    10: "GENERAL", 11: "GENERAL", 12: "GENERAL", 13: "GENERAL", 14: "GENERAL",
    15: "GENERAL", 16: "GENERAL", 17: "GENERAL", 18: "GENERAL",
    19: "GENERAL", 20: "GENERAL", 21: "GENERAL", 22: "GENERAL",
    23: "OVERNIGHT",
  };

  let bundle = null;
  let activeCode = "GENERAL";
  let dirty = false;
  let daypartDirty = false;

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(msg) {
    const el = $("clock-status");
    if (el) el.textContent = msg || "—";
  }

  function openClockEditor() {
    const bd = $("clock-backdrop");
    if (!bd) return;
    bd.classList.add("open");
    bd.setAttribute("aria-hidden", "false");
    loadClocks();
  }

  function closeClockEditor() {
    const bd = $("clock-backdrop");
    if (!bd) return;
    bd.classList.remove("open");
    bd.setAttribute("aria-hidden", "true");
  }

  function clockCodes() {
    return (bundle && bundle.clocks ? bundle.clocks : []).map((c) => c.code);
  }

  function activeClock() {
    if (!bundle || !bundle.clocks) return null;
    return bundle.clocks.find((c) => c.code === activeCode) || bundle.clocks[0] || null;
  }

  function selectOpts(values, selected) {
    return values
      .map((v) => `<option value="${v}"${v === selected ? " selected" : ""}>${v}</option>`)
      .join("");
  }

  function escapeAttr(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function daypartName(hour) {
    const h = Number(hour);
    if ([23, 0, 1, 2, 3, 4].includes(h)) return "overnight";
    if (h >= 5 && h <= 9) return "morning";
    if (h >= 10 && h <= 14) return "day";
    if (h >= 15 && h <= 18) return "afternoon";
    return "evening";
  }

  function renderDaypartGrid() {
    const grid = $("daypart-grid");
    const legend = $("daypart-legend");
    if (!grid || !bundle) return;
    const codes = clockCodes();
    const map = bundle.hour_clock || {};
    const cells = [];
    for (let h = 0; h < 24; h++) {
      const code = map[String(h)] || map[h] || DEFAULT_HOUR_CLOCK[h] || "GENERAL";
      const dp = daypartName(h);
      cells.push(`<div class="daypart-cell daypart-${dp}" data-hour="${h}" title="${dp}">
        <span class="daypart-hour">${String(h).padStart(2, "0")}</span>
        <select class="daypart-select" data-hour="${h}" aria-label="Clock for hour ${h}">
          ${selectOpts(codes.length ? codes : ["GENERAL", "OVERNIGHT"], code)}
        </select>
      </div>`);
    }
    grid.innerHTML = cells.join("");
    grid.querySelectorAll(".daypart-select").forEach((sel) => {
      sel.addEventListener("change", () => {
        const hour = sel.getAttribute("data-hour");
        if (!bundle.hour_clock) bundle.hour_clock = {};
        bundle.hour_clock[String(hour)] = sel.value;
        daypartDirty = true;
        setStatus(`hour ${hour} → ${sel.value}`);
        renderDaypartLegend();
      });
    });
    renderDaypartLegend();
  }

  function renderDaypartLegend() {
    const legend = $("daypart-legend");
    if (!legend || !bundle) return;
    const map = bundle.hour_clock || {};
    const counts = {};
    for (let h = 0; h < 24; h++) {
      const code = map[String(h)] || DEFAULT_HOUR_CLOCK[h] || "GENERAL";
      counts[code] = (counts[code] || 0) + 1;
    }
    legend.innerHTML = Object.keys(counts)
      .sort()
      .map((c) => `<span class="daypart-chip"><strong>${escapeAttr(c)}</strong> ×${counts[c]}</span>`)
      .join(" ");
  }

  function readDaypartFromGrid() {
    if (!bundle) return {};
    const map = {};
    document.querySelectorAll(".daypart-select").forEach((sel) => {
      map[String(sel.getAttribute("data-hour"))] = sel.value;
    });
    if (Object.keys(map).length) {
      bundle.hour_clock = map;
    }
    return bundle.hour_clock || {};
  }

  function syncTabs() {
    const tabs = $("clock-tabs");
    if (!tabs || !bundle) return;
    const codes = clockCodes();
    if (!codes.includes(activeCode) && codes.length) {
      activeCode = codes[0];
    }
    tabs.innerHTML = codes
      .map(
        (code) =>
          `<button type="button" class="clock-tab${code === activeCode ? " active" : ""}" data-clock="${escapeAttr(code)}">${escapeAttr(code)}</button>`
      )
      .join("");
    tabs.querySelectorAll(".clock-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = btn.getAttribute("data-clock") || "GENERAL";
        if (next === activeCode) return;
        if (dirty) {
          readSlotsIntoClock();
          setStatus("modified (switch — save when ready)");
        }
        activeCode = next;
        syncTabs();
        renderSlots();
        updateResetButton();
        if (!dirty) setStatus(activeCode);
      });
    });
    updateResetButton();
    syncCloneSource();
  }

  function updateResetButton() {
    const reset = $("btn-clock-reset");
    if (!reset) return;
    const can = CANONICAL.has(activeCode);
    reset.disabled = !can;
    reset.title = can
      ? "Restore factory slots for this canonical clock"
      : "Reset only available for GENERAL / OVERNIGHT";
  }

  function syncCloneSource() {
    const sel = $("clock-clone-source");
    if (!sel) return;
    const codes = clockCodes();
    const prefer = codes.includes(activeCode) ? activeCode : codes[0] || "GENERAL";
    sel.innerHTML = selectOpts(codes.length ? codes : ["GENERAL", "OVERNIGHT"], prefer);
  }

  function renderSlots() {
    const clock = activeClock();
    const body = $("clock-slots-body");
    if (!body || !clock) return;
    $("clock-name").value = clock.name || "";
    $("clock-desc").value = clock.description || "";
    const slots = clock.slots || [];
    body.innerHTML = slots
      .map((s, i) => {
        const et = s.event_type || "MUSIC";
        const hard = et === "ETM" || s.timing_mode === "HIT" || s.timing_mode === "HARD";
        return `<tr class="${hard ? "clock-row-hard" : ""}" data-idx="${i}">
          <td class="clock-pos">${i}</td>
          <td><select class="clk-et">${selectOpts(EVENT_TYPES, et)}</select></td>
          <td><input class="clk-cat" type="text" value="${escapeAttr(s.category_code || "")}" maxlength="8" /></td>
          <td><select class="clk-timing">${selectOpts(TIMINGS, s.timing_mode || "FLOAT")}</select></td>
          <td><select class="clk-chain">${selectOpts(CHAINS, s.chain_mode || "AUTO")}</select></td>
          <td><input class="clk-label" type="text" value="${escapeAttr(s.label || "")}" /></td>
          <td><input class="clk-off" type="number" value="${s.offset_sec == null ? "" : s.offset_sec}" step="1" /></td>
          <td><button type="button" class="btn-clock-del" title="Remove">✕</button></td>
        </tr>`;
      })
      .join("");

    body.querySelectorAll("select, input").forEach((el) => {
      el.addEventListener("change", () => {
        dirty = true;
        setStatus("modified");
      });
      el.addEventListener("input", () => {
        dirty = true;
        setStatus("modified");
      });
    });
    body.querySelectorAll(".btn-clock-del").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tr = btn.closest("tr");
        const idx = Number(tr.getAttribute("data-idx"));
        readSlotsIntoClock();
        const c = activeClock();
        if (!c) return;
        c.slots.splice(idx, 1);
        dirty = true;
        renderSlots();
        setStatus("slot removed");
      });
    });
    body.querySelectorAll(".clk-et").forEach((sel) => {
      sel.addEventListener("change", () => {
        if (sel.value === "ETM") {
          const tr = sel.closest("tr");
          const timing = tr.querySelector(".clk-timing");
          const label = tr.querySelector(".clk-label");
          if (timing) timing.value = "HIT";
          if (label && !label.value) label.value = "ETM / stopset window";
        }
        if (sel.value === "VOICE_TRACK") {
          const tr = sel.closest("tr");
          const cat = tr.querySelector(".clk-cat");
          if (cat && !cat.value) cat.value = "VT";
        }
      });
    });
  }

  function readSlotsIntoClock() {
    const clock = activeClock();
    if (!clock) return;
    clock.name = $("clock-name").value.trim() || clock.name;
    clock.description = $("clock-desc").value.trim();
    const rows = [...document.querySelectorAll("#clock-slots-body tr")];
    clock.slots = rows.map((tr, i) => {
      const offRaw = tr.querySelector(".clk-off").value;
      return {
        position: i,
        event_type: tr.querySelector(".clk-et").value,
        category_code: tr.querySelector(".clk-cat").value.trim() || null,
        timing_mode: tr.querySelector(".clk-timing").value,
        chain_mode: tr.querySelector(".clk-chain").value,
        label: tr.querySelector(".clk-label").value.trim(),
        offset_sec: offRaw === "" ? null : Number(offRaw),
        duration_sec: null,
      };
    });
  }

  async function loadClocks() {
    setStatus("loading…");
    try {
      const data = await fetch("/api/clocks").then((r) => r.json());
      bundle = data;
      if (data.event_types) EVENT_TYPES.splice(0, EVENT_TYPES.length, ...data.event_types);
      if (data.chain_modes && data.chain_modes.length) {
        CHAINS.splice(0, CHAINS.length, ...data.chain_modes);
      }
      if (!data.hour_clock || !Object.keys(data.hour_clock).length) {
        bundle.hour_clock = {};
        for (let h = 0; h < 24; h++) {
          bundle.hour_clock[String(h)] = DEFAULT_HOUR_CLOCK[h];
        }
      }
      syncTabs();
      renderDaypartGrid();
      renderSlots();
      dirty = false;
      daypartDirty = false;
      setStatus(`${(data.clocks || []).length} clocks`);
    } catch (e) {
      setStatus("load failed");
    }
  }

  async function saveClocks() {
    readSlotsIntoClock();
    readDaypartFromGrid();
    const clock = activeClock();
    if (!clock) return;
    setStatus("saving…");
    const res = await fetch("/api/clocks/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: clock.code,
        name: clock.name,
        description: clock.description,
        slots: clock.slots,
        hour_clock: bundle && bundle.hour_clock,
      }),
    }).then((r) => r.json());
    if (!res.ok) {
      setStatus(res.error || "save failed");
      return;
    }
    if (res.bundle) bundle = res.bundle;
    else if (res.clock) {
      const idx = bundle.clocks.findIndex((c) => c.code === res.clock.code);
      if (idx >= 0) bundle.clocks[idx] = res.clock;
    }
    dirty = false;
    daypartDirty = false;
    syncTabs();
    renderDaypartGrid();
    renderSlots();
    setStatus(`saved → ${res.json_path || "DB"}`);
    if (document.getElementById("engine-msg")) {
      document.getElementById("engine-msg").textContent =
        `Clock ${clock.code} saved (${(clock.slots || []).length} slots)`;
    }
  }

  async function saveDaypartOnly() {
    readDaypartFromGrid();
    setStatus("saving daypart…");
    const res = await fetch("/api/clocks/daypart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hour_clock: bundle.hour_clock }),
    }).then((r) => r.json());
    if (!res.ok) {
      setStatus(res.error || "daypart save failed");
      return;
    }
    if (res.bundle) bundle = res.bundle;
    else if (res.hour_clock) bundle.hour_clock = res.hour_clock;
    daypartDirty = false;
    renderDaypartGrid();
    setStatus(`daypart saved → ${res.json_path || "DB"}`);
  }

  function applyDaypartDefaults() {
    if (!bundle) return;
    if (!confirm("Restore hour→clock defaults (OVERNIGHT 23–04, GENERAL elsewhere)?")) return;
    bundle.hour_clock = {};
    for (let h = 0; h < 24; h++) {
      bundle.hour_clock[String(h)] = DEFAULT_HOUR_CLOCK[h];
    }
    daypartDirty = true;
    renderDaypartGrid();
    setStatus("defaults applied (save daypart to persist)");
  }

  async function resetCanonical() {
    if (!CANONICAL.has(activeCode)) {
      setStatus("reset only for GENERAL / OVERNIGHT");
      return;
    }
    if (!confirm(`Reset ${activeCode} to canonical factory slots?`)) return;
    const res = await fetch("/api/clocks/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: activeCode }),
    }).then((r) => r.json());
    if (!res.ok) {
      setStatus(res.error || "reset failed");
      return;
    }
    if (res.bundle) bundle = res.bundle;
    dirty = false;
    syncTabs();
    renderDaypartGrid();
    renderSlots();
    setStatus("reset to canonical");
  }

  async function cloneActiveClock() {
    const sourceEl = $("clock-clone-source");
    const codeEl = $("clock-clone-code");
    const nameEl = $("clock-clone-name");
    const source = sourceEl ? sourceEl.value : activeCode;
    const code = codeEl ? codeEl.value.trim() : "";
    const name = nameEl ? nameEl.value.trim() : "";
    if (!code) {
      setStatus("enter new clock code");
      if (codeEl) codeEl.focus();
      return;
    }
    setStatus("cloning…");
    const res = await fetch("/api/clocks/clone", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, code, name: name || undefined }),
    }).then((r) => r.json());
    if (!res.ok) {
      setStatus(res.error || "clone failed");
      return;
    }
    if (res.bundle) bundle = res.bundle;
    activeCode = (res.clock && res.clock.code) || code.toUpperCase();
    dirty = false;
    syncTabs();
    renderDaypartGrid();
    renderSlots();
    if (codeEl) codeEl.value = "";
    if (nameEl) nameEl.value = "";
    setStatus(`cloned ${source} → ${activeCode}`);
  }

  function addSlot() {
    readSlotsIntoClock();
    const clock = activeClock();
    if (!clock) return;
    clock.slots = clock.slots || [];
    clock.slots.push({
      position: clock.slots.length,
      event_type: "MUSIC",
      category_code: "A",
      timing_mode: "FLOAT",
      chain_mode: "MIX",
      label: "New slot",
      offset_sec: null,
      duration_sec: null,
    });
    dirty = true;
    renderSlots();
    setStatus("slot added");
  }

  async function regenHour() {
    if (dirty || daypartDirty) {
      await saveClocks();
    }
    const hourEl = $("clock-regen-hour");
    const hour = hourEl ? Number(hourEl.value) : 12;
    const dateEl = document.getElementById("log-date");
    const date = dateEl && dateEl.value ? dateEl.value : new Date().toISOString().slice(0, 10);
    setStatus(`generating hour ${hour}…`);
    const res = await fetch("/api/log/generate-hour", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date, hour, force: false }),
    }).then((r) => r.json());
    if (res.ok === false || res.error) {
      setStatus(res.error || "generate failed");
      return;
    }
    const fill = res.etm_fill || {};
    const mapped =
      bundle && bundle.hour_clock
        ? bundle.hour_clock[String(hour)] || "?"
        : "?";
    setStatus(
      `hour ${hour} [${mapped}]: ${res.events || "?"} events` +
        (fill.filler_inserted || fill.stretched_ms
          ? ` · ETM fill +${fill.filler_inserted || 0} filler / stretch ${fill.stretched_ms || 0}ms`
          : "")
    );
    if (typeof window.refreshLog === "function") {
      window.refreshLog();
    } else if (typeof window.loadLog === "function") {
      window.loadLog();
    } else {
      const btn = document.getElementById("btn-refresh");
      if (btn) btn.click();
    }
  }

  function initClockEditor() {
    const btnClocks = $("btn-clocks");
    const btnOpen = $("btn-open-clock-editor");
    if (btnClocks) btnClocks.onclick = openClockEditor;
    if (btnOpen) {
      btnOpen.onclick = () => {
        openClockEditor();
      };
    }
    const close = $("btn-clock-close");
    if (close) close.onclick = closeClockEditor;
    const bd = $("clock-backdrop");
    if (bd) {
      bd.addEventListener("click", (ev) => {
        if (ev.target === bd) closeClockEditor();
      });
    }
    const save = $("btn-clock-save");
    if (save) save.onclick = () => saveClocks();
    const reset = $("btn-clock-reset");
    if (reset) reset.onclick = () => resetCanonical();
    const add = $("btn-clock-add-slot");
    if (add) add.onclick = () => addSlot();
    const regen = $("btn-clock-regen");
    if (regen) regen.onclick = () => regenHour();
    const cloneBtn = $("btn-clock-clone");
    if (cloneBtn) cloneBtn.onclick = () => cloneActiveClock();
    const dpSave = $("btn-daypart-save");
    if (dpSave) dpSave.onclick = () => saveDaypartOnly();
    const dpDef = $("btn-daypart-defaults");
    if (dpDef) dpDef.onclick = () => applyDaypartDefaults();
  }

  window.MQClockEditor = {
    open: openClockEditor,
    close: closeClockEditor,
    reload: loadClocks,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initClockEditor);
  } else {
    initClockEditor();
  }
})();
