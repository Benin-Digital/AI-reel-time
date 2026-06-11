import { safeFetch } from "./api.js";
import { store, setStore, persistAuth, clearAuth } from "./store.js";
import { $, show, hide, setBanner, openModal, closeModal } from "./utils/dom.js";
import { initials } from "./utils/format.js";

export const ADMIN_ROLES = new Set(["admin", "superadmin"]);

export const canManageUsers = () => Boolean(store.authUser && ADMIN_ROLES.has(store.authUser.role));

export function updateAuthUi() {
  const { authUser } = store;

  const authGate   = $("#authGate");
  const appShell   = $("#appShell");
  const adminNav   = $("#adminNavSection");
  const avatarEl   = $("#sidebarAvatar");
  const nameEl     = $("#sidebarUserName");
  const roleEl     = $("#sidebarUserRole");

  if (authUser) {
    hide(authGate);
    show(appShell);
    const displayName = [authUser.first_name, authUser.last_name].filter(Boolean).join(" ") || authUser.email;
    if (avatarEl) avatarEl.textContent = initials(displayName);
    if (nameEl)   nameEl.textContent   = displayName;
    if (roleEl)   roleEl.textContent   = authUser.role;
    if (adminNav) { canManageUsers() ? show(adminNav) : hide(adminNav); }
  } else {
    show(authGate);
    hide(appShell);
  }
}

export async function login(email, password) {
  const data = await safeFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    json: true,
    skipAuth: true,
    allowAuthErrors: true,
  });
  persistAuth(data.access_token, data.user);
  setStore({ authToken: data.access_token, authUser: data.user });
  updateAuthUi();
}

export function logout() {
  clearAuth();
  setStore({ authToken: "", authUser: null });
  updateAuthUi();
}

export function initAuth() {
  const loginModal      = $("#loginModal");
  const loginForm       = $("#loginForm");
  const loginError      = $("#loginError");
  const openLoginBtn    = $("#openLoginModal");
  const logoutBtn       = $("#logoutBtn");
  const themeToggle     = $("#themeToggle");
  const themeIconDark   = $("#themeIconDark");
  const themeIconLight  = $("#themeIconLight");

  // Restore saved theme
  const savedTheme = localStorage.getItem("theme") ?? "dark";
  document.documentElement.dataset.theme = savedTheme;
  applyThemeIcons(savedTheme, themeIconDark, themeIconLight);

  themeToggle?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    applyThemeIcons(next, themeIconDark, themeIconLight);
  });

  openLoginBtn?.addEventListener("click", () => openModal(loginModal));

  logoutBtn?.addEventListener("click", () => {
    logout();
    openModal(loginModal);
  });

  // Close modals via backdrop or close button
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-modal-close]")) {
      const modal = e.target.closest(".modal");
      if (modal) closeModal(modal);
    }
  });

  loginForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    setBanner(loginError, "");
    const email    = $("#loginEmail")?.value ?? "";
    const password = $("#loginPassword")?.value ?? "";
    const btn = loginForm.querySelector('[type="submit"]');
    if (btn) { btn.disabled = true; btn.textContent = "Connexion…"; }
    try {
      await login(email, password);
      closeModal(loginModal);
      loginForm.reset();
    } catch (err) {
      setBanner(loginError, err.message, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Se connecter"; }
    }
  });

  updateAuthUi();
}

function applyThemeIcons(theme, darkIcon, lightIcon) {
  if (!darkIcon || !lightIcon) return;
  if (theme === "dark") { show(darkIcon); hide(lightIcon); }
  else                  { hide(darkIcon); show(lightIcon); }
}
