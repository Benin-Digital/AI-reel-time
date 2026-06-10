import { API_BASE } from "./config.js";
import { store, clearAuth } from "./store.js";
import { openModal } from "./utils/dom.js";

const REQUEST_TIMEOUT_MS = 12000;
const MAX_RETRIES = 2;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const withTimeout = async (url, options, ms) => {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...options, signal: ctrl.signal });
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
  } = options;

  const reqHeaders = new Headers(headers);
  if (json) reqHeaders.set("Content-Type", "application/json");
  if (!skipAuth && store.authToken) reqHeaders.set("Authorization", `Bearer ${store.authToken}`);

  const url = `${API_BASE}${path}`;
  let lastError;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await withTimeout(url, { method, headers: reqHeaders, body }, REQUEST_TIMEOUT_MS);

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
      if (attempt >= retries) throw err;
      await sleep(400 + attempt * 400);
    }
  }

  throw lastError ?? new Error("Erreur inconnue");
};

export const fetchBlob = async (path) => {
  const headers = new Headers();
  if (store.authToken) headers.set("Authorization", `Bearer ${store.authToken}`);
  const res = await withTimeout(`${API_BASE}${path}`, { method: "GET", headers }, REQUEST_TIMEOUT_MS);
  if (!res.ok) throw new Error(`Impossible de charger le fichier (${res.status})`);
  return res.blob();
};
