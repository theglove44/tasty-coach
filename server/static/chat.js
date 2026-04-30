// Minimal dashboard + chat logic. Token comes from window.TC_TOKEN.

const TOKEN = window.TC_TOKEN;
const CHAT_SESSION = "default";

const fmt = {
  money(v, signed = false) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const sign = signed && v > 0 ? "+" : "";
    return sign + "$" + Math.round(v).toLocaleString();
  },
  pct(v, decimals = 1) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return v.toFixed(decimals) + "%";
  },
  num(v, decimals = 0) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return v.toFixed(decimals);
  },
};

function withToken(url) {
  const u = new URL(url, window.location.origin);
  u.searchParams.set("token", TOKEN);
  return u.toString();
}

async function loadSnapshot() {
  const res = await fetch(withToken("/api/snapshot"));
  if (!res.ok) {
    document.getElementById("generated-at").textContent = `error: ${res.status}`;
    return;
  }
  const data = await res.json();
  renderKpis(data.kpis);
  renderPositions(data.positions);
  renderAlerts(data.alerts, data.warnings);
  document.getElementById("generated-at").textContent = `as of ${data.generated_at}`;
  // Show 'other' cached scans (different watchlist combinations).
  renderOtherScans(data.cached_scans || [], data.inflight_scans || []);
  // Refresh the gating of the briefing button.
  updateBriefingGate();
  // Refresh the journal feed.
  loadJournal();
}

async function loadJournal() {
  const meta = document.getElementById("journal-meta");
  const list = document.getElementById("journal-list");
  try {
    const res = await fetch(withToken("/api/journal?days=30&limit=50"));
    if (!res.ok) {
      list.innerHTML = `<div class="empty">error ${res.status}</div>`;
      return;
    }
    const data = await res.json();
    const entries = data.entries || [];
    const stats = data.stats || {};
    meta.textContent = `${entries.length} of ${stats.total || 0} total · last 30 days`;
    if (!entries.length) {
      list.innerHTML = `<div class="empty">No decisions recorded yet. The coach will start logging once you ask it for recommendations.</div>`;
      return;
    }
    list.innerHTML = entries.map(renderJournalEntry).join("");
  } catch (e) {
    list.innerHTML = `<div class="empty">error: ${escapeHtml(String(e))}</div>`;
  }
}

function renderJournalEntry(e) {
  const ts = (e.ts || "").replace("T", " ").slice(0, 16);  // YYYY-MM-DD HH:MM
  const kind = e.kind || "note";
  const sym = e.symbol ? `<span class="symbol">${escapeHtml(e.symbol)}</span>` : "";
  const strat = e.strategy ? `<span class="strategy">${escapeHtml(e.strategy)}</span>` : "";
  const rationale = escapeHtml(e.rationale || "");
  return `
    <div class="journal-entry">
      <span class="ts">${escapeHtml(ts)}</span>
      <span class="kind ${escapeHtml(kind)}">${escapeHtml(kind)}</span>
      <span class="body">${sym}${rationale}${strat}</span>
    </div>`;
}

function renderOtherScans(cached, inflight) {
  const host = document.getElementById("scan-other");
  const sel = new Set(getSelectedWatchlists());
  const sameSet = (a) => a.length === sel.size && a.every((x) => sel.has(x));
  const chips = [];
  for (const c of cached) {
    if (sameSet(c.watchlists)) continue;
    chips.push({
      label: `cached: ${c.watchlists.join(", ")} (${c.age_sec}s, ${c.picks} picks)`,
      watchlists: c.watchlists,
    });
  }
  for (const i of inflight) {
    if (sameSet(i.watchlists)) continue;
    chips.push({
      label: `scanning: ${i.watchlists.join(", ")}`,
      watchlists: i.watchlists,
    });
  }
  host.innerHTML = chips
    .map((c, idx) => `<span class="other-chip" data-idx="${idx}">${escapeHtml(c.label)}</span>`)
    .join("");
  host.querySelectorAll(".other-chip").forEach((el) => {
    const idx = Number(el.dataset.idx);
    el.addEventListener("click", () => {
      setSelectedWatchlists(chips[idx].watchlists);
      pollScanStatus();
    });
  });
}

function renderKpis(k) {
  document.getElementById("kpi-nlv").textContent = fmt.money(k.nlv);
  const bp = document.getElementById("kpi-bp");
  // Negative bp_usage_pct flags PM-account over-leverage (EBP > NLV); show
  // it explicitly rather than masking the sign.
  bp.textContent = (k.over_leveraged ? "⚠ " : "") + fmt.pct(k.bp_usage_pct);
  bp.className = "kpi-value " + (k.over_leveraged || k.bp_usage_pct > 50 ? "bad" : k.bp_usage_pct > 35 ? "warn" : "good");
  document.getElementById("kpi-cash").textContent = fmt.money(k.cash_balance);
  const d = document.getElementById("kpi-delta");
  d.textContent = fmt.num(k.portfolio_delta, 1);
  d.className = "kpi-value " + (Math.abs(k.portfolio_delta) > 50 ? "warn" : "");
  document.getElementById("kpi-theta").textContent = fmt.money(k.portfolio_theta, true);
  document.getElementById("kpi-pos").textContent = `${k.position_count} (${k.underlying_count}u)`;
}

function renderPositions(positions) {
  const tbody = document.querySelector("#positions-table tbody");
  if (!positions || !positions.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="muted">No open positions</td></tr>';
    return;
  }
  tbody.innerHTML = positions
    .map((p) => {
      const dte = p.dte === null || p.dte === undefined ? "—" : String(p.dte);
      let dteCls = "num";
      if (typeof p.dte === "number") {
        if (p.dte <= 21) dteCls = "num dte-stop";
        else if (p.dte <= 30) dteCls = "num dte-warn";
      }
      return `<tr>
        <td>${p.underlying || "—"}</td>
        <td>${p.option_type || p.instrument_type || "—"}</td>
        <td>${p.direction || "—"}</td>
        <td class="num">${p.strike != null ? p.strike.toFixed(2) : "—"}</td>
        <td>${p.expiration || "—"}</td>
        <td class="${dteCls}">${dte}</td>
        <td class="num">${p.quantity}</td>
        <td class="num">${p.average_open_price ? p.average_open_price.toFixed(2) : "—"}</td>
        <td class="muted">${p.sector || "—"}</td>
      </tr>`;
    })
    .join("");
}

function renderAlerts(alerts, warnings) {
  const list = document.getElementById("alerts-list");
  const items = [];
  for (const a of alerts || []) {
    const sev = (a.severity || "info").toLowerCase();
    items.push(`<li><span class="alert-sev ${sev}">${sev}</span>${escapeHtml(a.message || "")}</li>`);
  }
  for (const w of warnings || []) {
    items.push(`<li><span class="alert-sev info">note</span>${escapeHtml(w)}</li>`);
  }
  list.innerHTML = items.length ? items.join("") : '<li class="muted">No alerts</li>';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// --- Chat / briefing streaming ---

function appendMsg(role, initialText = "") {
  const stream = document.getElementById("chat-stream");
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  const tag = document.createElement("span");
  tag.className = "role-tag";
  tag.textContent = role === "user" ? "you" : role === "coach" ? "coach" : role;
  const body = document.createElement("span");
  body.className = "msg-body";
  body.textContent = initialText;
  const status = document.createElement("span");
  status.className = "status";
  status.textContent = role === "coach" ? "waiting…" : "";
  status.style.display = role === "coach" ? "block" : "none";
  const cost = document.createElement("span");
  cost.className = "cost";
  div.appendChild(tag);
  div.appendChild(body);
  div.appendChild(status);
  div.appendChild(cost);
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
  return { body, status, cost, container: div };
}

function streamSSE(url, refs, { onDone, onError } = {}) {
  return new Promise((resolve) => {
    const es = new EventSource(url);
    let firstToken = true;
    es.addEventListener("status", (e) => {
      refs.status.textContent = e.data;
      refs.status.classList.remove("idle");
      refs.status.style.display = "block";
    });
    es.addEventListener("token", (e) => {
      if (firstToken) {
        // First visible token — hide the spinner status.
        refs.status.style.display = "none";
        firstToken = false;
      }
      refs.body.textContent += e.data;
      const stream = document.getElementById("chat-stream");
      stream.scrollTop = stream.scrollHeight;
    });
    es.addEventListener("cost", (e) => {
      refs.cost.textContent = `cost: ${e.data}`;
    });
    es.addEventListener("done", () => {
      refs.status.style.display = "none";
      es.close();
      onDone && onDone();
      resolve();
    });
    es.addEventListener("error", (e) => {
      const data = e.data || "stream interrupted";
      refs.body.textContent += `\n[error: ${data}]`;
      refs.status.style.display = "none";
      es.close();
      onError && onError(e);
      resolve();
    });
  });
}

document.getElementById("briefing-btn").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  if (btn.disabled) return;
  const watchlists = getSelectedWatchlists();
  if (!watchlists.length) {
    alert("Pick at least one watchlist first.");
    return;
  }
  btn.disabled = true;
  const prev = btn.textContent;
  btn.textContent = "Briefing…";
  const refs = appendMsg("coach", "");
  try {
    const url = new URL("/api/briefing", window.location.origin);
    for (const w of watchlists) url.searchParams.append("watchlists", w);
    url.searchParams.set("token", TOKEN);
    await streamSSE(url.toString(), refs);
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
    updateBriefingGate();
  }
});

document.getElementById("chat-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const input = document.getElementById("chat-input");
  const q = input.value.trim();
  if (!q) return;
  input.value = "";
  appendMsg("user", q);
  const target = appendMsg("coach", "");
  const url = new URL("/api/chat", window.location.origin);
  url.searchParams.set("q", q);
  url.searchParams.set("session_id", CHAT_SESSION);
  url.searchParams.set("token", TOKEN);
  await streamSSE(url.toString(), target);
});

document.getElementById("chat-reset-btn").addEventListener("click", async () => {
  await fetch(withToken(`/api/chat/reset?session_id=${CHAT_SESSION}`), { method: "POST" });
  document.getElementById("chat-stream").innerHTML = "";
});

document.getElementById("refresh-btn").addEventListener("click", loadSnapshot);

// --- Watchlist picker / scan flow ---

const STORAGE_KEY = "tc_watchlists";

function getSelectedWatchlists() {
  return Array.from(document.querySelectorAll("#watchlist-picker input:checked")).map((el) => el.value);
}

function setSelectedWatchlists(names) {
  const want = new Set(names);
  document.querySelectorAll("#watchlist-picker input").forEach((el) => {
    el.checked = want.has(el.value);
  });
  persistSelection();
  pollScanStatus();
}

function persistSelection() {
  const sel = getSelectedWatchlists();
  if (sel.length) localStorage.setItem(STORAGE_KEY, JSON.stringify(sel));
  else localStorage.removeItem(STORAGE_KEY);
}

function setScanStatus(state, text) {
  const el = document.getElementById("scan-status");
  el.className = `scan-status ${state}`;
  el.textContent = text;
}

function updateBriefingGate(state = null) {
  const btn = document.getElementById("briefing-btn");
  const sel = getSelectedWatchlists();
  if (!sel.length) {
    btn.disabled = true;
    btn.title = "Pick at least one watchlist";
    btn.textContent = "Run morning briefing";
    return;
  }
  if (state === "ready") {
    btn.disabled = false;
    btn.title = "";
    btn.textContent = `Run morning briefing (${sel.length} list${sel.length === 1 ? "" : "s"})`;
  } else if (state === "scanning") {
    btn.disabled = true;
    btn.title = "Scan in progress…";
    btn.textContent = "Run morning briefing (scanning…)";
  } else {
    btn.disabled = true;
    btn.title = "Start a trade scan first";
    btn.textContent = "Run morning briefing";
  }
}

let _allWatchlists = [];      // [{name, kind}]
let _publicCollapsed = true;  // public section starts collapsed
let _searchTerm = "";

async function loadWatchlists() {
  const res = await fetch(withToken("/api/watchlists"));
  if (!res.ok) {
    document.getElementById("watchlist-picker").innerHTML =
      `<div class="empty">error loading watchlists (${res.status})</div>`;
    return;
  }
  const data = await res.json();
  _allWatchlists = data.watchlists || [];
  renderWatchlistPicker();
}

function renderWatchlistPicker() {
  const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  const checked = new Set(stored);
  const term = _searchTerm.trim().toLowerCase();
  const matches = (w) => !term || w.name.toLowerCase().includes(term);

  const priv = _allWatchlists.filter((w) => w.kind === "private" && matches(w));
  const pub = _allWatchlists.filter((w) => w.kind === "public" && matches(w));

  const host = document.getElementById("watchlist-picker");
  if (!priv.length && !pub.length) {
    host.innerHTML = `<div class="empty">no watchlists match "${escapeHtml(_searchTerm)}"</div>`;
    return;
  }

  const row = (w) => `
    <label>
      <input type="checkbox" value="${escapeHtml(w.name)}" ${checked.has(w.name) ? "checked" : ""}>
      <span class="name">${escapeHtml(w.name)}</span>
    </label>`;

  // When searching, auto-expand public so the user sees matches.
  const publicCollapsed = _publicCollapsed && !term;

  let html = "";
  if (priv.length) {
    html += `
      <div class="group-header">
        <span>Your watchlists</span>
        <span>${priv.length}</span>
      </div>
      <div class="group-body">${priv.map(row).join("")}</div>
    `;
  }
  if (pub.length) {
    html += `
      <div class="group-header collapsible ${publicCollapsed ? "collapsed" : ""}" data-section="public">
        <span>Public watchlists</span>
        <span>${pub.length}</span>
      </div>
      <div class="group-body ${publicCollapsed ? "hidden" : ""}" data-section="public-body">${pub.map(row).join("")}</div>
    `;
  }
  host.innerHTML = html;

  host.querySelectorAll("input[type='checkbox']").forEach((el) => {
    el.addEventListener("change", () => {
      persistSelection();
      updateSelCount();
      pollScanStatus();
    });
  });
  host.querySelectorAll(".group-header.collapsible").forEach((el) => {
    el.addEventListener("click", () => {
      _publicCollapsed = !_publicCollapsed;
      renderWatchlistPicker();
    });
  });

  updateSelCount();
  updateBriefingGate();
}

function updateSelCount() {
  const n = getSelectedWatchlists().length;
  const el = document.getElementById("scan-selcount");
  el.textContent = `${n} selected`;
  el.classList.toggle("has-sel", n > 0);
}

document.getElementById("scan-search").addEventListener("input", (ev) => {
  _searchTerm = ev.target.value;
  renderWatchlistPicker();
});

document.getElementById("scan-clear").addEventListener("click", () => {
  document.querySelectorAll("#watchlist-picker input:checked").forEach((el) => (el.checked = false));
  persistSelection();
  updateSelCount();
  pollScanStatus();
});

let pollTimer = null;
async function pollScanStatus() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  const sel = getSelectedWatchlists();
  if (!sel.length) {
    setScanStatus("idle", "pick a watchlist");
    updateBriefingGate();
    return;
  }
  const url = new URL("/api/scan/status", window.location.origin);
  for (const w of sel) url.searchParams.append("watchlists", w);
  url.searchParams.set("token", TOKEN);
  let st;
  try {
    const res = await fetch(url.toString());
    if (!res.ok) {
      setScanStatus("error", `status ${res.status}`);
      updateBriefingGate();
      return;
    }
    st = await res.json();
  } catch (e) {
    setScanStatus("error", "network");
    return;
  }
  if (st.state === "ready") {
    setScanStatus("ready", `ready (${st.age_sec}s old, ${st.picks} picks)`);
    updateBriefingGate("ready");
    renderPicksPanel(st);
  } else if (st.state === "inflight") {
    setScanStatus("scanning", "scanning watchlists…");
    updateBriefingGate("scanning");
    hidePicksPanel();
    pollTimer = setTimeout(pollScanStatus, 5000);
  } else {
    setScanStatus("idle", "idle — click Start scan");
    updateBriefingGate();
    hidePicksPanel();
  }
}

function hidePicksPanel() {
  document.getElementById("picks-panel").classList.add("hidden");
}

function renderPicksPanel(st) {
  const panel = document.getElementById("picks-panel");
  const meta = document.getElementById("picks-meta");
  const list = document.getElementById("picks-list");
  const rej = document.getElementById("picks-rejections");
  const rejBody = document.getElementById("picks-rejections-body");

  panel.classList.remove("hidden");
  const wls = (st.watchlists || []).join(", ");
  meta.textContent = `${wls} · ${st.age_sec}s old · ${st.rejected_count || 0} rejected`;

  const top = st.top || [];
  if (!top.length) {
    list.innerHTML = `<div class="picks-empty">No picks survived all gates. See rejection summary below for why.</div>`;
  } else {
    list.innerHTML = top.map(renderPickCard).join("");
  }

  // Rejection summary
  const summary = st.rejected_summary || {};
  const reasons = Object.entries(summary).sort((a, b) => b[1] - a[1]);
  if (reasons.length) {
    rej.style.display = "";
    rejBody.innerHTML = reasons
      .map(([reason, n]) => `<div class="rej-row"><span class="reason">${escapeHtml(reason)}</span><span class="count">${n}</span></div>`)
      .join("");
  } else {
    rej.style.display = "none";
  }
}

function renderPickCard(p) {
  const fmt2 = (v) => (v == null ? "—" : Number(v).toFixed(2));
  const fmt0 = (v) => (v == null ? "—" : Math.round(Number(v)));
  const credit = p.credit != null ? `$${(p.credit * 100).toFixed(0)}` : "—";
  const maxLoss = p.max_loss_dollars != null ? `$${fmt0(p.max_loss_dollars)}` : (p.max_loss != null ? `$${(p.max_loss * 100).toFixed(0)}` : "—");
  const delta = p.short_delta != null ? Number(p.short_delta).toFixed(2) : "—";
  const score = p.score != null ? `${Number(p.score).toFixed(1)}/100` : "";

  const legsLine = (p.legs || [])
    .map((leg) => {
      const action = leg.action || leg.side || "?";
      const type = leg.option_type || leg.type || "?";
      const strike = leg.strike != null ? Number(leg.strike) : null;
      const ld = leg.delta != null ? Number(leg.delta).toFixed(2) : null;
      return `${action} ${type} ${strike != null ? strike : "?"}${ld != null ? ` Δ${ld >= 0 ? "+" : ""}${ld}` : ""}`;
    })
    .join("  /  ");

  const rec = p.recommended_contracts;
  const pctRisk = p.pct_nlv_at_risk;
  const pct1 = p.pct_nlv_at_risk_one_contract;
  let sizeHTML = "";
  if (rec === 0) {
    const oneStr = pct1 != null ? ` — 1 contract = ${(pct1 * 100).toFixed(1)}% NLV` : "";
    sizeHTML = `<div class="pick-size size-skip">SKIP: exceeds per-trade risk budget${oneStr}</div>`;
  } else if (rec != null) {
    const pctStr = pctRisk != null ? ` (${(pctRisk * 100).toFixed(1)}% NLV at risk)` : "";
    sizeHTML = `<div class="pick-size size-ok">Recommended size: ${rec} contract${rec === 1 ? "" : "s"}${pctStr}</div>`;
  }

  return `
    <div class="pick-card">
      <div class="pick-row1">
        <span><span class="pick-symbol">${escapeHtml(p.symbol)}</span> <span class="pick-structure">${escapeHtml(p.structure || "")}</span></span>
        <span class="pick-score">${escapeHtml(score)}</span>
      </div>
      <div class="pick-row2">
        <span><span class="label">EXP</span><span class="num">${escapeHtml(p.expiration || "")}</span></span>
        <span><span class="label">DTE</span><span class="num">${p.dte ?? "—"}</span></span>
        <span><span class="label">CREDIT</span><span class="num">${credit}</span></span>
        <span><span class="label">MAX LOSS</span><span class="num">${maxLoss}</span></span>
        <span><span class="label">SHORT Δ</span><span class="num">${delta}</span></span>
        ${p.sector ? `<span><span class="label">SECTOR</span>${escapeHtml(p.sector)}</span>` : ""}
      </div>
      ${legsLine ? `<div class="pick-legs">${escapeHtml(legsLine)}</div>` : ""}
      ${sizeHTML}
      ${p.summary_reason ? `<div class="pick-summary">${escapeHtml(p.summary_reason)}</div>` : ""}
    </div>
  `;
}

async function startScan() {
  const sel = getSelectedWatchlists();
  if (!sel.length) {
    alert("Pick at least one watchlist first.");
    return;
  }
  const btn = document.getElementById("scan-start-btn");
  btn.disabled = true;
  setScanStatus("scanning", "starting…");
  const url = new URL("/api/scan/start", window.location.origin);
  for (const w of sel) url.searchParams.append("watchlists", w);
  url.searchParams.set("token", TOKEN);
  try {
    const res = await fetch(url.toString(), { method: "POST" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setScanStatus("error", body.detail || `error ${res.status}`);
      updateBriefingGate();
      return;
    }
    pollScanStatus();
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("scan-start-btn").addEventListener("click", startScan);

// --- Settings drawer ---

let _settingsData = null;  // {groups, settings}

function openSettings() {
  document.getElementById("settings-drawer").classList.remove("hidden");
  loadSettings();
}

function closeSettings() {
  document.getElementById("settings-drawer").classList.add("hidden");
  setSettingsStatus("", "");
}

async function loadSettings() {
  setSettingsStatus("loading…", "");
  const res = await fetch(withToken("/api/settings"));
  if (!res.ok) {
    setSettingsStatus(`error ${res.status}`, "error");
    return;
  }
  _settingsData = await res.json();
  renderSettings();
  setSettingsStatus("", "");
}

function renderSettings() {
  const body = document.getElementById("settings-body");
  if (!_settingsData) return;
  const { groups, settings } = _settingsData;
  body.innerHTML = groups.map((g) => {
    const rows = g.keys
      .filter((k) => settings[k])
      .map((k) => renderSettingRow(settings[k]))
      .join("");
    return `
      <div class="settings-group">
        <h3>${escapeHtml(g.label)}</h3>
        ${rows}
      </div>`;
  }).join("");

  body.querySelectorAll("input[data-key]").forEach((el) => {
    el.addEventListener("input", () => onInputChange(el));
    el.addEventListener("blur", () => saveIfDirty(el));
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); el.blur(); }
      if (ev.key === "Escape") { ev.preventDefault(); revertInput(el); }
    });
  });
  body.querySelectorAll(".reset-btn[data-key]").forEach((el) => {
    el.addEventListener("click", () => resetKey(el.dataset.key));
  });
}

function renderSettingRow(s) {
  const isInt = s.type === "integer";
  const isOptional = s.type === "optional_number";
  const value = s.value === null || s.value === undefined ? "" : s.value;
  const step = isInt ? "1" : "0.01";
  const placeholder = isOptional ? "(none)" : "";
  return `
    <div class="settings-row">
      <div class="label-col">
        <span class="key">${escapeHtml(s.key)}</span>
        <span class="desc">${escapeHtml(s.description)}</span>
        <span class="default-hint">default: ${escapeHtml(String(s.default))}</span>
      </div>
      <input type="${isInt ? "number" : (isOptional ? "text" : "number")}"
             data-key="${escapeHtml(s.key)}"
             data-original="${escapeHtml(String(value))}"
             value="${escapeHtml(String(value))}"
             step="${step}" placeholder="${escapeHtml(placeholder)}">
      <button class="reset-btn" data-key="${escapeHtml(s.key)}" title="Reset to default">↺</button>
    </div>`;
}

function onInputChange(el) {
  const original = el.dataset.original;
  el.classList.toggle("dirty", el.value !== original);
}

function revertInput(el) {
  el.value = el.dataset.original;
  el.classList.remove("dirty");
}

async function saveIfDirty(el) {
  if (!el.classList.contains("dirty")) return;
  const key = el.dataset.key;
  const raw = el.value.trim();
  let value;
  if (raw === "" && _settingsData.settings[key].type === "optional_number") {
    value = null;
  } else if (raw === "") {
    revertInput(el);
    return;
  } else {
    const n = Number(raw);
    if (Number.isNaN(n)) {
      setSettingsStatus(`'${raw}' is not a number`, "error");
      revertInput(el);
      return;
    }
    value = n;
  }
  setSettingsStatus(`saving ${key}…`, "");
  const res = await fetch(withToken("/api/settings"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [key]: value }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    setSettingsStatus(body.detail || `error ${res.status}`, "error");
    revertInput(el);
    return;
  }
  _settingsData = body;
  renderSettings();
  setSettingsStatus(`saved ${key} (cache cleared)`, "ok");
  // Cache cleared on server side — refresh scan status to reflect.
  pollScanStatus();
  loadSnapshot();
}

async function resetKey(key) {
  setSettingsStatus(`resetting ${key}…`, "");
  const res = await fetch(withToken("/api/settings/reset"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keys: [key] }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    setSettingsStatus(body.detail || `error ${res.status}`, "error");
    return;
  }
  _settingsData = body;
  renderSettings();
  setSettingsStatus(`reset ${key}`, "ok");
  pollScanStatus();
  loadSnapshot();
}

async function resetAll() {
  if (!confirm("Reset ALL settings to defaults?")) return;
  setSettingsStatus("resetting all…", "");
  const res = await fetch(withToken("/api/settings/reset"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    setSettingsStatus(body.detail || `error ${res.status}`, "error");
    return;
  }
  _settingsData = body;
  renderSettings();
  setSettingsStatus("all settings reset to defaults", "ok");
  pollScanStatus();
  loadSnapshot();
}

function setSettingsStatus(text, kind) {
  const el = document.getElementById("settings-status");
  el.textContent = text;
  el.className = kind === "ok" ? "ok" : kind === "error" ? "error" : "muted";
}

document.getElementById("settings-btn").addEventListener("click", openSettings);
document.getElementById("settings-reset-all").addEventListener("click", resetAll);
document.getElementById("settings-drawer").addEventListener("click", (ev) => {
  if (ev.target.matches("[data-close]")) closeSettings();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !document.getElementById("settings-drawer").classList.contains("hidden")) {
    closeSettings();
  }
});

loadSnapshot();
loadWatchlists();
