function todayISO() {
  const d = new Date();
  const z = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

function fmtDur(ms) {
  if (!ms) return "—";
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

async function refresh() {
  const date = document.getElementById("log-date").value || todayISO();
  const st = await fetch(`/api/status?date=${date}`).then((r) => r.json());
  const np = st.now;
  document.getElementById("np-title").textContent = np ? np.title : "No committed events";
  document.getElementById("np-artist").textContent = np ? (np.artist || np.event_type) : "—";
  document.getElementById("np-meta").textContent = np
    ? `${np.event_type} · ${np.chain_mode}/${np.timing_mode} · pos ${np.position} · ${np.status}`
    : `Total events: ${st.total || 0}`;

  const log = await fetch(`/api/log?date=${date}`).then((r) => r.json());
  const body = document.getElementById("log-body");
  body.innerHTML = "";
  (log.events || []).forEach((e) => {
    const tr = document.createElement("tr");
    if (e.status === "ON_AIR") tr.className = "on-air";
    if (e.status === "COMPLETED" || e.status === "SKIPPED") tr.className = "completed";
    tr.innerHTML = `
      <td>${e.position}</td>
      <td>${(e.scheduled_at || "").replace("T", " ")}</td>
      <td>${e.event_type}</td>
      <td>${e.chain_mode}</td>
      <td>${e.timing_mode}</td>
      <td>${e.artist || ""}</td>
      <td>${e.title || ""}</td>
      <td>${fmtDur(e.duration_ms)}</td>
      <td>${e.status}</td>`;
    body.appendChild(tr);
  });
}

async function postAction(path) {
  const date = document.getElementById("log-date").value || todayISO();
  const res = await fetch(`${path}?date=${date}`, { method: "POST" }).then((r) => r.json());
  document.getElementById("engine-msg").textContent = res.message || "";
  await refresh();
}

function tickClock() {
  document.getElementById("wallclock").textContent = new Date().toLocaleTimeString();
}

document.getElementById("log-date").value = todayISO();
document.getElementById("btn-refresh").onclick = refresh;
document.getElementById("btn-play").onclick = () => postAction("/api/play");
document.getElementById("btn-stop").onclick = () => postAction("/api/stop");
document.getElementById("btn-skip").onclick = () => postAction("/api/skip");
document.getElementById("btn-step").onclick = () => postAction("/api/step");
document.getElementById("log-date").onchange = refresh;
setInterval(tickClock, 1000);
tickClock();
refresh();
setInterval(refresh, 5000);
