import { safeFetch } from "../api.js";
import { $, setBanner, show, hide, escapeHtml } from "../utils/dom.js";
import { store } from "../store.js";
import { formatDate } from "../utils/format.js";

export function initArchives() {
  $("#archiveCreateForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const feedback = $("#archiveCreateFeedback");
    const btn = e.target.querySelector('[type="submit"]');
    const name = $("#archiveName")?.value.trim();
    const description = $("#archiveDescription")?.value.trim();

    if (!name) {
      setBanner(feedback, "Le nom est obligatoire.", "error");
      return;
    }

    setBanner(feedback, "");
    if (btn) { btn.disabled = true; btn.textContent = "Création…"; }

    try {
      const session = await safeFetch("/sessions", {
        method: "POST",
        body: JSON.stringify({ name, description }),
        json: true,
      });

      // Assign current cached documents to the new session
      const payload = {};
      const cvs  = store.cachedCvDocuments;
      const jobs = store.cachedJobDocuments;
      if (cvs?.length)  payload.cv_ids  = cvs.map((d) => d.id);
      if (jobs?.length) payload.job_ids = jobs.map((d) => d.id);

      if (payload.cv_ids || payload.job_ids) {
        await safeFetch(`/sessions/${session.id}/assign`, {
          method: "POST",
          body: JSON.stringify(payload),
          json: true,
        });
      }

      setBanner(feedback, "Archive créée.", "success");
      e.target.reset();
      _loadSessions();
    } catch (err) {
      setBanner(feedback, err.message, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Créer l'archive"; }
    }
  });

  // Click delegation on the sessions list
  $("#archiveSessionsList")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-open-session]");
    if (btn) _loadDetail(btn.dataset.openSession);
  });

  window.addEventListener("load-archives", () => _loadSessions());
}

async function _loadSessions() {
  const list = $("#archiveSessionsList");
  if (!list) return;

  try {
    const sessions = await safeFetch("/sessions");

    if (!sessions.length) {
      list.innerHTML = `<div class="empty-state"><div class="empty-state__hint">Aucune archive créée.</div></div>`;
      return;
    }

    list.innerHTML = sessions
      .map(
        (s) => `
      <article class="doc-item" style="cursor:pointer" data-archive-id="${s.id}">
        <div class="doc-item__icon"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1" y="2" width="14" height="3.5" rx="1" stroke="currentColor" stroke-width="1.5"/><path d="M2.5 5.5v8a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-8" stroke="currentColor" stroke-width="1.5"/><path d="M6.5 9h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></div>
        <div class="doc-item__body">
          <div class="doc-item__name truncate">${escapeHtml(s.name)}</div>
          <div class="doc-item__meta">
            <span class="badge badge--${s.status === "closed" ? "default" : "success"}">
              ${s.status === "closed" ? "Fermée" : "Ouverte"}
            </span>
            <span>${s.cv_count ?? 0} CV</span>
            <span>${s.job_count ?? 0} offres</span>
            <span>${s.match_count ?? 0} matches</span>
          </div>
        </div>
        <div class="doc-item__actions">
          <button class="btn btn--ghost btn--sm" data-open-session="${s.id}">Ouvrir</button>
        </div>
      </article>
    `
      )
      .join("");
  } catch (err) {
    if (err.name !== "AuthError") {
      list.innerHTML = `<div class="empty-state"><div class="empty-state__hint text-error">${escapeHtml(err.message)}</div></div>`;
    }
  }
}

async function _loadDetail(sessionId) {
  const detailEl = $("#archiveDetails");
  if (!detailEl) return;

  show(detailEl);
  detailEl.innerHTML = `<div class="skeleton skeleton--card"></div>`;

  try {
    const [s, matches] = await Promise.all([
      safeFetch(`/sessions/${sessionId}`),
      safeFetch(`/matches?session_id=${sessionId}&page_size=50&sort_by=score_desc`).catch(() => []),
    ]);

    const statusVariant = s.status === "closed" ? "default" : "success";
    const statusLabel   = s.status === "closed" ? "Fermée" : "Ouverte";

    const _basename = (p) => (p ? p.replace(/\\/g, "/").split("/").pop() : "");

    const cvHtml = s.cv_documents?.length
      ? s.cv_documents.map((d) => `<div class="text-xs text-secondary truncate" title="${escapeHtml(d.path ?? "")}">CV ${d.id} — ${escapeHtml(_basename(d.path))}</div>`).join("")
      : `<span class="text-xs text-muted">Aucun</span>`;

    const jobHtml = s.job_documents?.length
      ? s.job_documents.map((d) => `<div class="text-xs text-secondary truncate" title="${escapeHtml(d.path ?? "")}">Offre ${d.id} — ${escapeHtml(_basename(d.path))}</div>`).join("")
      : `<span class="text-xs text-muted">Aucune</span>`;

    const matchHtml = matches?.length
      ? matches.map((m) => {
          const score = Math.max(0, Math.min(100, Math.round(Number(m.score) || 0)));
          const tone  = score >= 70 ? "high" : score >= 40 ? "mid" : "low";
          return `
            <div style="display:flex;align-items:center;gap:var(--space-3);background:var(--bg-surface-raised);border-radius:var(--radius-md);padding:var(--space-2) var(--space-3)">
              <span class="score-chip score-chip--${tone}">${score}%</span>
              <span class="text-xs text-secondary">CV ${m.cv_id} ↔ Offre ${m.job_id}</span>
            </div>`;
        }).join("")
      : `<span class="text-xs text-muted">Aucune correspondance trouvée.</span>`;

    detailEl.innerHTML = `
      <div class="card__header">
        <div class="card__title">${escapeHtml(s.name)}</div>
        <span class="badge badge--${statusVariant}">${statusLabel}</span>
      </div>
      ${s.description ? `<p class="text-sm text-secondary" style="margin-bottom:var(--space-4)">${escapeHtml(s.description)}</p>` : ""}
      <div style="display:flex;gap:var(--space-4);flex-wrap:wrap;margin-bottom:var(--space-4)">
        <span class="text-sm text-muted">${s.cv_count ?? 0} CV</span>
        <span class="text-sm text-muted">${s.job_count ?? 0} offres</span>
        <span class="text-sm text-muted">${s.match_count ?? 0} correspondances</span>
        <span class="text-sm text-muted">Créée le ${new Date(s.created_at).toLocaleString("fr-FR")}</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4);margin-bottom:var(--space-4)">
        <div class="card card--flat">
          <div class="card__title text-sm" style="margin-bottom:var(--space-3)">CV archivés</div>
          <div class="stack" style="gap:var(--space-2)">${cvHtml}</div>
        </div>
        <div class="card card--flat">
          <div class="card__title text-sm" style="margin-bottom:var(--space-3)">Offres archivées</div>
          <div class="stack" style="gap:var(--space-2)">${jobHtml}</div>
        </div>
      </div>
      <div class="card card--flat">
        <div class="card__title text-sm" style="margin-bottom:var(--space-3)">Correspondances archivées</div>
        <div class="stack" style="gap:var(--space-2)">${matchHtml}</div>
      </div>
    `;
  } catch (err) {
    detailEl.innerHTML = `<div class="banner banner--error">${escapeHtml(err.message)}</div>`;
  }
}
