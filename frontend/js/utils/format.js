export const clampScore = (v) => Math.max(0, Math.min(100, Math.round(Number(v) || 0)));

export const scoreTone = (score) => {
  if (score >= 80) return { key: "high", label: "Fort" };
  if (score >= 60) return { key: "mid",  label: "Moyen" };
  return             { key: "low",  label: "À vérifier" };
};

// A match whose score came only from the cheap vector-similarity
// pre-filter (see matcher.py's embedding overflow path) has a real,
// often misleadingly high `score` but no skill/keyword breakdown at all
// -- every component is computed together or not at all (see
// _upsert_match_result's cs={} case), so the absence of just one
// (score_skills) reliably means none of them landed yet. The automatic
// follow-up rescore that corrects it can take a while if the processing
// queue is backed up, so showing that provisional number as a confident
// "Fort"/"Moyen" result in the meantime would read as the platform
// reporting a wrong answer, not a working one.
export const isProvisionalScore = (match) => match?.score_skills == null;

export const renderScoreChip = (score, provisional = false) => {
  if (provisional) {
    return `<span class="score-chip score-chip--pending" title="Analyse complète en cours — ce score n'est pas encore fiable">Analyse en cours…</span>`;
  }
  const { key, label } = scoreTone(score);
  return `<span class="score-chip score-chip--${key}" title="${label}">${score}%</span>`;
};

export const renderScoreBar = (score, provisional = false) => {
  if (provisional) {
    return `<div class="score-bar"><div class="score-bar__fill" style="width:100%;opacity:.25"></div></div>`;
  }
  const { key } = scoreTone(score);
  return `<div class="score-bar"><div class="score-bar__fill score-bar__fill--${key}" style="width:${score}%"></div></div>`;
};

export const renderKeywordChips = (keywords) => {
  const list = (keywords ?? []).filter(Boolean).slice(0, 6);
  if (!list.length) return `<p class="text-muted text-xs">Aucun mot-clé détecté.</p>`;
  return `<div class="chip-row">${list.map((k) => `<span class="chip">${k}</span>`).join("")}</div>`;
};

export const formatDate = (iso) =>
  iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";

export const statusBadge = (status) => {
  const map = { ready: "Prêt", pending: "En attente", failed: "Échec", draft: "Brouillon", published: "Publié" };
  return `<span class="badge badge--${status ?? "default"}">${map[status] ?? status ?? "—"}</span>`;
};

export const initials = (name) =>
  (name ?? "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
