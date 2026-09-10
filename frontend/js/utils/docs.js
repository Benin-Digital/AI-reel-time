import { formatDate, statusBadge } from "./format.js";
import { escapeHtml } from "./dom.js";
import { fetchBlob } from "../api.js";

/**
 * Build a URLSearchParams query string from an object.
 * Skips entries where the value is null, undefined, or "".
 * Returns a string beginning with "?" if there are params, or "" if empty.
 */
export function buildParams(params) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v === null || v === undefined || v === "") continue;
    sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/**
 * Read the current page number from a DOM element's text content.
 * Returns at least 1.
 */
export function getPage(el) {
  return Math.max(1, parseInt(el?.textContent ?? "1", 10) || 1);
}

/**
 * Set a DOM element's text content to a page number (at least 1).
 */
export function setPage(el, n) {
  if (el) el.textContent = String(Math.max(1, n));
}

/**
 * Format a byte count as a human-readable string (e.g. "1.2 MB").
 */
export function formatBytes(bytes) {
  if (bytes == null || isNaN(bytes)) return "—";
  const n = Number(bytes);
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} Ko`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} Mo`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(1)} Go`;
}

/**
 * Split a string on newlines, commas, or semicolons; trim each part and
 * drop empty strings.
 */
export function splitItems(value) {
  if (!value) return [];
  return String(value)
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Return an HTML badge for a document status.
 */
export function documentStatusBadge(status) {
  const map = { ready: "Prêt", pending: "En attente", failed: "Échec" };
  const label = map[status] ?? status ?? "—";
  const cls = map[status] ? status : "default";
  return `<span class="badge badge--${cls}">${label}</span>`;
}

/**
 * Extract the basename of a file path.
 */
function _basename(path) {
  if (!path) return "";
  return path.replace(/\\/g, "/").split("/").pop() ?? path;
}

/**
 * Render an HTML string for a document list item.
 *
 * @param {object} doc        - Document object (cv or job)
 * @param {"cv"|"job"} kind   - Document kind
 * @param {string|null} selectedId - Currently selected document ID (string)
 * @returns {string} HTML string
 */
export function renderDocItem(doc, kind, selectedId) {
  const id = doc.id;
  const isSelected = selectedId != null && String(id) === String(selectedId);
  const icon = kind === "cv"
    ? `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="3" y="1.5" width="10" height="13" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`
    : `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1" y="5" width="14" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M5 5V3.5A1.5 1.5 0 0 1 6.5 2h3A1.5 1.5 0 0 1 11 3.5V5" stroke="currentColor" stroke-width="1.5"/></svg>`;
  const name = escapeHtml(_basename(doc.path ?? doc.filename ?? String(id)));
  const badge = documentStatusBadge(doc.status);
  const date = formatDate(doc.updated_at ?? doc.created_at);
  const errorHtml = doc.last_error
    ? `<div class="text-xs text-error">${escapeHtml(doc.last_error)}</div>`
    : "";

  return `
<article class="doc-item${isSelected ? " is-selected" : ""}" data-doc-id="${escapeHtml(String(id))}" data-kind="${kind}">
  <div class="doc-item__icon">${icon}</div>
  <div class="doc-item__body">
    <div class="doc-item__name truncate">${name}</div>
    <div class="doc-item__meta">
      <span>ID ${escapeHtml(String(id))}</span>
      ${badge}
      <span>${escapeHtml(date)}</span>
    </div>
    ${errorHtml}
  </div>
  <div class="doc-item__actions">
    <button class="btn btn--ghost btn--sm" data-action="matches" data-doc="${escapeHtml(String(id))}" data-kind="${kind}">Matches</button>
    <button class="btn btn--danger btn--sm" data-action="delete" data-doc="${escapeHtml(doc.path ?? doc.filename ?? String(id))}" data-kind="${kind}">Suppr.</button>
  </div>
</article>`.trim();
}

/**
 * Render an HTML string for a document detail panel.
 *
 * @param {object} doc        - Detailed document object
 * @param {"cv"|"job"} kind   - Document kind
 * @returns {string} HTML string
 */
export function renderDocDetail(doc, kind) {
  const errorHtml = doc.last_error
    ? `<div class="banner banner--error">${escapeHtml(doc.last_error)}</div>`
    : "";

  const pdfSvg = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" style="vertical-align:middle;margin-right:4px"><rect x="3" y="1.5" width="10" height="13" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;

  const structuredSvg = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" style="vertical-align:middle;margin-right:4px"><path d="M2 4h12M2 8h8M2 12h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;
  const deepStructureSvg = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" style="vertical-align:middle;margin-right:4px"><rect x="2" y="2" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.5"/><rect x="9" y="2" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.5"/><rect x="2" y="9" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.5"/><rect x="9" y="9" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.5"/></svg>`;

  const structuringStatus = doc.structuring_status ?? null;
  const structuringBadge = structuringStatus ? statusBadge(structuringStatus) : "";
  const structuringDisabled = structuringStatus === "pending" ? "disabled" : "";
  const structuringLabel = structuringStatus === "pending" ? "Structuration…" : "Structurer (approfondi)";
  const structuringErrorHtml = structuringStatus === "failed" && doc.structuring_error
    ? `<p class="text-xs text-error">${escapeHtml(doc.structuring_error)}</p>`
    : "";
  const structuringWaitHtml = structuringStatus === "pending"
    ? `<p class="text-xs text-muted" id="structuringWait-${escapeHtml(String(doc.id))}">Structuration en cours… Pour un document long, cela peut prendre plusieurs minutes — merci de patienter.</p>`
    : "";

  const previewId = `docPreview-${kind}-${escapeHtml(String(doc.id))}`;
  const docId = escapeHtml(String(doc.id));

  // Recruiter-curated priority keywords -- job offers only (see
  // JobDocument.priority_keywords). Real offers observed in production
  // each come with a hand-picked shortlist of the terms that matter most
  // for that specific offer, often acronyms the general skill taxonomy
  // doesn't recognize at all (LOD2, DORA, TRM) -- see matcher.py's
  // _apply_priority_keywords for how these feed into scoring.
  const priorityKeywordsHtml = kind === "job" ? `
  <div class="card card--flat" style="padding:var(--space-4)">
    <div class="card__title text-sm" style="margin-bottom:var(--space-2)">Mots-clés prioritaires</div>
    <p class="text-xs text-muted" style="margin-bottom:var(--space-3)">
      Un mot-clé par ligne. Ils comptent séparément des compétences détectées
      automatiquement, avec leur propre score ("X/Y mots-clés prioritaires
      trouvés") affiché sur chaque correspondance — un CV ne peut pas
      compenser un mot-clé prioritaire manquant avec du vocabulaire générique.
      Facultatif : sans mot-clé renseigné, le matching fonctionne comme avant.
    </p>
    <textarea id="priorityKeywords-${docId}" rows="5" class="input" style="resize:vertical"
      placeholder="Un mot-clé par ligne…">${escapeHtml(doc.priority_keywords ?? "")}</textarea>
    <div style="display:flex;gap:var(--space-2);align-items:center;margin-top:var(--space-3);flex-wrap:wrap">
      <button class="btn btn--primary btn--sm" data-action="save-priority-keywords" data-doc-id="${docId}">Enregistrer</button>
      <button class="btn btn--ghost btn--sm" data-action="import-priority-keywords" data-doc-id="${docId}">Importer un fichier</button>
      <input type="file" accept=".pdf,.docx,.txt" hidden id="priorityKeywordsFile-${docId}" data-doc-id="${docId}" />
      <span class="text-xs text-muted" id="priorityKeywordsMsg-${docId}"></span>
    </div>
  </div>` : "";

  return `
<div class="stack" style="gap:var(--space-4)">
  <div style="display:flex;justify-content:flex-end;align-items:center;gap:var(--space-2);margin-bottom:var(--space-1);flex-wrap:wrap">
    ${structuringBadge}
    <button class="btn btn--ghost btn--sm" data-action="preview-pdf" data-doc-id="${docId}" data-kind="${kind}">${pdfSvg}Aperçu PDF</button>
    <button class="btn btn--ghost btn--sm" data-action="preview-parsed-pdf" data-doc-id="${docId}" data-kind="${kind}">${structuredSvg}PDF structuré</button>
    <button class="btn btn--ghost btn--sm" data-action="deep-structure" data-doc-id="${docId}" data-kind="${kind}" ${structuringDisabled}>${deepStructureSvg}${structuringLabel}</button>
  </div>
  ${structuringErrorHtml}
  ${structuringWaitHtml}
  ${errorHtml}
  ${priorityKeywordsHtml}
  <div class="doc-preview" id="${previewId}">
    <div class="skeleton doc-preview__frame"></div>
  </div>
</div>`.trim();
}

// One in-flight object URL per document kind (cv/job) — each detail panel
// fully replaces its own preview when a different document is selected, so
// it's safe (and necessary, to avoid leaking blob URLs) to revoke the
// previous one for that kind right before creating the next.
const _lastPreviewUrl = { cv: null, job: null };

/**
 * Load the document preview into the container rendered by renderDocDetail:
 * the original file if it's already a PDF, otherwise the already-extracted
 * text rendered as PDF (there is no way to preview a DOCX/TXT file in an
 * iframe directly).
 *
 * @param {"cv"|"job"} kind
 * @param {string|number} id
 */
export async function loadDocPdfPreview(kind, id) {
  const container = document.getElementById(`docPreview-${kind}-${id}`);
  if (!container) return;

  const rawPath = kind === "cv" ? `/cv-documents/${id}/pdf` : `/job-documents/${id}/pdf`;
  const parsedPath = kind === "cv" ? `/cv-documents/${id}/parsed-pdf` : `/job-documents/${id}/parsed-pdf`;

  try {
    let blob;
    try {
      blob = await fetchBlob(rawPath);
    } catch (err) {
      if (err.status !== 415) throw err;
      blob = await fetchBlob(parsedPath, { timeout: 60000 });
    }

    if (_lastPreviewUrl[kind]) URL.revokeObjectURL(_lastPreviewUrl[kind]);
    const url = URL.createObjectURL(blob);
    _lastPreviewUrl[kind] = url;

    // Guard against a stale response landing after the user already
    // navigated to a different document.
    if (!document.getElementById(`docPreview-${kind}-${id}`)) return;
    container.innerHTML = `<iframe src="${url}" class="doc-preview__frame" title="Aperçu du document"></iframe>`;
  } catch (err) {
    if (!document.getElementById(`docPreview-${kind}-${id}`)) return;
    container.innerHTML = `<div class="empty-state"><div class="empty-state__hint text-error">${escapeHtml(err.message)}</div></div>`;
  }
}
