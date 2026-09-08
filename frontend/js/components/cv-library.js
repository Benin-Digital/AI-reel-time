import { safeFetch, fetchBlob } from "../api.js";
import { $, setBanner, openModal } from "../utils/dom.js";
import { store, setStore } from "../store.js";
import { navigateTo } from "../router.js";
import { openDeleteConfirm } from "../utils/upload.js";
import { buildParams, setPage, renderDocItem, renderDocDetail, loadDocPdfPreview } from "../utils/docs.js";

const MAX_MB = 20;
const SUPPORTED = [".pdf", ".docx", ".txt"];

// module-local state
let _selectedId = null;
let _page = 1;

export function initCvLibrary() {
  // Upload via button
  const btn   = $("#uploadCvButton");
  const input = $("#uploadCvInput");
  btn?.addEventListener("click", () => input?.click());
  input?.addEventListener("change", () => {
    if (input.files?.length) _handleUpload(Array.from(input.files));
    input.value = "";
  });

  // Filters & pagination
  $("#applyCvFilters")?.addEventListener("click", () => { _page = 1; _load(); });
  $("#cvPrev")?.addEventListener("click", () => { if (_page > 1) { _page--; _load(); } });
  $("#cvNext")?.addEventListener("click", () => { _page++; _load(); });

  // Delegation on list
  $("#cvList")?.addEventListener("click", (e) => {
    const item      = e.target.closest("[data-doc-id]");
    const actionBtn = e.target.closest("[data-action]");
    if (!item) return;

    if (actionBtn) {
      e.stopPropagation();
      const action = actionBtn.dataset.action;
      const doc    = actionBtn.dataset.doc;
      if (action === "delete") {
        _handleDelete(doc);
      } else if (action === "matches") {
        const filterCv  = $("#filterCv");
        const filterJob = $("#filterJob");
        if (filterCv)  filterCv.value  = doc;
        if (filterJob) filterJob.value = "";
        navigateTo("matches");
        window.dispatchEvent(new CustomEvent("load-matches"));
      }
      return;
    }

    const id = item.dataset.docId;
    _selectedId = id;
    _loadDetail(id);
    _refreshList();
  });

  window.addEventListener("load-cv-library", () => _load());
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

async function _load() {
  const list = $("#cvList");
  if (!list) return;
  try {
    const params = buildParams({
      page:      _page,
      page_size: $("#cvPageSize")?.value ?? 25,
      status:    $("#cvStatus")?.value,
      query:     $("#cvQuery")?.value,
    });
    const docs = await safeFetch(`/cv-documents${params}`);
    setStore({ cachedCvDocuments: docs });

    // sidebar badge
    const badge = $("#cvCountBadge");
    if (badge) {
      if (docs.length > 0) {
        badge.textContent = String(docs.length);
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }
    }

    if (!docs.length) {
      list.innerHTML = `<div class="empty-state"><div class="empty-state__icon"><svg width="32" height="32" viewBox="0 0 32 32" fill="none"><rect x="6" y="3" width="20" height="26" rx="3" stroke="currentColor" stroke-width="1.5"/><path d="M11 11h10M11 16h10M11 21h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></div><div class="empty-state__title">Aucun CV importé</div></div>`;
      return;
    }

    if (!_selectedId || !docs.some((d) => String(d.id) === _selectedId)) {
      _selectedId = String(docs[0].id);
    }

    _refreshList(docs);

    const pageEl  = $("#cvPage");
    if (pageEl) setPage(pageEl, _page);
    const prevBtn = $("#cvPrev");
    if (prevBtn) prevBtn.disabled = _page <= 1;

    if (_selectedId) _loadDetail(_selectedId);

  } catch (err) {
    if (err.name !== "AuthError") {
      list.innerHTML = `<div class="empty-state"><div class="empty-state__hint text-error">${err.message}</div></div>`;
    }
  }
}

function _refreshList(docs = store.cachedCvDocuments) {
  const list = $("#cvList");
  if (!list) return;
  list.innerHTML = docs.map((d) => renderDocItem(d, "cv", _selectedId)).join("");
}

async function _loadDetail(id) {
  const detail = $("#cvDetails");
  if (!detail) return;
  detail.innerHTML = `<div class="skeleton skeleton--card" style="margin:var(--space-5)"></div>`;
  try {
    const doc = await safeFetch(`/cv-documents/${id}/details`);
    detail.innerHTML = `<div class="workspace__detail-body">${renderDocDetail(doc, "cv")}</div>`;
    loadDocPdfPreview("cv", id);

    // wire explain buttons injected by renderDocDetail
    detail.querySelectorAll("[data-explain]").forEach((btn) => {
      btn.addEventListener("click", () => {
        window.dispatchEvent(new CustomEvent("load-explain", { detail: { matchId: btn.dataset.explain } }));
      });
    });

    // wire PDF preview button
    const pdfBtn = detail.querySelector("[data-action='preview-pdf']");
    if (pdfBtn) {
      pdfBtn.addEventListener("click", async () => {
        pdfBtn.disabled = true;
        try {
          let blob;
          try {
            blob = await fetchBlob(`/cv-documents/${id}/pdf`);
          } catch (err) {
            // Original isn't a PDF (DOCX/TXT) — fall back to the already
            // extracted text rendered as PDF instead of a dead end.
            if (err.status !== 415) throw err;
            blob = await fetchBlob(`/cv-documents/${id}/parsed-pdf`, { timeout: 60000 });
          }
          const url = URL.createObjectURL(blob);
          window.open(url, "_blank");
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (err) {
          setBanner($("#uploadCvStatus"), `PDF : ${err.message}`, "error");
        } finally {
          pdfBtn.disabled = false;
        }
      });
    }

    // wire structured PDF button
    const parsedPdfBtn = detail.querySelector("[data-action='preview-parsed-pdf']");
    if (parsedPdfBtn) {
      parsedPdfBtn.addEventListener("click", async () => {
        parsedPdfBtn.disabled = true;
        parsedPdfBtn.textContent = "Génération…";
        try {
          const blob = await fetchBlob(`/cv-documents/${id}/parsed-pdf`, { timeout: 60000 });
          const url = URL.createObjectURL(blob);
          window.open(url, "_blank");
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (err) {
          setBanner($("#uploadCvStatus"), `PDF structuré : ${err.message}`, "error");
        } finally {
          parsedPdfBtn.disabled = false;
          parsedPdfBtn.textContent = "PDF structuré";
        }
      });
    }

    // wire on-demand deep structuring (Docling) button
    const deepStructureBtn = detail.querySelector("[data-action='deep-structure']");
    if (deepStructureBtn) {
      deepStructureBtn.addEventListener("click", async () => {
        deepStructureBtn.disabled = true;
        try {
          await safeFetch(`/cv-documents/${id}/structure`, { method: "POST" });
          if (_selectedId === id) await _loadDetail(id);
          _pollStructuring(id);
        } catch (err) {
          setBanner($("#uploadCvStatus"), `Structuration : ${err.message}`, "error");
          deepStructureBtn.disabled = false;
        }
      });
    }
  } catch (err) {
    if (err.name !== "AuthError") {
      detail.innerHTML = `<div class="empty-state"><div class="empty-state__hint text-error">${err.message}</div></div>`;
    }
  }
}

async function _pollStructuring(id, maxWaitMs = 1800000) {
  // Docling structuring is genuinely slow for a long document — update the
  // wait message with elapsed time instead of leaving a static "en cours"
  // that looks stuck, and keep watching (slower, every 15s) well past the
  // point a short document would already be done.
  const fastPhaseMs = 60000;
  const fastInterval = 3000;
  const slowInterval = 15000;
  const startedAt = Date.now();
  const deadline = startedAt + maxWaitMs;

  while (Date.now() < deadline) {
    const elapsedBefore = Date.now() - startedAt;
    await new Promise((r) => setTimeout(r, elapsedBefore < fastPhaseMs ? fastInterval : slowInterval));
    try {
      const doc = await safeFetch(`/cv-documents/${id}/details`);
      if (doc.structuring_status !== "pending") {
        if (_selectedId === id) await _loadDetail(id);
        return;
      }
      const waitEl = document.getElementById(`structuringWait-${id}`);
      if (waitEl) {
        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        const hint = elapsed > 60
          ? " Ce document est long à analyser en profondeur, ça peut prendre plusieurs minutes."
          : "";
        waitEl.textContent = `Structuration en cours… (${elapsed}s)${hint}`;
      }
    } catch {
      return;
    }
  }
  const waitEl = document.getElementById(`structuringWait-${id}`);
  if (waitEl) {
    waitEl.textContent = "Ça prend anormalement longtemps. Rafraîchissez la page dans quelques minutes pour vérifier.";
  }
}

async function _handleUpload(files) {
  const statusEl = $("#uploadCvStatus");
  for (const file of files) {
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!SUPPORTED.includes(ext)) {
      setBanner(statusEl, `${file.name} — type non supporté`, "error");
      continue;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      setBanner(statusEl, `${file.name} — trop volumineux (max ${MAX_MB} Mo)`, "error");
      continue;
    }
    try {
      setBanner(statusEl, `Envoi de ${file.name}…`, "info");
      const fd = new FormData();
      fd.append("folder", "cv");
      fd.append("upload", file, file.name);
      fd.append("filename", file.name);
      await safeFetch("/ingest", { method: "POST", body: fd });
      setBanner(statusEl, `${file.name} — analyse en cours…`, "info");
      await _load();
      _pollUntilReady(statusEl, file.name);
    } catch (err) {
      setBanner(statusEl, `${file.name} — ${err.message}`, "error");
    }
  }
}

async function _pollUntilReady(statusEl, filename, maxWaitMs = 1800000) {
  // Poll every 3s for the first 5 minutes (typical case), then fall back to
  // a slower 15s check for up to 30 minutes total — a document that takes
  // longer isn't broken, so we keep genuinely watching instead of telling
  // the user "check back later" and abandoning it ourselves.
  const fastPhaseMs = 300000;
  const fastInterval = 3000;
  const slowInterval = 15000;
  const startedAt = Date.now();
  const deadline = startedAt + maxWaitMs;

  while (Date.now() < deadline) {
    const elapsedBefore = Date.now() - startedAt;
    await new Promise((r) => setTimeout(r, elapsedBefore < fastPhaseMs ? fastInterval : slowInterval));
    await _load();
    const docs = (await safeFetch("/cv-documents").catch(() => []));
    const basename = filename.replace(/\\/g, "/").split("/").pop();
    const doc = docs.find((d) => (d.path || "").endsWith(basename));
    if (!doc) continue;
    if (doc.status === "ready") {
      setBanner(statusEl, `${filename} prêt`, "success");
      return;
    }
    if (doc.status === "failed") {
      setBanner(statusEl, `${filename} — échec de l'analyse`, "error");
      return;
    }
    const elapsed = Math.round((Date.now() - startedAt) / 1000);
    const hint = elapsed > 30 ? " — ça prend plus de temps que d'habitude, merci de patienter" : "";
    setBanner(statusEl, `${filename} — analyse en cours… (${elapsed}s)${hint}`, "info");
  }
  setBanner(
    statusEl,
    `${filename} — le traitement prend anormalement longtemps. Rafraîchissez la page dans quelques minutes pour vérifier.`,
    "warning"
  );
}

async function _handleDelete(filename) {
  const confirmed = await openDeleteConfirm([filename]);
  if (!confirmed) return;
  try {
    await safeFetch("/ingest/delete", {
      method: "POST",
      body: JSON.stringify({ folder: "cv", filename }),
      json: true,
    });
    _selectedId = null;
    _load();
    // delay to let the async worker finish cleaning up match_results
    setTimeout(() => window.dispatchEvent(new CustomEvent("load-matches")), 2000);
  } catch (err) {
    setBanner($("#uploadCvStatus"), err.message, "error");
  }
}
