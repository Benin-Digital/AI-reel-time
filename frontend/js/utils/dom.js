export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

export const escapeHtml = (s) =>
  s == null ? "" : String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

export const show = (el) => { if (el) el.hidden = false; };
export const hide = (el) => { if (el) el.hidden = true; };

export const setBanner = (el, message, variant = "info") => {
  if (!el) return;
  if (!message) { hide(el); el.textContent = ""; return; }
  el.className = `banner banner--${variant}`;
  el.textContent = message;
  show(el);
};

export const renderEmpty = (message) =>
  `<div class="empty-state"><div class="empty-state__hint">${escapeHtml(message)}</div></div>`;

export const openModal  = (el) => { if (el) el.hidden = false; };
export const closeModal = (el) => { if (el) el.hidden = true; };
