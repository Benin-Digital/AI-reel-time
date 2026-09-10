import { safeFetch, fetchBlob } from "../api.js";
import { $, openModal, closeModal, setBanner, escapeHtml, renderEmpty } from "../utils/dom.js";
import {
  renderScoreChip,
  renderScoreBar,
  renderKeywordChips,
  formatDate,
  clampScore,
  scoreTone,
} from "../utils/format.js";
import { buildParams, setPage } from "../utils/docs.js";
import { canManageUsers } from "../auth.js";

let _page = 1;
// Local cache: matchId → decision ("accept" | "reject" | "review")
const _feedbackCache = new Map();
let _progressPollTimer = null;
let _progressPollAttempts = 0;
// Documents flip to "ready" as soon as extraction succeeds, before
// _score_against_counterparts()'s matching loop runs against every active
// counterpart (see main.py) -- so "ready" CVs/offers can sit for a while
// with matches trickling in one at a time. Without polling, the page only
// updated on a manual filter change or a full reload, and in the meantime
// showed either a stale list or "Aucune correspondance" (the exact same
// empty state as "you haven't imported anything"), with nothing telling
// the recruiter that a calculation was still running.
const _PROGRESS_POLL_MS = 5000;
const _PROGRESS_POLL_MAX_ATTEMPTS = 120; // ~10 minutes at 5s/tick

// After a forced recompute, every active MatchResult row already exists
// (it's an in-place upsert, not a delete+recreate) -- so computed_pairs
// already equals expected_pairs before the recompute even finishes, and
// the ordinary progress poll above never sees anything "incomplete" to
// react to. Poll the list directly on a fixed schedule instead, so scores
// visibly update as the backend works through the queue.
const _RECOMPUTE_POLL_MS = 5000;
const _RECOMPUTE_POLL_TICKS = 18; // ~90s -- now re-extracts (PyMuPDF/OCR) every file, not just rescoring

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

    // View the CV / job PDF directly from the match card
    const viewBtn = e.target.closest("[data-view-doc]");
    if (viewBtn) _viewDocumentPdf(viewBtn.dataset.viewDoc, viewBtn.dataset.docId, viewBtn);
  });

  // Close modal when a [data-modal-close] element is clicked
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-modal-close]")) {
      const modal = e.target.closest(".modal");
      if (modal) closeModal(modal);
    }
  });

  $("#matchesRecomputeBtn")?.addEventListener("click", () => _recomputeMatches());

  window.addEventListener("load-matches", () => {
    const action = $("#matchesRecomputeAction");
    if (action) action.hidden = !canManageUsers();
    _load();
  });

  // Dashboard "meilleure correspondance active" widget -- same card, same
  // actions (voir CV/offre, analyser, évaluer) as the Correspondances page,
  // wired through the same handlers via delegation on its own container.
  $("#dashboardBestMatchCard")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-explain]");
    if (btn) _loadExplain(btn.dataset.explain);

    const fb = e.target.closest("[data-feedback]");
    if (fb) _submitQuickFeedback(fb);

    const viewBtn = e.target.closest("[data-view-doc]");
    if (viewBtn) _viewDocumentPdf(viewBtn.dataset.viewDoc, viewBtn.dataset.docId, viewBtn);
  });
  window.addEventListener("load-dashboard", () => _loadDashboardBestMatch());
}

async function _loadDashboardBestMatch() {
  const container = $("#dashboardBestMatchCard");
  if (!container) return;
  container.innerHTML = `<div class="skeleton skeleton--card"></div>`;
  try {
    const data = await safeFetch(`/matches?page_size=1&sort_by=score_desc&unassigned_only=true`);
    if (!data.length) {
      container.innerHTML = renderEmpty("Aucune correspondance active pour l'instant.");
      return;
    }
    const match = data[0];
    if (match.feedback_decision) {
      _feedbackCache.set(String(match.id), {
        decision: match.feedback_decision,
        rating: match.feedback_rating ?? 0,
        comment: match.feedback_comment ?? null,
      });
    }
    container.innerHTML = _renderMatchCard(match);
  } catch (err) {
    if (err.name !== "AuthError") {
      container.innerHTML = `<div class="banner banner--error">${escapeHtml(err.message)}</div>`;
    }
  }
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
  if (_progressPollTimer) { clearTimeout(_progressPollTimer); _progressPollTimer = null; }
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
    const [data, progress] = await Promise.all([
      safeFetch(`/matches${params}`),
      safeFetch("/matches/progress").catch(() => null),
    ]);

    const pageEl  = $("#matchesPage");
    if (pageEl) setPage(pageEl, _page);
    const prevBtn = $("#matchesPrev");
    if (prevBtn) prevBtn.disabled = _page <= 1;

    _updateSidebarReviewBadge(progress);

    const incomplete = !!progress && progress.expected_pairs > progress.computed_pairs;
    // The empty-state below already explains "calcul en cours" on its own
    // when there's nothing to show yet -- only surface the banner once
    // there's an actual list underneath it, to avoid saying the same thing
    // twice.
    _renderProgressBanner(progress, incomplete && data.length > 0);

    if (!data.length) {
      list.innerHTML = incomplete
        ? `<div class="empty-state">
            <div class="empty-state__icon empty-state__icon--spin"><svg width="32" height="32" viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="13.5" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="60 40"/></svg></div>
            <div class="empty-state__title">Calcul des correspondances en cours…</div>
            <div class="empty-state__hint">Les CV et offres sont prêts, le rapprochement des scores démarre — cette liste se mettra à jour automatiquement.</div>
          </div>`
        : `<div class="empty-state">
            <div class="empty-state__icon"><svg width="32" height="32" viewBox="0 0 32 32" fill="none"><path d="M10 16h12M16 10l6 6-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="16" cy="16" r="13.5" stroke="currentColor" stroke-width="1.5"/></svg></div>
            <div class="empty-state__title">Aucune correspondance</div>
            <div class="empty-state__hint">Importez des CV et des offres, puis attendez le traitement.</div>
          </div>`;
    } else {
      // Seed the feedback cache from the server's own persisted state:
      // without this, a saved evaluation only showed up in the card list
      // while its decision happened to already be in this in-memory cache
      // (set when the user picked it, or when the "Analyser" modal was
      // opened for that exact match in this page load) -- any other page
      // load, including a plain refresh, showed every match as unevaluated
      // even though the feedback was sitting untouched in the database.
      for (const match of data) {
        if (match.feedback_decision) {
          _feedbackCache.set(String(match.id), {
            decision: match.feedback_decision,
            rating: match.feedback_rating ?? 0,
            comment: match.feedback_comment ?? null,
          });
        }
      }
      list.innerHTML = data.map(_renderMatchCard).join("");
    }

    _scheduleProgressPoll(incomplete);
  } catch (err) {
    if (err.name !== "AuthError") {
      list.innerHTML = `<div class="empty-state"><div class="empty-state__hint text-error">${err.message}</div></div>`;
    }
  }
}

// Piggybacks on the /matches/progress fetch _load() already makes -- no
// extra request, so the "Correspondances" sidebar badge stays current
// every time this panel is visited, without a background poll running
// while the user is elsewhere (that pattern is exactly what caused a real
// rate-limit outage during a bulk upload earlier -- see cv-library.js).
function _updateSidebarReviewBadge(progress) {
  const badge = $("#matchesReviewBadge");
  if (!badge) return;
  const count = progress?.unreviewed_count ?? 0;
  badge.textContent = String(count);
  badge.hidden = count === 0;
}

function _renderProgressBanner(progress, incomplete) {
  const el = $("#matchProgressStatus");
  if (!el) return;
  if (!incomplete) { setBanner(el, ""); return; }
  setBanner(
    el,
    `Calcul des correspondances en cours… ${progress.computed_pairs}/${progress.expected_pairs} déjà disponibles.`,
    "info"
  );
}

async function _recomputeMatches() {
  const btn = $("#matchesRecomputeBtn");
  const msg = $("#matchesRecomputeMsg");
  setBanner(msg, "");
  if (btn) { btn.disabled = true; btn.textContent = "Relance en cours…"; }

  try {
    const result = await safeFetch("/matches/recompute", { method: "POST" });
    setBanner(
      msg,
      `Réextraction et recalcul lancés pour ${result.queued} CV — les scores ci-dessous se mettront à jour au fur et à mesure. Pour une grosse bibliothèque, revenez sur cette page un peu plus tard si tout n'a pas fini de se mettre à jour.`,
      "info"
    );
    _pollAfterRecompute();
  } catch (err) {
    setBanner(msg, err.message, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Relancer l'IA"; }
  }
}

function _pollAfterRecompute() {
  let ticks = 0;
  const tick = () => {
    ticks++;
    const stillOnThisPanel = !document.querySelector('.view[data-panel="matches"]')?.hidden;
    if (stillOnThisPanel) _load();
    if (ticks < _RECOMPUTE_POLL_TICKS && stillOnThisPanel) setTimeout(tick, _RECOMPUTE_POLL_MS);
  };
  setTimeout(tick, _RECOMPUTE_POLL_MS);
}

function _scheduleProgressPoll(incomplete) {
  if (!incomplete) { _progressPollAttempts = 0; return; }
  const section = document.querySelector('.view[data-panel="matches"]');
  if (section?.hidden) { _progressPollAttempts = 0; return; }
  if (_progressPollAttempts >= _PROGRESS_POLL_MAX_ATTEMPTS) { _progressPollAttempts = 0; return; }
  _progressPollAttempts++;
  _progressPollTimer = setTimeout(() => {
    const stillOnThisPanel = !document.querySelector('.view[data-panel="matches"]')?.hidden;
    if (stillOnThisPanel) _load();
  }, _PROGRESS_POLL_MS);
}

const _CV_ICON  = `<svg width="18" height="18" viewBox="0 0 16 16" fill="none"><rect x="3" y="1.5" width="10" height="13" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;
const _JOB_ICON = `<svg width="18" height="18" viewBox="0 0 16 16" fill="none"><rect x="1" y="5" width="14" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M5 5V3.5A1.5 1.5 0 0 1 6.5 2h3A1.5 1.5 0 0 1 11 3.5V5" stroke="currentColor" stroke-width="1.5"/></svg>`;

function _renderMatchCard(match) {
  const score    = clampScore(match.score);
  const tone     = scoreTone(score);
  const keywords = (match.common_keywords ?? []).filter(Boolean).slice(0, 6);
  const domain   = match.match_domain ? `<span class="badge badge--primary">${escapeHtml(match.match_domain)}</span>` : "";
  const current  = _feedbackCache.get(String(match.id)) ?? null;
  const cvLabel  = escapeHtml(match.cv_label || `CV ${match.cv_id}`);
  const jobLabel = escapeHtml(match.job_label || `Offre ${match.job_id}`);

  return `
<article class="match-card" data-match-id="${escapeHtml(String(match.id))}">
  <div class="match-faceoff">
    <div class="match-faceoff__side">
      <div class="match-faceoff__icon">${_CV_ICON}</div>
      <div class="match-faceoff__label truncate" title="${cvLabel} (CV #${escapeHtml(String(match.cv_id))})">${cvLabel}</div>
      <button class="btn btn--ghost btn--sm" data-view-doc="cv" data-doc-id="${escapeHtml(String(match.cv_id))}">Voir le CV</button>
    </div>
    <div class="match-faceoff__score">
      <span class="score-chip score-chip--${tone.key} match-faceoff__score-chip">${score}%</span>
      <span class="text-xs text-muted">${tone.label}</span>
      ${domain}
      <button class="btn btn--ghost btn--sm" data-explain="${escapeHtml(String(match.id))}">Analyser</button>
    </div>
    <div class="match-faceoff__side match-faceoff__side--right">
      <div class="match-faceoff__icon">${_JOB_ICON}</div>
      <div class="match-faceoff__label truncate" title="${jobLabel} (Offre #${escapeHtml(String(match.job_id))})">${jobLabel}</div>
      <button class="btn btn--ghost btn--sm" data-view-doc="job" data-doc-id="${escapeHtml(String(match.job_id))}">Voir l'offre</button>
    </div>
  </div>
  <div class="match-card__body">
    <p class="text-xs text-muted">Match #${escapeHtml(String(match.id))}</p>
    ${renderScoreBar(score)}
    ${_renderComponentScores(match)}
    <div class="match-card__meta">${renderKeywordChips(keywords)}</div>
    ${_renderFeedbackBar(match.id, current)}
  </div>
</article>`.trim();
}

async function _viewDocumentPdf(kind, id, btn) {
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Ouverture…";
  const rawPath    = kind === "cv" ? `/cv-documents/${id}/pdf` : `/job-documents/${id}/pdf`;
  const parsedPath = kind === "cv" ? `/cv-documents/${id}/parsed-pdf` : `/job-documents/${id}/parsed-pdf`;
  try {
    let blob;
    try {
      blob = await fetchBlob(rawPath);
    } catch (err) {
      // The original file isn't a PDF (DOCX/TXT) — there's no way to view
      // it as-is in a new tab, but the extracted text is already rendered
      // as a PDF elsewhere in the app. Show that instead of a dead end.
      if (err.status !== 415) throw err;
      blob = await fetchBlob(parsedPath, { timeout: 60000 });
    }
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (err) {
    btn.title = err.message;
    btn.textContent = "Indisponible";
    setTimeout(() => { btn.textContent = originalText; btn.title = ""; }, 3000);
  } finally {
    btn.disabled = false;
    if (btn.textContent === "Ouverture…") btn.textContent = originalText;
  }
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
    </div>
    <p class="text-xs text-muted" id="explainWait" style="padding:0 var(--space-4)">Analyse en cours…</p>`;
  openModal(modal);

  // The first analysis after a while can be slow (cold model cache) — a
  // silent skeleton for up to 90s reads as frozen. Show elapsed time and a
  // reassurance line past the point where it'd normally be done.
  const waitStartedAt = Date.now();
  const waitTimer = setInterval(() => {
    const el = content.querySelector("#explainWait");
    if (!el) return;
    const elapsed = Math.round((Date.now() - waitStartedAt) / 1000);
    const hint = elapsed > 15 ? " — première analyse après une pause, ça peut prendre un peu plus longtemps" : "";
    el.textContent = `Analyse en cours… (${elapsed}s)${hint}`;
  }, 1000);

  try {
    // Load explain data and existing feedback in parallel.
    // /explain rebuilds both StructuredDocuments and runs scoring — cold
    // cache + Docling + NER can push this past 30s. Allow 90s here.
    const [data, existingFb] = await Promise.all([
      safeFetch(`/matches/${matchId}/explain`, { timeout: 90000, retries: 0 }),
      safeFetch(`/matches/${matchId}/feedback`).catch(() => null),
    ]);

    if (existingFb) _feedbackCache.set(String(matchId), existingFb);

    clearInterval(waitTimer);
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
    clearInterval(waitTimer);
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
