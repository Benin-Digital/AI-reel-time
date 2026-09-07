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
// Local cache: matchId → decision ("accept" | "reject" | "review")
const _feedbackCache = new Map();

export function initMatches() {
  $("#applyFilters")?.addEventListener("click", () => { _page = 1; _load(); });

  $("#clearFilters")?.addEventListener("click", () => {
    ["filterCv", "filterJob", "minScore", "maxScore", "matchSearch"].forEach((id) => {
      const el = $(`#${id}`);
      if (el) el.value = "";
    });
    const sort = $("#sortMatches");
    if (sort) sort.value = "score_desc";
    const includeArchived = $("#includeArchived");
    if (includeArchived) includeArchived.checked = false;
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

    // Quick feedback from match card (decision only, no rating/comment)
    const fb = e.target.closest("[data-feedback]");
    if (fb) _submitQuickFeedback(fb);
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
  const domain   = match.match_domain ? `<span class="badge badge--primary">${escapeHtml(match.match_domain)}</span>` : "";
  const current  = _feedbackCache.get(String(match.id)) ?? null;

  return `
<article class="match-card" data-match-id="${escapeHtml(String(match.id))}">
  <div class="match-card__score">
    ${renderScoreChip(score)}
    <span class="text-xs text-muted">${tone.label}</span>
  </div>
  <div class="match-card__body">
    <div class="match-card__title">
      Match #${escapeHtml(String(match.id))}
      <span class="badge badge--default" title="CV #${escapeHtml(String(match.cv_id))}">${escapeHtml(match.cv_label || `CV ${match.cv_id}`)}</span>
      <span class="badge badge--default" title="Offre #${escapeHtml(String(match.job_id))}">${escapeHtml(match.job_label || `Offre ${match.job_id}`)}</span>
      ${domain}
    </div>
    ${renderScoreBar(score)}
    ${_renderComponentScores(match)}
    <div class="match-card__meta">${renderKeywordChips(keywords)}</div>
    ${_renderFeedbackBar(match.id, current)}
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
    // Load explain data and existing feedback in parallel.
    // /explain rebuilds both StructuredDocuments and runs scoring — cold
    // cache + Docling + NER can push this past 30s. Allow 90s here.
    const [data, existingFb] = await Promise.all([
      safeFetch(`/matches/${matchId}/explain`, { timeout: 90000, retries: 0 }),
      safeFetch(`/matches/${matchId}/feedback`).catch(() => null),
    ]);

    if (existingFb) _feedbackCache.set(String(matchId), existingFb);

    content.innerHTML = _renderExplainContent(data);
    _wireFeedbackForm(matchId);

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
  ${_renderComponentScoresDetailed(data)}
  ${_renderFeedbackForm(data.match_id)}
  <div style="display:flex;gap:var(--space-2);flex-wrap:wrap">
    <button class="btn btn--ghost btn--sm" data-explain-copy="${escapeHtml(String(data.match_id ?? ""))}">Copier le texte</button>
    <button class="btn btn--ghost btn--sm" data-explain-print="${escapeHtml(String(data.match_id ?? ""))}">Imprimer le rapport</button>
  </div>
</div>`.trim();
}

const _SCORE_COMPONENTS = [
  { key: "score_skills",     label: "Compétences" },
  { key: "score_semantic",   label: "Sémantique" },
  { key: "score_experience", label: "Expérience" },
  { key: "score_education",  label: "Formation" },
  { key: "score_languages",  label: "Langues" },
  { key: "score_contract",   label: "Contrat" },
];

function _renderComponentScores(match) {
  const available = _SCORE_COMPONENTS.filter((c) => match[c.key] != null);
  if (!available.length) return "";

  const items = available.map(({ key, label }) => {
    const pct  = Math.round((match[key] ?? 0) * 100);
    const tone = scoreTone(pct).key;
    return `<div class="score-breakdown__item">
      <span class="score-breakdown__label">${label}</span>
      <div class="score-breakdown__bar"><div class="score-breakdown__bar-fill score-bar__fill--${tone}" style="width:${pct}%"></div></div>
      <span class="score-breakdown__value">${pct}%</span>
    </div>`;
  }).join("");

  return `<div class="score-breakdown">${items}</div>`;
}

function _renderComponentScoresDetailed(data) {
  const available = _SCORE_COMPONENTS.filter((c) => data[c.key] != null);
  if (!available.length) return "";

  const domain = data.match_domain
    ? `<span class="badge badge--primary" style="margin-left:var(--space-2)">${escapeHtml(data.match_domain)}</span>`
    : "";

  const rows = available.map(({ key, label }) => {
    const pct  = Math.round((data[key] ?? 0) * 100);
    const tone = scoreTone(pct).key;
    return `<div class="score-breakdown__item">
      <span class="score-breakdown__label">${label}</span>
      <div class="score-breakdown__bar"><div class="score-breakdown__bar-fill score-bar__fill--${tone}" style="width:${pct}%"></div></div>
      <span class="score-breakdown__value">${pct}%</span>
    </div>`;
  }).join("");

  return `<div>
    <div class="divider-label" style="margin-bottom:var(--space-3)">Détail des scores${domain}</div>
    <div class="score-breakdown">${rows}</div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Feedback helpers
// ---------------------------------------------------------------------------

const _FB_LABELS = {
  accept: { label: "Accepté",  icon: "✓", cls: "accept" },
  review: { label: "À revoir", icon: "↩", cls: "review" },
  reject: { label: "Rejeté",   icon: "✗", cls: "reject" },
};

function _renderFeedbackBar(matchId, current) {
  const mid = escapeHtml(String(matchId));
  // `current` may be a bare decision string (quick-feedback path) or a full
  // feedback object {decision, rating, comment} (form-submit or server-fetched
  // path) — normalize both so the comment is never silently dropped.
  const decision = typeof current === "string" ? current : (current?.decision ?? null);
  const comment  = (current && typeof current === "object") ? current.comment : null;
  return `<div class="feedback-bar">
    <span class="feedback-bar__label">Évaluation :</span>
    ${Object.entries(_FB_LABELS).map(([dec, { label, icon, cls }]) => {
      const active = decision === dec ? " is-active" : "";
      return `<button class="feedback-btn feedback-btn--${cls}${active}"
        data-feedback data-match="${mid}" data-decision="${dec}"
        title="${label}">${icon} ${label}</button>`;
    }).join("")}
    ${comment ? `<div class="feedback-bar__comment text-xs text-muted">${escapeHtml(comment)}</div>` : ""}
  </div>`;
}

function _renderFeedbackForm(matchId) {
  if (!matchId) return "";
  const mid = escapeHtml(String(matchId));
  const current = _feedbackCache.get(String(matchId));
  return `
<div class="stack" style="gap:var(--space-3)" id="feedbackForm-${mid}">
  <div class="divider-label">Votre évaluation</div>
  <div class="feedback-bar">
    ${Object.entries(_FB_LABELS).map(([decision, { label, icon, cls }]) => {
      const active = current?.decision === decision ? " is-active" : "";
      return `<button class="feedback-btn feedback-btn--${cls}${active}"
        data-fb-decision="${decision}">${icon} ${label}</button>`;
    }).join("")}
  </div>
  <div class="star-rating" id="feedbackStars-${mid}">
    ${[1,2,3,4,5].map((n) => {
      const active = current?.rating >= n ? " is-active" : "";
      return `<span class="star-rating__star${active}" data-star="${n}">★</span>`;
    }).join("")}
  </div>
  <textarea id="feedbackComment-${mid}" rows="2"
    class="input" style="resize:vertical"
    placeholder="Commentaire optionnel…">${escapeHtml(current?.comment ?? "")}</textarea>
  <div>
    <button class="btn btn--primary btn--sm" data-fb-submit="${mid}">Enregistrer</button>
    <span id="feedbackMsg-${mid}" class="text-xs text-muted" style="margin-left:var(--space-2)"></span>
  </div>
</div>`;
}

async function _submitQuickFeedback(btn) {
  const matchId  = btn.dataset.match;
  const decision = btn.dataset.decision;
  if (!matchId || !decision) return;

  // Optimistic update
  _feedbackCache.set(matchId, decision);
  _refreshCardFeedback(matchId, decision);

  try {
    await safeFetch(`/matches/${matchId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
  } catch {
    // Revert on error
    _feedbackCache.delete(matchId);
    _refreshCardFeedback(matchId, null);
  }
}

function _refreshCardFeedback(matchId, decision, comment = null) {
  const card = document.querySelector(`[data-match-id="${matchId}"]`);
  if (!card) return;
  const bar = card.querySelector(".feedback-bar");
  if (!bar) return;
  bar.outerHTML = _renderFeedbackBar(matchId, comment ? { decision, comment } : decision);
}

function _wireFeedbackForm(matchId) {
  const mid    = String(matchId);
  const form   = document.getElementById(`feedbackForm-${mid}`);
  const stars  = document.getElementById(`feedbackStars-${mid}`);
  const msg    = document.getElementById(`feedbackMsg-${mid}`);
  if (!form) return;

  let selectedDecision = _feedbackCache.get(mid)?.decision ?? null;
  let selectedRating   = _feedbackCache.get(mid)?.rating   ?? 0;

  // Decision buttons
  form.querySelectorAll("[data-fb-decision]").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedDecision = btn.dataset.fbDecision;
      form.querySelectorAll("[data-fb-decision]").forEach((b) => {
        b.classList.toggle("is-active", b.dataset.fbDecision === selectedDecision);
      });
    });
  });

  // Star rating
  stars?.querySelectorAll(".star-rating__star").forEach((star) => {
    star.addEventListener("click", () => {
      selectedRating = Number(star.dataset.star);
      stars.querySelectorAll(".star-rating__star").forEach((s) => {
        s.classList.toggle("is-active", Number(s.dataset.star) <= selectedRating);
      });
    });
  });

  // Submit
  form.querySelector(`[data-fb-submit="${mid}"]`)?.addEventListener("click", async () => {
    if (!selectedDecision) {
      if (msg) msg.textContent = "Choisissez une décision.";
      return;
    }
    const comment = document.getElementById(`feedbackComment-${mid}`)?.value.trim() || null;
    const payload = { decision: selectedDecision, rating: selectedRating || null, comment };

    try {
      await safeFetch(`/matches/${mid}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      _feedbackCache.set(mid, payload);
      if (msg) { msg.textContent = "Enregistré ✓"; msg.style.color = "var(--color-success)"; }
      _refreshCardFeedback(mid, selectedDecision, payload.comment);
    } catch (err) {
      if (msg) { msg.textContent = err.message; msg.style.color = "var(--color-error)"; }
    }
  });
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
