import { safeFetch } from "../api.js";
import { $, escapeHtml } from "../utils/dom.js";
import { scoreTone } from "../utils/format.js";

export function initFeedbackStats() {
  $("#refreshFeedbackStats")?.addEventListener("click", _load);
  window.addEventListener("load-feedback-stats", _load);
}

async function _load() {
  const container = $("#feedbackStatsContent");
  if (!container) return;

  container.innerHTML = `
    <div class="skeleton skeleton--card"></div>
    <div class="skeleton skeleton--card" style="margin-top:var(--space-4)"></div>`;

  try {
    const data = await safeFetch("/feedback/stats");
    container.innerHTML = _render(data);
  } catch (err) {
    if (err.name !== "AuthError") {
      container.innerHTML = `<div class="empty-state"><div class="empty-state__hint text-error">${escapeHtml(err.message)}</div></div>`;
    }
  }
}

function _render(data) {
  if (data.total === 0) {
    return `<div class="empty-state">
      <div class="empty-state__icon"><svg width="32" height="32" viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="13.5" stroke="currentColor" stroke-width="1.5"/><path d="M16 10v6M16 20v2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></div>
      <div class="empty-state__title">Aucune évaluation</div>
      <div class="empty-state__hint">Évaluez des correspondances depuis le panel Correspondances pour voir les statistiques ici.</div>
    </div>`;
  }

  return `
    ${_renderSummaryCards(data)}
    <div style="margin-top:var(--space-4)">${_renderDecisionDistribution(data)}</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4);margin-top:var(--space-4)">
      ${_renderWeightHints(data.weight_hints)}
      ${_renderDecisionScores(data)}
    </div>
    ${data.by_domain.length ? `<div style="margin-top:var(--space-4)">${_renderDomainTable(data.by_domain)}</div>` : ""}
  `.trim();
}

function _renderSummaryCards(data) {
  const dec   = data.by_decision ?? {};
  const accept = dec.accept ?? { count: 0, pct: 0, avg_rating: null };
  const reject = dec.reject ?? { count: 0, pct: 0, avg_rating: null };
  const review = dec.review ?? { count: 0, pct: 0, avg_rating: null };

  const allRatings = Object.values(dec)
    .map((d) => d.avg_rating)
    .filter((r) => r != null);
  const globalRating = allRatings.length
    ? (allRatings.reduce((a, b) => a + b, 0) / allRatings.length).toFixed(1)
    : null;

  return `<div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-card__label">Total évaluations</div>
      <div class="metric-card__value">${data.total}</div>
      <div class="metric-card__hint">feedbacks enregistrés</div>
    </div>
    <div class="metric-card">
      <div class="metric-card__label" style="color:var(--color-success)">Acceptés</div>
      <div class="metric-card__value">${accept.count}</div>
      <div class="metric-card__hint">${accept.pct}% des évaluations</div>
    </div>
    <div class="metric-card">
      <div class="metric-card__label" style="color:var(--color-error)">Rejetés</div>
      <div class="metric-card__value">${reject.count}</div>
      <div class="metric-card__hint">${reject.pct}% des évaluations</div>
    </div>
    <div class="metric-card">
      <div class="metric-card__label" style="color:var(--color-warning)">À revoir</div>
      <div class="metric-card__value">${review.count}</div>
      <div class="metric-card__hint">${review.pct}% des évaluations</div>
    </div>
    ${globalRating != null ? `
    <div class="metric-card">
      <div class="metric-card__label">Note moyenne</div>
      <div class="metric-card__value">${globalRating} / 5</div>
      <div class="metric-card__hint">sur les évaluations notées</div>
    </div>` : ""}
  </div>`;
}

function _renderDecisionDistribution(data) {
  const dec    = data.by_decision ?? {};
  const accept = dec.accept ?? { count: 0, pct: 0 };
  const review = dec.review ?? { count: 0, pct: 0 };
  const reject = dec.reject ?? { count: 0, pct: 0 };

  return `<div class="chart-card">
    <div class="chart-card__title">Répartition des décisions</div>
    <div class="decision-bar">
      ${accept.pct ? `<div class="decision-bar__segment decision-bar__segment--accept" style="width:${accept.pct}%"></div>` : ""}
      ${review.pct ? `<div class="decision-bar__segment decision-bar__segment--review" style="width:${review.pct}%"></div>` : ""}
      ${reject.pct ? `<div class="decision-bar__segment decision-bar__segment--reject" style="width:${reject.pct}%"></div>` : ""}
    </div>
    <div class="chart-card__legend">
      <span class="legend-item"><span class="legend-dot legend-dot--accept"></span>Acceptés : <strong>${accept.count}</strong> (${accept.pct}%)</span>
      <span class="legend-item"><span class="legend-dot legend-dot--review"></span>À revoir : <strong>${review.count}</strong> (${review.pct}%)</span>
      <span class="legend-item"><span class="legend-dot legend-dot--reject"></span>Rejetés : <strong>${reject.count}</strong> (${reject.pct}%)</span>
    </div>
  </div>`;
}

function _renderWeightHints(hints) {
  if (!hints?.length) return `<div class="card"><div class="card__header"><div class="card__title">Prédicteurs d'acceptation</div></div><p class="text-sm text-muted" style="padding:var(--space-4)">Pas encore assez de données (besoin d'évaluations acceptées ET rejetées).</p></div>`;

  const maxDelta = Math.max(...hints.map((h) => Math.abs(h.delta)), 0.001);

  // Impact magnitude has its own 4-bucket scale (not the 3-tier red/orange/
  // green match-score scale) — direct colors, independent of the shared
  // score tone tokens.
  const DELTA_COLORS = { excellent: "#22c55e", strong: "#4F6EF7", medium: "#f59e0b", weak: "#ef4444" };

  const rows = hints.map((h) => {
    const pct   = Math.round((h.delta / maxDelta) * 100);
    const tone  = h.delta >= 0.1 ? "excellent" : h.delta >= 0.05 ? "strong" : h.delta >= 0 ? "medium" : "weak";
    const color = DELTA_COLORS[tone];
    const arrow = h.delta > 0 ? "↑" : "↓";
    const sign  = h.delta >= 0 ? "+" : "";
    return `<div class="score-breakdown__item" style="margin-bottom:var(--space-2)">
      <span class="score-breakdown__label">${escapeHtml(h.label)}</span>
      <div class="score-breakdown__bar">
        <div class="score-breakdown__bar-fill" style="width:${Math.abs(pct)}%;background:${color}"></div>
      </div>
      <span class="score-breakdown__value" style="color:${color}">${arrow} ${sign}${(h.delta * 100).toFixed(1)}%</span>
    </div>`;
  }).join("");

  return `<div class="card">
    <div class="card__header">
      <div class="card__title">Prédicteurs d'acceptation</div>
      <span class="text-xs text-muted">delta = score moyen accepté − rejeté</span>
    </div>
    <div style="padding:var(--space-4)">
      <div class="score-breakdown" style="flex-direction:column;gap:var(--space-1)">
        ${rows}
      </div>
      <p class="text-xs text-muted" style="margin-top:var(--space-3)">Les composantes avec le delta le plus élevé sont les meilleurs prédicteurs de qualité pour vos cas réels.</p>
    </div>
  </div>`;
}

function _renderDecisionScores(data) {
  const accept = data.avg_scores_by_decision?.accept;
  const reject = data.avg_scores_by_decision?.reject;

  if (!accept && !reject) return `<div class="card"><div class="card__header"><div class="card__title">Scores moyens par décision</div></div><p class="text-sm text-muted" style="padding:var(--space-4)">Données insuffisantes.</p></div>`;

  const comps = [
    { key: "score_skills",     label: "Compétences" },
    { key: "score_semantic",   label: "Sémantique" },
    { key: "score_experience", label: "Expérience" },
    { key: "score_education",  label: "Formation" },
    { key: "score_languages",  label: "Langues" },
    { key: "score_contract",   label: "Contrat" },
  ];

  const rows = comps.map(({ key, label }) => {
    const a   = accept?.[key];
    const r   = reject?.[key];
    const aP  = a != null ? Math.round(a * 100) : null;
    const rP  = r != null ? Math.round(r * 100) : null;
    return `<tr>
      <td class="text-sm text-secondary" style="padding:var(--space-1) var(--space-2)">${escapeHtml(label)}</td>
      <td style="padding:var(--space-1) var(--space-2)">
        ${aP != null ? `<span style="color:var(--color-success);font-weight:var(--weight-medium)">${aP}%</span>` : `<span class="text-muted">—</span>`}
      </td>
      <td style="padding:var(--space-1) var(--space-2)">
        ${rP != null ? `<span style="color:var(--color-error)">${rP}%</span>` : `<span class="text-muted">—</span>`}
      </td>
    </tr>`;
  }).join("");

  const aGlobal = accept?.score_global;
  const rGlobal = reject?.score_global;

  return `<div class="card">
    <div class="card__header">
      <div class="card__title">Scores moyens par décision</div>
    </div>
    <div style="padding:var(--space-4)">
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr>
            <th class="text-xs text-muted" style="text-align:left;padding:var(--space-1) var(--space-2)">Composante</th>
            <th class="text-xs" style="color:var(--color-success);padding:var(--space-1) var(--space-2)">✓ Accepté</th>
            <th class="text-xs" style="color:var(--color-error);padding:var(--space-1) var(--space-2)">✗ Rejeté</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
        ${aGlobal != null || rGlobal != null ? `
        <tfoot>
          <tr style="border-top:1px solid var(--border-subtle)">
            <td class="text-sm font-semibold" style="padding:var(--space-2) var(--space-2)">Score global</td>
            <td style="padding:var(--space-2) var(--space-2)">
              ${aGlobal != null ? `<span style="color:var(--color-success);font-weight:var(--weight-semibold)">${aGlobal}%</span>` : "—"}
            </td>
            <td style="padding:var(--space-2) var(--space-2)">
              ${rGlobal != null ? `<span style="color:var(--color-error)">${rGlobal}%</span>` : "—"}
            </td>
          </tr>
        </tfoot>` : ""}
      </table>
    </div>
  </div>`;
}

function _renderDomainTable(domains) {
  const rows = domains.map((d) => {
    const rate = d.total > 0 ? Math.round((d.accept / d.total) * 100) : 0;
    const tone = scoreTone(rate).key;
    const acceptPct = d.total > 0 ? (d.accept / d.total) * 100 : 0;
    const reviewPct = d.total > 0 ? (d.review / d.total) * 100 : 0;
    const rejectPct = d.total > 0 ? (d.reject / d.total) * 100 : 0;
    return `<tr>
      <td style="padding:var(--space-2) var(--space-3)" class="text-sm text-secondary">${escapeHtml(d.domain)}</td>
      <td style="padding:var(--space-2) var(--space-3)" class="text-sm">${d.total}</td>
      <td style="padding:var(--space-2) var(--space-3)">
        <div style="display:flex;align-items:center;gap:var(--space-2)">
          <div class="decision-bar decision-bar--mini" style="flex:1" title="${d.accept} acceptés / ${d.review} à revoir / ${d.reject} rejetés">
            ${acceptPct ? `<div class="decision-bar__segment decision-bar__segment--accept" style="width:${acceptPct}%"></div>` : ""}
            ${reviewPct ? `<div class="decision-bar__segment decision-bar__segment--review" style="width:${reviewPct}%"></div>` : ""}
            ${rejectPct ? `<div class="decision-bar__segment decision-bar__segment--reject" style="width:${rejectPct}%"></div>` : ""}
          </div>
          <span class="text-xs text-muted" style="white-space:nowrap">
            <span style="color:var(--color-success)">${d.accept}</span>/<span style="color:var(--color-warning)">${d.review}</span>/<span style="color:var(--color-error)">${d.reject}</span>
          </span>
        </div>
      </td>
      <td style="padding:var(--space-2) var(--space-3)">
        <span class="score-chip score-chip--${tone}" style="font-size:var(--text-xs)">${rate}%</span>
      </td>
      <td style="padding:var(--space-2) var(--space-3)" class="text-sm text-muted">${d.avg_score != null ? d.avg_score + "%" : "—"}</td>
    </tr>`;
  }).join("");

  return `<div class="card">
    <div class="card__header"><div class="card__title">Par domaine</div></div>
    <div class="table-wrapper">
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:1px solid var(--border-subtle)">
            <th class="text-xs text-muted" style="text-align:left;padding:var(--space-2) var(--space-3)">Domaine</th>
            <th class="text-xs text-muted" style="padding:var(--space-2) var(--space-3)">Total</th>
            <th class="text-xs text-muted" style="padding:var(--space-2) var(--space-3)">Répartition</th>
            <th class="text-xs text-muted" style="padding:var(--space-2) var(--space-3)">Taux accept.</th>
            <th class="text-xs text-muted" style="padding:var(--space-2) var(--space-3)">Score moy.</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </div>`;
}
