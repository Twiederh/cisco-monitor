const statusBadge = document.getElementById("status-badge");
const connectForm = document.getElementById("connect-form");
const connectBtn = document.getElementById("connect-btn");
const disconnectBtn = document.getElementById("disconnect-btn");
const connectError = document.getElementById("connect-error");
const lastResult = document.getElementById("last-result");
const historyEl = document.getElementById("history");
const historyCard = document.getElementById("history-card");
const routerLogCard = document.getElementById("router-log-card");
const routerLogEl = document.getElementById("router-log");
const incidentsCard = document.getElementById("incidents-card");
const incidentsEl = document.getElementById("incidents");
const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = document.querySelectorAll(".tab-panel");
const debugStartBtn = document.getElementById("debug-start-btn");
const debugStopBtn = document.getElementById("debug-stop-btn");
const debugStatusEl = document.getElementById("debug-status");
const debugErrorEl = document.getElementById("debug-error");
const debugResultCard = document.getElementById("debug-result-card");
const debugLogEl = document.getElementById("debug-log");
const debugDownloadBtn = document.getElementById("debug-download-btn");

const POLL_UI_INTERVAL_MS = 3000;

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.toggle("active", b === btn));
    tabPanels.forEach((p) => {
      p.hidden = p.id !== "tab-" + btn.dataset.tab;
    });
  });
});

function hasAnomaly(history) {
  if (!history.length || !Array.isArray(history[0].parsed)) return false;
  const latest = history[0].parsed;
  if (latest.some((r) => (r.reg || "").toLowerCase() === "no")) return true;

  if (history.length > 1 && Array.isArray(history[1].parsed)) {
    const currentLines = new Set(latest.map((r) => r.line));
    const wasPresent = history[1].parsed.some((r) => !currentLines.has(r.line));
    if (wasPresent) return true;
  }
  return false;
}

function renderStatus(snapshot) {
  statusBadge.textContent = snapshot.status;
  statusBadge.className = "badge " + snapshot.status;

  const running = snapshot.status === "running" || snapshot.status === "connecting";
  disconnectBtn.disabled = !running;
  connectBtn.disabled = running;

  connectError.textContent = snapshot.error && snapshot.status === "error" ? snapshot.error : "";

  renderDebugStatus(snapshot.debug || {});

  const history = snapshot.history || [];
  if (history.length === 0) {
    lastResult.textContent = "Noch keine Daten.";
    lastResult.className = "muted";
    historyCard.hidden = true;
    historyEl.innerHTML = "";
    return;
  }

  const labels = snapshot.labels || {};
  const latest = history[0];
  lastResult.className = "";
  lastResult.innerHTML = renderEntry(latest, labels, true);

  if (hasAnomaly(history)) {
    historyCard.hidden = false;
    historyEl.innerHTML = history.map((e) => renderEntry(e, labels, false)).join("");
    routerLogCard.hidden = false;
    routerLogEl.innerHTML = renderRouterLog(snapshot.log_entries || []);
  } else {
    historyCard.hidden = true;
    historyEl.innerHTML = "";
    routerLogCard.hidden = true;
    routerLogEl.innerHTML = "";
  }
}

function renderRouterLog(entries) {
  if (!entries.length) {
    return `<p class="muted">Keine neuen Logmeldungen seit Verbindungsaufbau erfasst.</p>`;
  }
  return entries
    .map((e) => {
      const isError = typeof e.severity === "number" && e.severity <= 4;
      return `<div class="log-line ${isError ? "log-error" : ""}">
        <span class="log-ts">${escapeHtml(e.timestamp)}</span>
        <span>${escapeHtml(e.line)}</span>
      </div>`;
    })
    .join("");
}

function regStatusClass(reg) {
  const v = (reg || "").toLowerCase();
  if (v === "no") return "fail";
  if (v === "yes") return "ok";
  return "unknown";
}

function renderTable(rows, labels) {
  if (!rows.length) {
    return `<p class="muted">Keine Registrierungen in der Ausgabe gefunden.</p>`;
  }
  const body = rows
    .map((r) => {
      const title = labels[r.line] || r.line;
      const dotClass = regStatusClass(r.reg);
      return `<tr>
        <td>
          <span class="line-title">${escapeHtml(title)}</span>
          <button type="button" class="edit-label" data-line="${escapeHtml(r.line)}" data-current="${escapeHtml(title)}" title="Titel bearbeiten">&#9998;</button>
        </td>
        <td><span class="status-dot ${dotClass}" title="reg: ${escapeHtml(r.reg || "?")}"></span></td>
      </tr>`;
    })
    .join("");
  return `<table class="sip-table"><thead><tr><th>Line</th><th>Status</th></tr></thead><tbody>${body}</tbody></table>`;
}

function renderEntry(entry, labels, big) {
  const dotClass = entry.ok ? "ok" : "fail";
  let body;
  if (!entry.ok) {
    body = `<pre class="output">${escapeHtml(entry.error || "Fehler")}</pre>`;
  } else if (Array.isArray(entry.parsed)) {
    body = renderTable(entry.parsed, labels);
  } else {
    body = `<pre class="output">${escapeHtml(entry.output || "(leere Ausgabe)")}</pre>`;
  }
  const wrapClass = big ? "" : "history-entry";
  return `<div class="${wrapClass}">
      ${body}
      <div class="meta"><span class="dot ${dotClass}"></span><span>${entry.timestamp}</span></div>
    </div>`;
}

document.addEventListener("click", async (ev) => {
  const btn = ev.target.closest(".edit-label");
  if (!btn) return;
  const line = btn.dataset.line;
  const next = window.prompt(`Titel für "${line}":`, btn.dataset.current || line);
  if (next === null) return;
  await fetch("/api/labels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ line, title: next.trim() }),
  });
  refreshStatus();
});

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    renderStatus(data);
  } catch (e) {
    // transient network hiccup, ignore
  }
}

connectForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  connectError.textContent = "";
  const fd = new FormData(connectForm);
  const payload = Object.fromEntries(fd.entries());

  const res = await fetch("/api/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    connectError.textContent = data.error || "Verbindung fehlgeschlagen.";
    return;
  }
  renderStatus(data);
});

disconnectBtn.addEventListener("click", async () => {
  const res = await fetch("/api/disconnect", { method: "POST" });
  const data = await res.json();
  renderStatus(data);
});

// --- Störungsfälle -------------------------------------------------------

function renderIncidents(items) {
  if (!items.length) {
    incidentsCard.hidden = true;
    incidentsEl.innerHTML = "";
    return;
  }
  incidentsCard.hidden = false;
  incidentsEl.innerHTML = items
    .map((it) => {
      const stamp = it.filename.replace(/\.log$/, "").replace("_", " ");
      const kb = ((it.size || 0) / 1024).toFixed(1);
      return `<div class="history-entry">
        <div><strong>${escapeHtml(stamp)}</strong> — ${escapeHtml(it.reason || "?")} <span class="muted">(${kb} KB)</span></div>
        <div class="row actions">
          <a href="/api/incidents/${encodeURIComponent(it.filename)}">Log herunterladen</a>
        </div>
      </div>`;
    })
    .join("");
}

async function refreshIncidents() {
  try {
    const res = await fetch("/api/incidents");
    const data = await res.json();
    renderIncidents(data.incidents || []);
  } catch (e) {
    // transient network hiccup, ignore
  }
}

refreshIncidents();
setInterval(refreshIncidents, POLL_UI_INTERVAL_MS);

// --- SIP-Debug ---------------------------------------------------------

function renderDebugStatus(debug) {
  debugStartBtn.disabled = !!debug.active;
  debugStopBtn.disabled = !debug.active;
  if (debug.active) {
    const kb = ((debug.bytes_captured || 0) / 1024).toFixed(1);
    debugStatusEl.textContent = `Aktiv seit ${debug.started_at || "?"} – ${kb} KB erfasst.`;
  } else {
    debugStatusEl.textContent = "Inaktiv.";
  }
}

debugStartBtn.addEventListener("click", async () => {
  debugErrorEl.textContent = "";
  debugStartBtn.disabled = true;
  try {
    const res = await fetch("/api/debug/start", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      debugErrorEl.textContent = data.error || "Debugging konnte nicht gestartet werden.";
      debugStartBtn.disabled = false;
      return;
    }
    renderDebugStatus(data);
  } catch (e) {
    debugErrorEl.textContent = "Debugging konnte nicht gestartet werden.";
    debugStartBtn.disabled = false;
  }
});

function debugLogFilename() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`;
  return `debug-${stamp}.log`;
}

debugDownloadBtn.addEventListener("click", () => {
  const blob = new Blob([debugLogEl.value || ""], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = debugLogFilename();
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
});

debugStopBtn.addEventListener("click", async () => {
  debugErrorEl.textContent = "";
  debugStopBtn.disabled = true;
  try {
    const res = await fetch("/api/debug/stop", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      debugErrorEl.textContent = data.error || "Debugging konnte nicht gestoppt werden.";
      debugStopBtn.disabled = false;
      return;
    }
    debugLogEl.value = data.log || "(keine Ausgabe erfasst)";
    debugResultCard.hidden = false;
    refreshStatus();
  } catch (e) {
    debugErrorEl.textContent = "Debugging konnte nicht gestoppt werden.";
    debugStopBtn.disabled = false;
  }
});

refreshStatus();
setInterval(refreshStatus, POLL_UI_INTERVAL_MS);
