import { safeFetch } from "../api.js";
import { $, openModal, closeModal, setBanner, escapeHtml } from "../utils/dom.js";
import {
  renderScoreChip,
  renderScoreBar,
  renderKeywordChips,
  formatDate,
  clampScore,
  scoreTone,
} from "../utils/format.js";
import { buildParams, setPage } from "../utils/docs.js";

let _page = 1;

export function initMatches() {
  $("#applyFilters")?.addEventListener("click", () => { _page = 1; _load(); });

  $("#clearFilters")?.addEventListener("click", () => {
    ["filterCv", "filterJob", "minScore", "maxScore", "matchSearch"].forEach((id) => {
      const el = $(`#${id}`);
      if (el) el.value = "";
    });
    const sort = $("#sortMatches");
    if (sort) sort.value = "score_desc";
    _page = 1;
    _load();
  });

  $("#matchesPrev")?.addEventListener("click", () => { if (_page > 1) { _page--; _load(); } });
  $("#matchesNext")?.addEventListener("click", () => { _page++; _load(); });

  // Explain modal triggered from other components or from the list itself
  window.addEventListener("load-explain", (e) => _loadExplain(e.detail.matchId));

  $("#matchList")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-explain]");
    if (btn) _loadExplain(btn.dataset.explain);
  });

  // Close modal when a [data-modal-close] element is clicked
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-modal-close]")) {
      const modal = e.target.closest(".modal");
      if (modal) closeModal(modal);
    }
  });

  window.addEventListener("load-matches", () => _load());
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

async function _load() {
  const list = $("#matchList");
  if (!list) return;
  list.innerHTML = `
    <div class="skeleton skeleton--card"></div>
    <div class="skeleton skeleton--card"></div>`;
  try {
    const includeArchived = $("#includeArchived")?.checked ?? false;
    const params = buildParams({
      page:             _page,
      page_size:        $("#matchPageSize")?.value ?? 25,
      cv_id:            $("#filterCv")?.value,
      job_id:           $("#filterJob")?.value,
      min_score:        $("#minScore")?.value,
      max_score:        $("#maxScore")?.value,
      sort_by:          $("#sortMatches")?.value,
      search:           $("#matchSearch")?.value,
      unassigned_only:  includeArchived ? null : "true",
    });
    const data = await safeFetch(`/matches${params}`);

    const pageEl  = $("#matchesPage");
    if (pageEl) setPage(pageEl, _page);
    const prevBtn = $("#matchesPrev");
    if (prevBtn) prevBtn.disabled = _page <= 1;

    if (!data.length) {
      list.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon"><svg width="32" height="32" viewBox="0 0 32 32" fill="none"><path d="M10 16h12M16 10l6 6-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="16" cy="16" r="13.5" stroke="currentColor" stroke-width="1.5"/></svg></div>
          <div class="empty-state__title">Aucune correspondance</div>
          <div class="empty-state__hint">Importez des CV et des offres, puis attendez le traitement.</div>
        </div>`;
      return;
    }
    list.innerHTML = data.map(_renderMatchCard).join("");
  } catch (err) {
    if (err.name !== "AuthError") {
      list.innerHTML = `<div class="empty-state"><div class="empty-state__hint text-error">${err.message}</div></div>`;
    }
  }
}

function _renderMatchCard(match) {
  const score    = clampScore(match.score);
  const tone     = scoreTone(score);
  const keywords = (match.common_keywords ?? []).filter(Boolean).slice(0, 6);

  return `
<article class="match-card">
  <div class="match-card__score">
    ${renderScoreChip(score)}
    <span class="text-xs text-muted">${tone.label}</span>
  </div>
  <div class="match-card__body">
    <div class="match-card__title">
      Match #${escapeHtml(String(match.id))}
      <span class="badge badge--default">CV ${escapeHtml(String(match.cv_id))}</span>
      <span class="badge badge--default">Offre ${escapeHtml(String(match.job_id))}</span>
    </div>
    ${renderScoreBar(score)}
    <div class="match-card__meta">${renderKeywordChips(keywords)}</div>
  </div>
  <div class="match-card__actions">
    <button class="btn btn--ghost btn--sm" data-explain="${escapeHtml(String(match.id))}">Analyser</button>
  </div>
</article>`.trim();
}

async function _loadExplain(matchId) {
  const modal   = $("#explainModal");
  const content = $("#explainContent");
  if (!modal || !content) return;

  content.innerHTML = `
    <div style="display:flex;align-items:center;gap:var(--space-4);padding:var(--space-4)">
      <div class="skeleton skeleton--avatar"></div>
      <div class="stack" style="flex:1;gap:var(--space-2)">
        <div class="skeleton skeleton--text" style="width:80%"></div>
        <div class="skeleton skeleton--text" style="width:60%"></div>
      </div>
    </div>`;
  openModal(modal);

  try {
    const data = await safeFetch(`/matches/${matchId}/explain`);
    content.innerHTML = _renderExplainContent(data);

    // Wire copy button
    const copyBtn = content.querySelector("[data-explain-copy]");
    copyBtn?.addEventListener("click", () => {
      const text = _buildExplainText(data);
      navigator.clipboard?.writeText(text).catch(() => {});
    });

    // Wire print button
    const printBtn = content.querySelector("[data-explain-print]");
    printBtn?.addEventListener("click", () => {
      window.print();
    });
  } catch (err) {
    content.innerHTML = `<div class="banner banner--error">${escapeHtml(err.message)}</div>`;
  }
}

function _renderExplainContent(data) {
  const score     = clampScore(data.score);
  const tone      = scoreTone(score);
  const keywords  = (data.common_keywords ?? data.top_keywords ?? []).filter(Boolean).slice(0, 12);
  const why       = (data.why_match  ?? []).filter(Boolean);
  const vigilance = (data.vigilance  ?? []).filter(Boolean);
  const evidence  = (data.evidence   ?? []).filter(Boolean);

  const list = (items) => items.length
    ? `<ul class="stack" style="gap:var(--space-2);padding-left:var(--space-4)">
        ${items.map((i) => `<li class="text-sm text-secondary">${escapeHtml(i)}</li>`).join("")}
       </ul>`
    : `<p class="text-sm text-muted">Aucune donnée disponible.</p>`;

  return `
<div class="stack" style="gap:var(--space-5)">
  <div style="display:flex;align-items:center;gap:var(--space-4)">
    ${renderScoreChip(score)}
    <div>
      <div class="text-lg font-semibold">${tone.label}</div>
      <div class="text-sm text-muted">Score de compatibilité : ${score}%</div>
    </div>
  </div>
  ${renderScoreBar(score)}
  ${data.summary ? `<p class="text-sm text-secondary">${escapeHtml(data.summary)}</p>` : ""}
  <div>
    <div class="divider-label" style="margin-bottom:var(--space-3)">Mots-clés communs</div>
    ${renderKeywordChips(keywords)}
  </div>
  ${why.length
    ? `<div>
        <div class="divider-label" style="margin-bottom:var(--space-3)">Pourquoi ce match</div>
        ${list(why)}
       </div>`
    : ""}
  ${vigilance.length
    ? `<div>
        <div class="divider-label" style="margin-bottom:var(--space-3)">Points de vigilance</div>
        ${list(vigilance)}
       </div>`
    : ""}
  ${evidence.length
    ? `<div>
        <div class="divider-label" style="margin-bottom:var(--space-3)">Extraits représentatifs</div>
        ${list(evidence)}
       </div>`
    : ""}
  <div style="display:flex;gap:var(--space-2);flex-wrap:wrap">
    <button class="btn btn--ghost btn--sm" data-explain-copy="${escapeHtml(String(data.match_id ?? ""))}">Copier le texte</button>
    <button class="btn btn--ghost btn--sm" data-explain-print="${escapeHtml(String(data.match_id ?? ""))}">Imprimer le rapport</button>
  </div>
</div>`.trim();
}

/**
 * Build a plain-text version of the explain data for clipboard copy.
 */
function _buildExplainText(data) {
  const score    = clampScore(data.score);
  const tone     = scoreTone(score);
  const lines    = [`Score : ${score}% — ${tone.label}`];
  if (data.summary) lines.push("", data.summary);

  const keywords = (data.common_keywords ?? data.top_keywords ?? []).filter(Boolean).slice(0, 12);
  if (keywords.length) lines.push("", "Mots-clés : " + keywords.join(", "));

  const why = (data.why_match ?? []).filter(Boolean);
  if (why.length) { lines.push("", "Pourquoi ce match :"); why.forEach((s) => lines.push("  - " + s)); }

  const vigilance = (data.vigilance ?? []).filter(Boolean);
  if (vigilance.length) { lines.push("", "Points de vigilance :"); vigilance.forEach((s) => lines.push("  - " + s)); }

  const evidence = (data.evidence ?? []).filter(Boolean);
  if (evidence.length) { lines.push("", "Extraits représentatifs :"); evidence.forEach((s) => lines.push("  - " + s)); }

  return lines.join("\n");
}
