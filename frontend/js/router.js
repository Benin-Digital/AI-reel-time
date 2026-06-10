import { $, $$ } from "./utils/dom.js";
import { setStore, store } from "./store.js";

const PANEL_TITLES = {
  "dashboard":   "Tableau de bord",
  "publish-cv":  "Publier un CV",
  "cv-library":  "Bibliothèque CV",
  "publish-job": "Publier une offre",
  "job-library": "Bibliothèque offres",
  "matches":     "Correspondances",
  "archives":    "Archives",
  "admin":       "Administration",
};

const _onPanelChange = [];

export function onPanelChange(fn) {
  _onPanelChange.push(fn);
}

export function navigateTo(panelId) {
  const panels  = $$(".view[data-panel]");
  const navItems = $$(".nav-item[data-panel]");

  panels.forEach((p) => {
    p.hidden = p.dataset.panel !== panelId;
  });
  navItems.forEach((btn) => {
    const isActive = btn.dataset.panel === panelId;
    btn.classList.toggle("is-active", isActive);
    btn.setAttribute("aria-current", isActive ? "page" : "false");
  });

  const titleEl = $("#topbarTitle");
  if (titleEl) titleEl.textContent = PANEL_TITLES[panelId] ?? panelId;

  setStore({ activePanel: panelId });
  _onPanelChange.forEach((fn) => fn(panelId));
}

export function initRouter() {
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".nav-item[data-panel]");
    if (!btn) return;
    navigateTo(btn.dataset.panel);
  });

  navigateTo(store.activePanel);
}
