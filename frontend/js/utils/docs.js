import { renderKeywordChips, renderScoreChip, formatDate, statusBadge } from "./format.js";
import { escapeHtml } from "./dom.js";

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
  const matchCount = doc.match_count ?? 0;
  const avgScore = doc.average_score != null
    ? `${Math.round(Number(doc.average_score))}%`
    : "n/a";
  const date = formatDate(doc.updated_at ?? doc.created_at);
  const method = escapeHtml(doc.extraction_method ?? doc.method ?? "—");

  const errorHtml = doc.last_error
    ? `<div class="banner banner--error">${escapeHtml(doc.last_error)}</div>`
    : "";

  const keywords = (doc.top_keywords ?? []).filter(Boolean);
  const keywordsHtml = keywords.length
    ? `<div>
        <div class="text-xs font-semibold text-muted" style="margin-bottom:var(--space-2)">Mots-clés</div>
        ${renderKeywordChips(keywords)}
      </div>`
    : "";

  const extractedText = escapeHtml(doc.extracted_text ?? "");
  const textHtml = extractedText
    ? `<div>
        <div class="text-xs font-semibold text-muted" style="margin-bottom:var(--space-2)">Texte extrait</div>
        <div style="font-size:var(--text-xs);color:var(--text-secondary);white-space:pre-wrap;max-height:200px;overflow-y:auto;background:var(--bg-surface-raised);border-radius:var(--radius-md);padding:var(--space-3)">${extractedText}</div>
      </div>`
    : "";

  const topMatches = (doc.top_matches ?? []).filter(Boolean);
  const topMatchesHtml = topMatches.length
    ? `<div>
        <div class="text-xs font-semibold text-muted" style="margin-bottom:var(--space-2)">Meilleurs matches</div>
        <div class="stack" style="gap:var(--space-2)">
          ${topMatches.slice(0, 5).map((m) => {
            const score = Math.max(0, Math.min(100, Math.round(Number(m.score) || 0)));
            const otherId = kind === "cv" ? m.job_id : m.cv_id;
            const otherLabel = kind === "cv" ? "Offre" : "CV";
            return `<div style="display:flex;align-items:center;gap:var(--space-3);background:var(--bg-surface-raised);border-radius:var(--radius-md);padding:var(--space-2) var(--space-3)">
              ${renderScoreChip(score)}
              <span class="text-sm text-secondary">${otherLabel} ${escapeHtml(String(otherId))}</span>
              <button class="btn btn--ghost btn--sm" style="margin-left:auto" data-explain="${escapeHtml(String(m.id))}">Analyser</button>
            </div>`;
          }).join("")}
        </div>
      </div>`
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

  return `
<div class="stack" style="gap:var(--space-5)">
  <div style="display:flex;justify-content:flex-end;align-items:center;gap:var(--space-2);margin-bottom:var(--space-1);flex-wrap:wrap">
    ${structuringBadge}
    <button class="btn btn--ghost btn--sm" data-action="preview-pdf" data-doc-id="${escapeHtml(String(doc.id))}" data-kind="${kind}">${pdfSvg}Aperçu PDF</button>
    <button class="btn btn--ghost btn--sm" data-action="preview-parsed-pdf" data-doc-id="${escapeHtml(String(doc.id))}" data-kind="${kind}">${structuredSvg}PDF structuré</button>
    <button class="btn btn--ghost btn--sm" data-action="deep-structure" data-doc-id="${escapeHtml(String(doc.id))}" data-kind="${kind}" ${structuringDisabled}>${deepStructureSvg}${structuringLabel}</button>
  </div>
  ${structuringErrorHtml}
  <div style="display:flex;gap:var(--space-4);flex-wrap:wrap">
    <div class="metric-card" style="flex:1;min-width:100px">
      <div class="metric-card__label">ID</div>
      <div class="metric-card__value">${escapeHtml(String(doc.id))}</div>
    </div>
    <div class="metric-card" style="flex:1;min-width:100px">
      <div class="metric-card__label">Matches</div>
      <div class="metric-card__value">${escapeHtml(String(matchCount))}</div>
    </div>
    <div class="metric-card" style="flex:1;min-width:100px">
      <div class="metric-card__label">Score moyen</div>
      <div class="metric-card__value">${avgScore}</div>
    </div>
  </div>
  <div class="stack" style="gap:var(--space-2)">
    <p class="text-xs text-muted">Mis à jour le ${escapeHtml(date)}</p>
    <p class="text-xs text-muted">Extraction : ${method}</p>
    ${errorHtml}
  </div>
  ${keywordsHtml}
  ${textHtml}
  ${topMatchesHtml}
</div>`.trim();
}
