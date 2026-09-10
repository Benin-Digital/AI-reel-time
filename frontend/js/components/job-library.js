import { safeFetch, fetchBlob } from "../api.js";
import { $, setBanner, openModal, closeModal, escapeHtml } from "../utils/dom.js";
import { store, setStore } from "../store.js";
import { navigateTo } from "../router.js";
import { openDeleteConfirm } from "../utils/upload.js";
import { buildParams, setPage, renderDocItem, renderDocDetail, loadDocPdfPreview } from "../utils/docs.js";

const MAX_MB = 20;
const SUPPORTED = [".pdf", ".docx", ".txt"];

// module-local state
let _selectedId = null;
let _page = 1;
// Set right before opening the native file picker, from the pre-upload
// priority-keywords modal below -- carried into _handleUpload so /ingest
// can set it on the JobDocument before the first scoring pass runs.
let _pendingJobPriorityKeywords = null;

export function initJobLibrary() {
  // Upload via button -- goes through the optional priority-keywords modal
  // first (see below) instead of opening the file picker directly.
  const btn   = $("#uploadJobButton");
  const input = $("#uploadJobInput");
  btn?.addEventListener("click", () => _openPreUploadKeywordsModal());
  input?.addEventListener("change", () => {
    if (input.files?.length) _handleUpload(Array.from(input.files), _pendingJobPriorityKeywords);
    input.value = "";
    input.multiple = true;
    _pendingJobPriorityKeywords = null;
  });

  // Priority keywords only make sense tied to a single offer, so
  // "Continuer" with any typed forces a single-file selection; leaving the
  // field empty keeps the normal unrestricted multi-file import.
  $("#preUploadPriorityKeywordsContinue")?.addEventListener("click", () => {
    const textarea = $("#preUploadPriorityKeywordsInput");
    const value = (textarea?.value || "").trim();
    _pendingJobPriorityKeywords = value || null;
    if (input) input.multiple = !value;
    closeModal($("#preUploadPriorityKeywordsModal"));
    input?.click();
  });

  const preUploadFileInput = $("#preUploadPriorityKeywordsFile");
  $("#preUploadPriorityKeywordsImport")?.addEventListener("click", () => preUploadFileInput?.click());
  preUploadFileInput?.addEventListener("change", () => _extractPreUploadPriorityKeywords(preUploadFileInput));

  // Filters & pagination
  $("#applyJobFilters")?.addEventListener("click", () => { _page = 1; _load(); });
  $("#jobPrev")?.addEventListener("click", () => { if (_page > 1) { _page--; _load(); } });
  $("#jobNext")?.addEventListener("click", () => { _page++; _load(); });

  // Delegation on list
  $("#jobList")?.addEventListener("click", (e) => {
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
        if (filterCv)  filterCv.value  = "";
        if (filterJob) filterJob.value = doc;
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

  window.addEventListener("load-job-library", () => _load());
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

async function _load() {
  const list = $("#jobList");
  if (!list) return;
  try {
    const params = buildParams({
      page:      _page,
      page_size: $("#jobPageSize")?.value ?? 25,
      status:    $("#jobStatus")?.value,
      query:     $("#jobQuery")?.value,
    });
    const docs = await safeFetch(`/job-documents${params}`);
    setStore({ cachedJobDocuments: docs });

    // sidebar badge
    const badge = $("#jobCountBadge");
    if (badge) {
      if (docs.length > 0) {
        badge.textContent = String(docs.length);
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }
    }

    if (!docs.length) {
      list.innerHTML = `<div class="empty-state"><div class="empty-state__icon"><svg width="32" height="32" viewBox="0 0 32 32" fill="none"><rect x="2" y="10" width="28" height="18" rx="3" stroke="currentColor" stroke-width="1.5"/><path d="M10 10V7a3 3 0 0 1 3-3h6a3 3 0 0 1 3 3v3" stroke="currentColor" stroke-width="1.5"/></svg></div><div class="empty-state__title">Aucune offre importée</div></div>`;
      return;
    }

    if (!_selectedId || !docs.some((d) => String(d.id) === _selectedId)) {
      _selectedId = String(docs[0].id);
    }

    _refreshList(docs);

    const pageEl  = $("#jobPage");
    if (pageEl) setPage(pageEl, _page);
    const prevBtn = $("#jobPrev");
    if (prevBtn) prevBtn.disabled = _page <= 1;

    if (_selectedId) _loadDetail(_selectedId);

  } catch (err) {
    if (err.name !== "AuthError") {
      list.innerHTML = `<div class="empty-state"><div class="empty-state__hint text-error">${err.message}</div></div>`;
    }
  }
}

function _refreshList(docs = store.cachedJobDocuments) {
  const list = $("#jobList");
  if (!list) return;
  list.innerHTML = docs.map((d) => renderDocItem(d, "job", _selectedId)).join("");
}

async function _loadDetail(id) {
  const detail = $("#jobDetails");
  if (!detail) return;
  // #jobDetails starts as .workspace__detail-empty (centers the "Sélectionnez
  // une offre" placeholder both ways) — once we're loading a real document,
  // that centering must go, or real content gets vertically centered inside
  // the panel instead of anchored to the top (worse the taller the list is).
  detail.classList.remove("workspace__detail-empty");
  detail.innerHTML = `<div class="skeleton skeleton--card" style="margin:var(--space-5)"></div>`;
  try {
    const doc = await safeFetch(`/job-documents/${id}/details`);
    detail.innerHTML = `<div class="workspace__detail-body">${renderDocDetail(doc, "job")}</div>`;
    loadDocPdfPreview("job", id);

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
            blob = await fetchBlob(`/job-documents/${id}/pdf`);
          } catch (err) {
            // Original isn't a PDF (DOCX/TXT) — fall back to the already
            // extracted text rendered as PDF instead of a dead end.
            if (err.status !== 415) throw err;
            blob = await fetchBlob(`/job-documents/${id}/parsed-pdf`, { timeout: 60000 });
          }
          const url = URL.createObjectURL(blob);
          window.open(url, "_blank");
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (err) {
          setBanner($("#uploadJobStatus"), `PDF : ${err.message}`, "error");
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
          const blob = await fetchBlob(`/job-documents/${id}/parsed-pdf`, { timeout: 60000 });
          const url = URL.createObjectURL(blob);
          window.open(url, "_blank");
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (err) {
          setBanner($("#uploadJobStatus"), `PDF structuré : ${err.message}`, "error");
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
          await safeFetch(`/job-documents/${id}/structure`, { method: "POST" });
          if (_selectedId === id) await _loadDetail(id);
          _pollStructuring(id);
        } catch (err) {
          setBanner($("#uploadJobStatus"), `Structuration : ${err.message}`, "error");
          deepStructureBtn.disabled = false;
        }
      });
    }

    // wire priority-keywords save/import (see renderDocDetail, job side only)
    const savePriorityBtn = detail.querySelector("[data-action='save-priority-keywords']");
    if (savePriorityBtn) {
      savePriorityBtn.addEventListener("click", () => _savePriorityKeywords(id));
    }
    const importPriorityBtn = detail.querySelector("[data-action='import-priority-keywords']");
    const priorityFileInput = document.getElementById(`priorityKeywordsFile-${id}`);
    if (importPriorityBtn && priorityFileInput) {
      importPriorityBtn.addEventListener("click", () => priorityFileInput.click());
      priorityFileInput.addEventListener("change", () => _extractPriorityKeywords(id, priorityFileInput));
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
      const doc = await safeFetch(`/job-documents/${id}/details`);
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

async function _openPreUploadKeywordsModal() {
  const textarea = $("#preUploadPriorityKeywordsInput");
  const msg = $("#preUploadPriorityKeywordsMsg");
  if (textarea) textarea.value = "";
  _setPriorityKeywordsMsg(msg, "");
  openModal($("#preUploadPriorityKeywordsModal"));
}

async function _extractPreUploadPriorityKeywords(fileInput) {
  const file = fileInput.files?.[0];
  fileInput.value = "";
  if (!file) return;

  const textarea = $("#preUploadPriorityKeywordsInput");
  const msg = $("#preUploadPriorityKeywordsMsg");
  if (!textarea) return;

  const ext = `.${file.name.split(".").pop().toLowerCase()}`;
  if (!SUPPORTED.includes(ext)) {
    _setPriorityKeywordsMsg(msg, `Format non supporté (${SUPPORTED.join(", ")})`, "error");
    return;
  }
  if (file.size > MAX_MB * 1024 * 1024) {
    _setPriorityKeywordsMsg(msg, `Fichier trop volumineux (max ${MAX_MB} Mo)`, "error");
    return;
  }

  _setPriorityKeywordsMsg(msg, `Lecture de ${file.name}…`);
  try {
    const fd = new FormData();
    fd.append("upload", file, file.name);
    const result = await safeFetch("/priority-keywords/extract-preview", { method: "POST", body: fd });
    textarea.value = result.keywords;
    _setPriorityKeywordsMsg(msg, "Relisez la liste puis cliquez sur Continuer.");
  } catch (err) {
    _setPriorityKeywordsMsg(msg, err.message, "error");
  }
}

async function _handleUpload(files, priorityKeywords = null) {
  const statusEl = $("#uploadJobStatus");
  const pending = [];
  for (const file of files) {
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!SUPPORTED.includes(ext)) {
      setBanner(statusEl, `${file.name} : type non supporté`, "error");
      continue;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      setBanner(statusEl, `${file.name} : trop volumineux (max ${MAX_MB} Mo)`, "error");
      continue;
    }
    try {
      setBanner(statusEl, `Envoi de ${file.name}…`, "info");
      const fd = new FormData();
      fd.append("folder", "job");
      fd.append("upload", file, file.name);
      fd.append("filename", file.name);
      if (priorityKeywords) fd.append("priority_keywords", priorityKeywords);
      await safeFetch("/ingest", { method: "POST", body: fd });
      pending.push(file.name);
    } catch (err) {
      setBanner(statusEl, `${file.name} : ${err.message}`, "error");
    }
  }
  if (pending.length) {
    await _load();
    _pollBatchUntilReady(statusEl, pending);
  }
}

async function _pollBatchUntilReady(statusEl, filenames, maxWaitMs = 1800000) {
  // One shared polling loop for the whole batch, not one independent loop
  // per file: uploading N documents at once used to start N concurrent
  // loops, each doing 2 GET requests every 3s (one from _load(), one to
  // check status) — with N=16 that's over 600 requests/minute, enough to
  // trip AI_REALTIME_RATE_LIMIT_MAX_REQUESTS (300/60s) and make the job
  // list itself return 429 mid-upload. A single loop makes exactly one
  // status check per tick regardless of batch size.
  //
  // Poll every 3s for the first 5 minutes (typical case), then fall back to
  // a slower 15s check for up to 30 minutes total — a document that takes
  // longer isn't broken, so we keep genuinely watching instead of telling
  // the user "check back later" and abandoning it ourselves.
  const fastPhaseMs = 300000;
  const fastInterval = 3000;
  const slowInterval = 15000;
  const startedAt = Date.now();
  const deadline = startedAt + maxWaitMs;
  const basenames = filenames.map((f) => f.replace(/\\/g, "/").split("/").pop());
  const remaining = new Set(basenames);
  let readyCount = 0;
  let failedCount = 0;

  while (Date.now() < deadline && remaining.size) {
    const elapsedBefore = Date.now() - startedAt;
    await new Promise((r) => setTimeout(r, elapsedBefore < fastPhaseMs ? fastInterval : slowInterval));
    const docs = await safeFetch("/job-documents").catch(() => []);
    for (const basename of Array.from(remaining)) {
      const doc = docs.find((d) => (d.path || "").endsWith(basename));
      if (!doc) continue;
      if (doc.status === "ready") {
        readyCount++;
        remaining.delete(basename);
      } else if (doc.status === "failed") {
        failedCount++;
        remaining.delete(basename);
      }
    }
    await _load();
    if (!remaining.size) break;
    const elapsed = Math.round((Date.now() - startedAt) / 1000);
    const hint = elapsed > 30 ? ". Ça prend plus de temps que d'habitude, merci de patienter" : "";
    const progress = basenames.length > 1 ? `${readyCount + failedCount}/${basenames.length} traités, ` : "";
    setBanner(statusEl, `${progress}${remaining.size} en cours… (${elapsed}s)${hint}`, "info");
  }

  if (!remaining.size) {
    const summary = failedCount
      ? `${readyCount} prêt(s), ${failedCount} échec(s)`
      : basenames.length > 1 ? `${readyCount} offres prêtes` : "Prêt";
    setBanner(statusEl, summary, failedCount ? "error" : "success");
  } else {
    setBanner(
      statusEl,
      `${remaining.size} document(s) prennent anormalement longtemps. Rafraîchissez la page dans quelques minutes pour vérifier.`,
      "warning"
    );
  }
}

async function _handleDelete(filename) {
  const confirmed = await openDeleteConfirm([filename]);
  if (!confirmed) return;
  try {
    await safeFetch("/ingest/delete", {
      method: "POST",
      body: JSON.stringify({ folder: "job", filename }),
      json: true,
    });
    _selectedId = null;
    _load();
    // delay to let the async worker finish cleaning up match_results
    setTimeout(() => window.dispatchEvent(new CustomEvent("load-matches")), 2000);
  } catch (err) {
    setBanner($("#uploadJobStatus"), err.message, "error");
  }
}

// Inline status text next to the save/import buttons -- a plain <span>,
// not a .banner block (setBanner would overwrite its layout classes).
function _setPriorityKeywordsMsg(el, text, tone = "muted") {
  if (!el) return;
  el.className = `text-xs text-${tone}`;
  // "info" means a background rescore just got queued -- a spinner makes
  // that state read as "working" instead of looking identical to a plain
  // static confirmation (see the same treatment on .banner--info).
  el.innerHTML = tone === "info"
    ? `<span class="spinner-inline"></span>${escapeHtml(text)}`
    : escapeHtml(text);
}

async function _savePriorityKeywords(id) {
  const textarea = document.getElementById(`priorityKeywords-${id}`);
  const btn      = document.querySelector(`[data-action='save-priority-keywords'][data-doc-id="${id}"]`);
  const msg      = document.getElementById(`priorityKeywordsMsg-${id}`);
  if (!textarea) return;

  if (btn) { btn.disabled = true; btn.textContent = "Enregistrement…"; }
  _setPriorityKeywordsMsg(msg, "");
  try {
    await safeFetch(`/job-documents/${id}/priority-keywords`, {
      method: "PATCH",
      body: JSON.stringify({ keywords: textarea.value }),
      json: true,
    });
    _setPriorityKeywordsMsg(msg, "Enregistré, recalcul des scores en cours…", "info");
    // Refresh so the sidebar/list badges (feedback count, etc.) reflect the
    // rescoring this save just triggered, same as after "Relancer l'IA".
    window.dispatchEvent(new CustomEvent("load-matches"));
    // This queues the same kind of background rescoring as "Relancer l'IA"
    // (_on_watch_event(..., event_type="rescore")), just from this page --
    // give it the same live-updating banner + polling on Correspondances
    // instead of a one-off refresh that only shows whatever had already
    // finished by the time this PATCH returned.
    window.dispatchEvent(new CustomEvent("matches-rescoring", {
      detail: {
        message: "Mots-clés prioritaires enregistrés — les scores de cette offre se recalculent, "
          + "ça peut prendre quelques instants.",
      },
    }));
  } catch (err) {
    _setPriorityKeywordsMsg(msg, err.message, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Enregistrer"; }
  }
}

async function _extractPriorityKeywords(id, fileInput) {
  const file = fileInput.files?.[0];
  fileInput.value = ""; // allow re-selecting the same file later
  if (!file) return;

  const textarea = document.getElementById(`priorityKeywords-${id}`);
  const msg      = document.getElementById(`priorityKeywordsMsg-${id}`);
  if (!textarea) return;

  const ext = `.${file.name.split(".").pop().toLowerCase()}`;
  if (!SUPPORTED.includes(ext)) {
    _setPriorityKeywordsMsg(msg, `Format non supporté (${SUPPORTED.join(", ")})`, "error");
    return;
  }
  if (file.size > MAX_MB * 1024 * 1024) {
    _setPriorityKeywordsMsg(msg, `Fichier trop volumineux (max ${MAX_MB} Mo)`, "error");
    return;
  }

  _setPriorityKeywordsMsg(msg, `Lecture de ${file.name}…`);
  try {
    const fd = new FormData();
    fd.append("upload", file, file.name);
    const result = await safeFetch(`/job-documents/${id}/priority-keywords/extract`, {
      method: "POST",
      body: fd,
    });
    // Pre-fills the textarea only -- the recruiter reviews/edits, then
    // clicks "Enregistrer" themselves. Nothing is saved by this call.
    textarea.value = result.keywords;
    _setPriorityKeywordsMsg(msg, "Relisez la liste puis cliquez sur Enregistrer.");
  } catch (err) {
    _setPriorityKeywordsMsg(msg, err.message, "error");
  }
}
