import { API_BASE } from "./config.js";
import { store, clearAuth } from "./store.js";
import { openModal } from "./utils/dom.js";

// Default timeout for short endpoints (list, details). Heavy endpoints
// (/matches/{id}/explain, /matches/recompute, parsed-pdf) need more — pass
// `timeout: 60000` explicitly on those calls.
const REQUEST_TIMEOUT_MS = 30000;
const MAX_RETRIES = 2;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const isAbortError = (err) =>
  err && (err.name === "AbortError" || err.name === "TimeoutError");

const withTimeout = async (url, options, ms) => {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...options, signal: ctrl.signal });
  } catch (err) {
    if (isAbortError(err)) {
      const timeoutErr = new Error(`Délai d'attente dépassé (${Math.round(ms / 1000)} s).`);
      timeoutErr.name = "TimeoutError";
      throw timeoutErr;
    }
    throw err;
  } finally {
    clearTimeout(tid);
  }
};

export const safeFetch = async (path, options = {}) => {
  const {
    method = "GET",
    headers = {},
    body = null,
    json = false,
    skipAuth = false,
    retries = MAX_RETRIES,
    allowAuthErrors = false,
    timeout = REQUEST_TIMEOUT_MS,
  } = options;

  const reqHeaders = new Headers(headers);
  if (json) reqHeaders.set("Content-Type", "application/json");
  if (!skipAuth && store.authToken) reqHeaders.set("Authorization", `Bearer ${store.authToken}`);

  const url = `${API_BASE}${path}`;
  let lastError;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await withTimeout(url, { method, headers: reqHeaders, body }, timeout);

      if (res.status === 401) {
        if (allowAuthErrors) {
          const msg = await res.text();
          throw new Error(msg || "Authentification requise");
        }
        clearAuth();
        const loginModal = document.getElementById("loginModal");
        if (loginModal) openModal(loginModal);
        const err = new Error("AUTH_REQUIRED");
        err.name = "AuthError";
        throw err;
      }

      if (!res.ok) {
        const msg = await res.text();
        throw new Error(`${res.status} — ${msg}`.trim());
      }

      const ct = res.headers.get("content-type") ?? "";
      return ct.includes("application/json") ? res.json() : res.text();

    } catch (err) {
      lastError = err;
      if (err.name === "AuthError") throw err;
      // Retrying a timeout would just compound the wait without fixing
      // anything — surface it immediately so the caller can react.
      if (err.name === "TimeoutError") throw err;
      if (attempt >= retries) throw err;
      await sleep(400 + attempt * 400);
    }
  }

  throw lastError ?? new Error("Erreur inconnue");
};

export const fetchBlob = async (path, options = {}) => {
  const { timeout = REQUEST_TIMEOUT_MS } = options;
  const headers = new Headers();
  if (store.authToken) headers.set("Authorization", `Bearer ${store.authToken}`);
  const res = await withTimeout(`${API_BASE}${path}`, { method: "GET", headers }, timeout);
  if (!res.ok) {
    const err = new Error(`Impossible de charger le fichier (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.blob();
};
