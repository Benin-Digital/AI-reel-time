export const clampScore = (v) => Math.max(0, Math.min(100, Math.round(Number(v) || 0)));

export const scoreTone = (score) => {
  if (score >= 80) return { key: "high", label: "Fort" };
  if (score >= 60) return { key: "mid",  label: "Moyen" };
  return             { key: "low",  label: "À vérifier" };
};

export const renderScoreChip = (score) => {
  const { key, label } = scoreTone(score);
  return `<span class="score-chip score-chip--${key}" title="${label}">${score}%</span>`;
};

export const renderScoreBar = (score) => {
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
