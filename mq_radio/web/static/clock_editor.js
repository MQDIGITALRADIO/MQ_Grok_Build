/* MQ Category Clock Editor — Maestro-dense slot grid for GENERAL / OVERNIGHT */
(function () {
  const EVENT_TYPES = [
    "MUSIC", "ID", "SWEEPER", "PROMO", "VOICE_TRACK", "ETM", "BREAK", "FILLER", "BED",
  ];
  const TIMINGS = ["FLOAT", "HIT", "HARD", "SOFT"];
  const CHAINS = ["AUTO", "MIX", "SEQ", "HOLD", "MANUAL"];

  let bundle = null;
  let activeCode = "GENERAL";
  let dirty = false;

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

  function activeClock() {
    if (!bundle || !bundle.clocks) return null;
    return bundle.clocks.find((c) => c.code === activeCode) || bundle.clocks[0] || null;
  }

  function selectOpts(values, selected) {
    return values
      .map((v) => `<option value="${v}"${v === selected ? " selected" : ""}>${v}</option>`)
      .join("");
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

  function escapeAttr(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
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
      syncTabs();
      renderSlots();
      dirty = false;
      setStatus(`${(data.clocks || []).length} clocks`);
    } catch (e) {
      setStatus("load failed");
    }
  }

  function syncTabs() {
    document.querySelectorAll(".clock-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-clock") === activeCode);
    });
  }

  async function saveClocks() {
    readSlotsIntoClock();
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
    renderSlots();
    setStatus(`saved → ${res.json_path || "DB"}`);
    if (document.getElementById("engine-msg")) {
      document.getElementById("engine-msg").textContent =
        `Clock ${clock.code} saved (${(clock.slots || []).length} slots)`;
    }
  }

  async function resetCanonical() {
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
    renderSlots();
    setStatus("reset to canonical");
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
    if (dirty) {
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
    if (!res.ok && res.ok !== undefined) {
      setStatus(res.error || "generate failed");
      return;
    }
    const fill = res.etm_fill || {};
    setStatus(
      `hour ${hour}: ${res.events || "?"} events` +
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
    document.querySelectorAll(".clock-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (dirty) readSlotsIntoClock();
        activeCode = btn.getAttribute("data-clock") || "GENERAL";
        syncTabs();
        renderSlots();
        setStatus(activeCode);
      });
    });
    const save = $("btn-clock-save");
    if (save) save.onclick = () => saveClocks();
    const reset = $("btn-clock-reset");
    if (reset) reset.onclick = () => resetCanonical();
    const add = $("btn-clock-add-slot");
    if (add) add.onclick = () => addSlot();
    const regen = $("btn-clock-regen");
    if (regen) regen.onclick = () => regenHour();
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
