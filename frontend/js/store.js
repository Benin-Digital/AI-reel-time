/**
 * État global partagé entre tous les modules.
 * Pas de framework : un objet muté + listeners simples.
 */

const _listeners = [];

export const store = {
  authToken: localStorage.getItem("authToken") ?? "",
  authUser:  JSON.parse(localStorage.getItem("authUser") ?? "null"),
  activePanel: "dashboard",
  cachedCvDocuments: [],
  cachedJobDocuments: [],
  currentArchiveSession: null,
  adminUsersCache: [],
  autoRefreshDelayMs: 3000,
  autoRefreshInFlight: false,
};

export function setStore(patch) {
  Object.assign(store, patch);
  _listeners.forEach((fn) => fn(store));
}

export function onStoreChange(fn) {
  _listeners.push(fn);
  return () => {
    const idx = _listeners.indexOf(fn);
    if (idx !== -1) _listeners.splice(idx, 1);
  };
}

export function persistAuth(token, user) {
  store.authToken = token;
  store.authUser  = user;
  if (token && user) {
    localStorage.setItem("authToken", token);
    localStorage.setItem("authUser", JSON.stringify(user));
  } else {
    localStorage.removeItem("authToken");
    localStorage.removeItem("authUser");
  }
}

export function clearAuth() {
  persistAuth("", null);
}
