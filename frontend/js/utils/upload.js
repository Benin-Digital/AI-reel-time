import { $, show, hide, openModal, closeModal } from "./dom.js";

let _pendingResolve = null;

let _pendingGenericResolve = null;

export function initGenericConfirm() {
  const modal     = $("#genericConfirmModal");
  const okBtn     = $("#genericConfirmOk");
  const cancelBtn = $("#genericConfirmCancel");

  okBtn?.addEventListener("click", () => {
    closeModal(modal);
    if (_pendingGenericResolve) { _pendingGenericResolve(true); _pendingGenericResolve = null; }
  });

  cancelBtn?.addEventListener("click", () => {
    if (_pendingGenericResolve) { _pendingGenericResolve(false); _pendingGenericResolve = null; }
  });
}

export function openConfirm(title, message, confirmLabel = "Confirmer") {
  return new Promise((resolve) => {
    _pendingGenericResolve = resolve;
    const modal   = $("#genericConfirmModal");
    const titleEl = $("#genericConfirmTitle");
    const textEl  = $("#genericConfirmText");
    const okBtn   = $("#genericConfirmOk");

    if (titleEl) titleEl.textContent = title;
    if (textEl)  textEl.textContent  = message;
    if (okBtn)   okBtn.textContent   = confirmLabel;

    openModal(modal);
  });
}

export function initDeleteConfirm() {
  const modal      = $("#deleteConfirmModal");
  const input      = $("#deleteConfirmInput");
  const confirmBtn = $("#deleteConfirmConfirm");
  const cancelBtn  = $("#deleteConfirmCancel");

  input?.addEventListener("input", () => {
    if (confirmBtn) confirmBtn.disabled = input.value.trim() !== "SUPPRIMER";
  });

  confirmBtn?.addEventListener("click", () => {
    closeModal(modal);
    if (_pendingResolve) { _pendingResolve(true); _pendingResolve = null; }
  });

  cancelBtn?.addEventListener("click", () => {
    if (_pendingResolve) { _pendingResolve(false); _pendingResolve = null; }
  });
}

export function openDeleteConfirm(filenames) {
  return new Promise((resolve) => {
    _pendingResolve = resolve;
    const names  = Array.isArray(filenames) ? filenames : [filenames];
    const textEl = $("#deleteConfirmText");
    const listEl = $("#deleteConfirmList");
    const input  = $("#deleteConfirmInput");
    const btn    = $("#deleteConfirmConfirm");
    const modal  = $("#deleteConfirmModal");

    if (textEl) textEl.textContent = names.length === 1
      ? `Confirmer la suppression : ${names[0]}`
      : `Confirmer la suppression de ${names.length} fichiers.`;

    if (listEl) listEl.innerHTML = names.slice(0, 10).map((n) => `<div>${n}</div>`).join("");
    if (input)  { input.value = ""; }
    if (btn)    btn.disabled = true;

    openModal(modal);
  });
}

export function setupUploadZone(zoneId, inputId, onFiles) {
  const zone  = $("#" + zoneId);
  const input = $("#" + inputId);
  if (!zone || !input) return;

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("is-dragover"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("is-dragover"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("is-dragover");
    if (e.dataTransfer?.files?.length) onFiles(Array.from(e.dataTransfer.files));
  });
  input.addEventListener("change", () => {
    if (input.files?.length) onFiles(Array.from(input.files));
    input.value = "";
  });
}
