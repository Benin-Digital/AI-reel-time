import { safeFetch } from "../api.js";
import { $, setBanner } from "../utils/dom.js";
import { store, setStore } from "../store.js";

const AUTO_REFRESH_MS     = 3000;
const AUTO_REFRESH_MAX_MS = 30000;
const BACKOFF_FACTOR      = 1.8;

let _timer = null;

export function renderMetrics(data) {
  _updateDonut("cv",  data.active_cv_count,  data.archived_cv_count);
  _updateDonut("job", data.active_job_count, data.archived_job_count);
  _updateScoreDistribution(data.score_high_count, data.score_mid_count, data.score_low_count);
  _setSidebarHealth(data.worker_alive ? "up" : "down", data.worker_alive ? "Système opérationnel" : "Worker arrêté");
}

// Visible on every panel (unlike the metric cards, only rendered on the
// Dashboard) so a recruiter can tell processing is alive without leaving
// whatever they're doing. Reuses .uptime-dot/.uptime-label so it looks
// like the exact same indicator, just smaller.
function _setSidebarHealth(state, label) {
  const dot = $("#sidebarHealthDot");
  const labelEl = $("#sidebarHealthLabel");
  if (dot) dot.classList.toggle("uptime-dot--down", state === "down");
  if (labelEl) {
    labelEl.classList.toggle("uptime-label--down", state === "down");
    labelEl.textContent = label;
  }
}

// Circumference of the donut's r=15.9155 circle is ~100, so a percentage
// (0-100) can be used directly as the stroke-dasharray's "drawn" length.
function _updateDonut(prefix, active, archived) {
  const active_n   = Number(active) || 0;
  const archived_n = Number(archived) || 0;
  const total = active_n + archived_n;
  const pct = total > 0 ? Math.round((active_n / total) * 100) : 0;

  const fillEl = document.querySelector(`#${prefix}StateDonut .donut__fill`);
  if (fillEl) fillEl.setAttribute("stroke-dasharray", `${pct} ${100 - pct}`);

  const valueEl = $(`#${prefix}StateActiveValue`);
  if (valueEl) valueEl.textContent = total > 0 ? String(active_n) : "–";

  const activeTextEl = $(`#${prefix}StateActiveText`);
  if (activeTextEl) activeTextEl.textContent = String(active_n);
  const archivedTextEl = $(`#${prefix}StateArchivedText`);
  if (archivedTextEl) archivedTextEl.textContent = String(archived_n);
}

function _updateScoreDistribution(high, mid, low) {
  const high_n = Number(high) || 0;
  const mid_n  = Number(mid)  || 0;
  const low_n  = Number(low)  || 0;
  const total  = high_n + mid_n + low_n;
  const pct = (n) => (total > 0 ? (n / total) * 100 : 0);

  const setWidth = (id, value) => { const el = $(id); if (el) el.style.width = `${value}%`; };
  setWidth("#scoreDistHigh", pct(high_n));
  setWidth("#scoreDistMid",  pct(mid_n));
  setWidth("#scoreDistLow",  pct(low_n));

  const set = (id, val) => { const el = $(id); if (el) el.textContent = val; };
  set("#scoreDistHighText", high_n);
  set("#scoreDistMidText",  mid_n);
  set("#scoreDistLowText",  low_n);
}

async function fetchMetrics() {
  if (store.autoRefreshInFlight) return;
  setStore({ autoRefreshInFlight: true });
  try {
    const data = await safeFetch("/metrics");
    renderMetrics(data);
    setBanner($("#apiStatusBanner"), "");
    setStore({ autoRefreshDelayMs: AUTO_REFRESH_MS });
  } catch (err) {
    if (err.name !== "AuthError") {
      setBanner($("#apiStatusBanner"), `API inaccessible — ${err.message}`, "error");
      _setSidebarHealth("down", "API inaccessible");
      const next = Math.min(store.autoRefreshDelayMs * BACKOFF_FACTOR, AUTO_REFRESH_MAX_MS);
      setStore({ autoRefreshDelayMs: next });
    }
  } finally {
    setStore({ autoRefreshInFlight: false });
  }
}

export function startAutoRefresh() {
  stopAutoRefresh();
  const tick = async () => {
    await fetchMetrics();
    _timer = setTimeout(tick, store.autoRefreshDelayMs);
  };
  tick();
}

export function stopAutoRefresh() {
  if (_timer) { clearTimeout(_timer); _timer = null; }
}

export function initMetrics() {
  fetchMetrics();
}
