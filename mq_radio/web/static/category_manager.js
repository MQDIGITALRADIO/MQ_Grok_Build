/* MQ Category / Library Manager — Maestro-dense category + cart browser */
(function () {
  let bundle = null;
  let activeCode = null;
  let dirty = false;

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(msg) {
    const el = $("cat-status");
    if (el) el.textContent = msg || "—";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtDur(ms) {
    const s = Math.round((ms || 0) / 1000);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return m + ":" + String(r).padStart(2, "0");
  }

  function openCategoryManager() {
    const bd = $("cat-backdrop");
    if (!bd) return;
    bd.classList.add("open");
    bd.setAttribute("aria-hidden", "false");
    loadCategories();
  }

  function closeCategoryManager() {
    const bd = $("cat-backdrop");
    if (!bd) return;
    bd.classList.remove("open");
    bd.setAttribute("aria-hidden", "true");
  }

  function activeCategory() {
    if (!bundle || !bundle.categories) return null;
    if (!activeCode && bundle.categories.length) {
      activeCode = bundle.categories[0].code;
    }
    return bundle.categories.find((c) => c.code === activeCode) || null;
  }

  function renderCategoryList() {
    const list = $("cat-list");
    if (!list || !bundle) return;
    const cats = bundle.categories || [];
    if (!cats.length) {
      list.innerHTML = `<div class="cat-empty-hint">No categories yet — click <strong>+ Add</strong>. Tip: drop audio on the desk first, then assign carts here.</div>`;
      return;
    }
    list.innerHTML = cats
      .map((c) => {
        const sel = c.code === activeCode ? " active" : "";
        const kind = c.is_music ? "MUSIC" : "IMG";
        return `<button type="button" class="cat-list-item${sel}" data-code="${escapeHtml(c.code)}">
          <span class="cat-code">${escapeHtml(c.code)}</span>
          <span class="cat-name">${escapeHtml(c.name)}</span>
          <span class="cat-meta">${kind} · ${c.track_count || 0}</span>
        </button>`;
      })
      .join("");
    list.querySelectorAll(".cat-list-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (dirty && !confirm("Discard unsaved category edits?")) return;
        activeCode = btn.getAttribute("data-code");
        dirty = false;
        renderCategoryList();
        fillEditor();
        loadTracks();
      });
    });
  }

  function fillEditor() {
    const c = activeCategory();
    if (!c) {
      const code = $("cat-edit-code");
      if (code) code.value = "";
      const name = $("cat-edit-name");
      if (name) name.value = "";
      setStatus("Add a category to begin");
      return;
    }
    $("cat-edit-code").value = c.code || "";
    $("cat-edit-name").value = c.name || "";
    $("cat-edit-rules").value = c.description || "";
    $("cat-edit-priority").value = c.priority != null ? c.priority : 50;
    $("cat-edit-music").checked = !!c.is_music;
    $("cat-rules-preview").textContent = c.rules_summary || "—";
    setStatus(`${c.code} · ${c.track_count || 0} carts`);
  }

  function markDirty() {
    dirty = true;
    setStatus("modified");
  }

  async function loadCategories() {
    setStatus("loading…");
    try {
      const data = await fetch("/api/categories").then((r) => r.json());
      bundle = data;
      if (!activeCode && data.categories && data.categories.length) {
        activeCode = data.categories[0].code;
      }
      renderCategoryList();
      fillEditor();
      dirty = false;
      setStatus(`${(data.categories || []).length} categories · ${data.total_tracks || 0} carts`);
      await loadTracks();
    } catch (e) {
      setStatus("load failed — is the On-Air engine running?");
      const list = $("cat-list");
      if (list) list.innerHTML = `<div class="cat-empty-hint">Could not load categories.</div>`;
    }
  }

  async function loadTracks() {
    const body = $("cat-tracks-body");
    if (!body) return;
    const code = activeCode || "";
    const q = ($("cat-track-search") && $("cat-track-search").value) || "";
    body.innerHTML = `<tr><td colspan="5" class="cat-empty">Loading…</td></tr>`;
    try {
      const url =
        "/api/categories/tracks?code=" +
        encodeURIComponent(code) +
        "&q=" +
        encodeURIComponent(q);
      const data = await fetch(url).then((r) => r.json());
      const tracks = data.tracks || [];
      if (!tracks.length) {
        body.innerHTML = `<tr><td colspan="5" class="cat-empty">No carts in ${escapeHtml(code) || "—"}. Drop .wav/.mp3 onto the On-Air desk (or Browse…) then Refresh — FILLER carts help ETM under-fills.</td></tr>`;
        return;
      }
      body.innerHTML = tracks
        .map(
          (t) => `<tr>
          <td class="cat-tid">${t.id}</td>
          <td>${escapeHtml(t.artist)}</td>
          <td>${escapeHtml(t.title)}</td>
          <td>${escapeHtml(t.event_type)}</td>
          <td class="cat-dur">${fmtDur(t.duration_ms)}</td>
        </tr>`
        )
        .join("");
    } catch (e) {
      body.innerHTML = `<tr><td colspan="5" class="cat-empty">Load failed</td></tr>`;
    }
  }

  async function saveCategory() {
    const code = ($("cat-edit-code").value || "").trim().toUpperCase();
    const orig = activeCategory();
    if (!orig) return;
    setStatus("saving…");
    // Rename if code changed
    if (code && code !== orig.code) {
      const ren = await fetch("/api/categories/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ old_code: orig.code, new_code: code }),
      }).then((r) => r.json());
      if (!ren.ok) {
        setStatus(ren.error || "rename failed");
        return;
      }
      activeCode = code;
      if (ren.bundle) bundle = ren.bundle;
    }
    const res = await fetch("/api/categories/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: activeCode,
        name: $("cat-edit-name").value,
        description: $("cat-edit-rules").value,
        priority: Number($("cat-edit-priority").value),
        is_music: $("cat-edit-music").checked,
      }),
    }).then((r) => r.json());
    if (!res.ok) {
      setStatus(res.error || "save failed");
      return;
    }
    if (res.bundle) bundle = res.bundle;
    dirty = false;
    renderCategoryList();
    fillEditor();
    setStatus(`saved ${activeCode}`);
  }

  async function addCategory() {
    const code = prompt("New category code (e.g. D, IMG2):");
    if (!code) return;
    const name = prompt("Display name:", code.trim().toUpperCase()) || code.trim().toUpperCase();
    const res = await fetch("/api/categories/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: code.trim().toUpperCase(),
        name: name.trim(),
        description: "",
        priority: 50,
        is_music: false,
      }),
    }).then((r) => r.json());
    if (!res.ok) {
      setStatus(res.error || "add failed");
      alert(res.error || "add failed");
      return;
    }
    if (res.bundle) bundle = res.bundle;
    activeCode = (res.category && res.category.code) || code.trim().toUpperCase();
    dirty = false;
    renderCategoryList();
    fillEditor();
    loadTracks();
    setStatus(`added ${activeCode}`);
  }

  function initCategoryManager() {
    const btn = $("btn-library");
    const btnOpen = $("btn-open-category-manager");
    if (btn) btn.onclick = openCategoryManager;
    if (btnOpen) btnOpen.onclick = openCategoryManager;
    const close = $("btn-cat-close");
    if (close) close.onclick = closeCategoryManager;
    const bd = $("cat-backdrop");
    if (bd) {
      bd.addEventListener("click", (ev) => {
        if (ev.target === bd) closeCategoryManager();
      });
    }
    ["cat-edit-name", "cat-edit-rules", "cat-edit-priority", "cat-edit-code"].forEach((id) => {
      const el = $(id);
      if (el) {
        el.addEventListener("input", markDirty);
        el.addEventListener("change", markDirty);
      }
    });
    const music = $("cat-edit-music");
    if (music) music.addEventListener("change", markDirty);
    const save = $("btn-cat-save");
    if (save) save.onclick = () => saveCategory();
    const add = $("btn-cat-add");
    if (add) add.onclick = () => addCategory();
    const search = $("cat-track-search");
    if (search) {
      let t = null;
      search.addEventListener("input", () => {
        clearTimeout(t);
        t = setTimeout(loadTracks, 200);
      });
    }
    const refresh = $("btn-cat-refresh");
    if (refresh) refresh.onclick = () => loadCategories();
  }

  window.MQCategoryManager = {
    open: openCategoryManager,
    close: closeCategoryManager,
    reload: loadCategories,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCategoryManager);
  } else {
    initCategoryManager();
  }
})();
