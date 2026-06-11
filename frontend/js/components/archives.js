import { safeFetch } from "../api.js";
import { $, setBanner, show, hide, escapeHtml } from "../utils/dom.js";
import { formatDate } from "../utils/format.js";
import { openDeleteConfirm } from "../utils/upload.js";

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

      // Fetch ALL unassigned documents from API (don't rely on potentially-stale cache)
      setBanner(feedback, "Récupération des documents…", "info");
      const [allCvs, allJobs] = await Promise.all([
        safeFetch("/cv-documents?page_size=500"),
        safeFetch("/job-documents?page_size=500"),
      ]);

      const payload = {
        cv_ids:  (allCvs  ?? []).filter((d) => !d.session_id).map((d) => d.id),
        job_ids: (allJobs ?? []).filter((d) => !d.session_id).map((d) => d.id),
      };

      if (payload.cv_ids.length || payload.job_ids.length) {
        await safeFetch(`/sessions/${session.id}/assign`, {
          method: "POST",
          body: JSON.stringify(payload),
          json: true,
        });
      }

      // Refresh matches page so archived docs disappear from it
      window.dispatchEvent(new CustomEvent("load-matches"));

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
      ${s.description ? `<p class="text-sm text-secondary" style="margin-bottom:var(--space-3)">${escapeHtml(s.description)}</p>` : ""}
      <div style="display:flex;gap:var(--space-3);flex-wrap:wrap;align-items:center;margin-bottom:var(--space-4)">
        <span class="text-sm text-muted">${s.cv_count ?? 0} CV</span>
        <span class="text-sm text-muted">${s.job_count ?? 0} offres</span>
        <span class="text-sm text-muted">${s.match_count ?? 0} correspondances</span>
        <span class="text-sm text-muted">Créée le ${new Date(s.created_at).toLocaleString("fr-FR")}</span>
        <div style="margin-left:auto;display:flex;gap:var(--space-2)">
          <button class="btn btn--ghost btn--sm" data-action="unarchive" data-session="${escapeHtml(String(s.id))}">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" style="vertical-align:middle;margin-right:4px"><rect x="1" y="2" width="14" height="3.5" rx="1" stroke="currentColor" stroke-width="1.5"/><path d="M2.5 5.5v8a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-8" stroke="currentColor" stroke-width="1.5"/><path d="M8 8v4M6 10l2-2 2 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>Désarchiver
          </button>
          <button class="btn btn--danger btn--sm" data-action="delete-session" data-session="${escapeHtml(String(s.id))}" data-name="${escapeHtml(s.name)}">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" style="vertical-align:middle;margin-right:4px"><path d="M2 4h12M5 4V2.5A.5.5 0 0 1 5.5 2h5a.5.5 0 0 1 .5.5V4M6 7v5M10 7v5M3 4l1 9.5A.5.5 0 0 0 4.5 14h7a.5.5 0 0 0 .5-.5L13 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>Supprimer
          </button>
        </div>
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

    // Wire action buttons
    detailEl.querySelector("[data-action='unarchive']")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      if (!window.confirm(`Désarchiver "${s.name}" ?\nLes CV et offres redeviendront actifs dans l'espace de travail.`)) return;
      btn.disabled = true;
      try {
        await safeFetch(`/sessions/${sessionId}/unassign`, { method: "POST", json: true });
        window.dispatchEvent(new CustomEvent("load-matches"));
        _loadSessions();
        hide(detailEl);
      } catch (err) {
        detailEl.insertAdjacentHTML("beforeend", `<div class="banner banner--error" style="margin-top:var(--space-3)">${escapeHtml(err.message)}</div>`);
      } finally {
        btn.disabled = false;
      }
    });

    detailEl.querySelector("[data-action='delete-session']")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const confirmed = await openDeleteConfirm([s.name]);
      if (!confirmed) return;
      btn.disabled = true;
      try {
        await safeFetch(`/sessions/${sessionId}`, { method: "DELETE" });
        window.dispatchEvent(new CustomEvent("load-matches"));
        _loadSessions();
        hide(detailEl);
      } catch (err) {
        detailEl.insertAdjacentHTML("beforeend", `<div class="banner banner--error" style="margin-top:var(--space-3)">${escapeHtml(err.message)}</div>`);
      } finally {
        btn.disabled = false;
      }
    });

  } catch (err) {
    detailEl.innerHTML = `<div class="banner banner--error">${escapeHtml(err.message)}</div>`;
  }
}
