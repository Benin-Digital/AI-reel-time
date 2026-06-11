import { safeFetch } from "../api.js";
import { $, setBanner } from "../utils/dom.js";
import { store, setStore } from "../store.js";

const AUTO_REFRESH_MS     = 3000;
const AUTO_REFRESH_MAX_MS = 30000;
const BACKOFF_FACTOR      = 1.8;

let _timer = null;

export function renderMetrics(data) {
  const set = (id, val) => { const el = $(id); if (el) el.textContent = val ?? "—"; };
  set("#metricUptime",       data.uptime_seconds != null ? Math.round(data.uptime_seconds) : "—");
  set("#metricEvents",       data.event_count);
  set("#metricExtractions",  data.extraction_count);
  set("#metricScores",       data.score_count);
  set("#metricWorkerStatus", data.worker_alive ? "Actif" : "Arrêté");
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
