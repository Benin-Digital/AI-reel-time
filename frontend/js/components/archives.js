import { safeFetch } from "../api.js";
import { $, setBanner, show, hide, escapeHtml } from "../utils/dom.js";
import { formatDate, scoreTone } from "../utils/format.js";
import { openDeleteConfirm, openConfirm } from "../utils/upload.js";
import { store } from "../store.js";

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

  // Click delegation sur la grille d'icônes : un dossier (classeur) ouvre
  // son contenu en interne (pas de requête réseau, re-rend depuis le cache
  // déjà chargé) ; une archive ouvre son détail ; "‹ Archives" revient à
  // la racine.
  $("#archiveSessionsList")?.addEventListener("click", (e) => {
    const back = e.target.closest("#archiveBackBtn");
    if (back) { _currentGroup = null; _render(); return; }

    const groupTile = e.target.closest("[data-open-group]");
    if (groupTile) { _currentGroup = groupTile.dataset.openGroup; _render(); return; }

    const archiveTile = e.target.closest("[data-open-session]");
    if (archiveTile) _loadDetail(archiveTile.dataset.openSession);
  });

  // Recherche en direct (nom + description, déjà supporté côté API --
  // voir GET /sessions?search=) -- débounce comme le slider de score
  // minimum dans matches.js, pour ne pas requêter à chaque frappe. Une
  // recherche active ramène toujours à la racine : rouvrir le dossier où
  // on se trouvait avant de chercher n'aurait pas de sens.
  let searchDebounce = null;
  $("#archiveSearch")?.addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      _currentGroup = null;
      _loadSessions();
    }, 300);
  });

  window.addEventListener("load-archives", () => _loadSessions());
}

// Derived client-side from the /sessions list this panel already fetches
// -- no extra request, just like the "Correspondances" badge in matches.js.
function _updateSidebarArchivesBadge(sessions) {
  const badge = $("#archivesOpenBadge");
  if (!badge) return;
  const openCount = sessions.filter((s) => s.status !== "closed").length;
  badge.textContent = String(openCount);
  badge.hidden = openCount === 0;
}

// Archives created by someone else only ever appear here at all for
// admin/superadmin (deps.visible_owner_ids on the backend already
// filtered the list by role hierarchy) -- this label exists purely so
// that view doesn't read as "my archives", which is what every role saw
// before this fix regardless of who actually created what.
const _isMine = (s) => s.created_by_user_id == null || s.created_by_user_id === store.authUser?.id;

// Même tracé que .doc-item__icon ailleurs dans l'app, juste agrandi --
// dossiers (classeur) et archives partagent cette forme, seule la couleur
// de fond (.icon-tile__icon--*) les distingue, comme des tags de couleur
// sur des dossiers Finder.
const _folderIconSvg = () =>
  `<svg width="26" height="26" viewBox="0 0 16 16" fill="none"><rect x="1" y="2" width="14" height="3.5" rx="1" stroke="currentColor" stroke-width="1.4"/><path d="M2.5 5.5v8a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-8" stroke="currentColor" stroke-width="1.4"/><path d="M6.5 9h3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`;

function _groupTileHtml(g) {
  const count = g.sessions.length;
  return `
      <button type="button" class="icon-tile" data-open-group="${escapeHtml(g.label)}">
        <span class="icon-tile__icon icon-tile__icon--folder">${_folderIconSvg()}</span>
        <span class="icon-tile__label">${escapeHtml(g.label)}</span>
        <span class="icon-tile__meta">${count} archive${count > 1 ? "s" : ""}</span>
      </button>
    `;
}

function _archiveTileHtml(s) {
  const statusClass = s.status === "closed" ? "icon-tile__icon--closed" : "icon-tile__icon--open";
  const ownerLine = !_isMine(s)
    ? `\n${s.created_by_label || "Propriétaire inconnu"}${s.created_by_role ? ` (${s.created_by_role})` : ""}`
    : "";
  const tooltip =
    `${s.name}\n${s.status === "closed" ? "Fermée" : "Ouverte"} · ${s.cv_count ?? 0} CV · ${s.job_count ?? 0} offres · ${s.match_count ?? 0} matches` +
    `\n${formatDate(s.created_at)}${ownerLine}`;
  return `
      <button type="button" class="icon-tile" data-open-session="${s.id}" title="${escapeHtml(tooltip)}">
        <span class="icon-tile__icon ${statusClass}">${_folderIconSvg()}</span>
        <span class="icon-tile__label">${escapeHtml(s.name)}</span>
        <span class="icon-tile__meta">${s.cv_count ?? 0} CV · ${s.job_count ?? 0} offres</span>
      </button>
    `;
}

function _startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

// Convention FR : la semaine commence lundi.
function _startOfWeek(d) {
  const x = _startOfDay(d);
  const day = x.getDay();
  x.setDate(x.getDate() + (day === 0 ? -6 : 1 - day));
  return x;
}

const _dayDiff = (a, b) => Math.round((a - b) / 86400000);

// Classeur jour / semaine / année -- demande explicite : les archives
// récentes restent repérables une par une (Aujourd'hui/Hier), le reste se
// range par semaine puis, au-delà, par année -- comme un vrai classeur
// papier rangé en dossiers qu'on ouvre un par un (voir _render(), qui
// affiche ces dossiers en grille d'icônes plutôt qu'à plat). Basé sur
// created_at (seule date que l'API expose pour une session, voir
// AnalysisSessionRead).
function _groupSessionsByDate(sessions) {
  const now = new Date();
  const today = _startOfDay(now);
  const thisWeekStart = _startOfWeek(now);
  const lastWeekStart = new Date(thisWeekStart);
  lastWeekStart.setDate(lastWeekStart.getDate() - 7);

  const order = ["Aujourd'hui", "Hier", "Cette semaine", "Semaine dernière"];
  const buckets = new Map(order.map((label) => [label, []]));
  const yearBuckets = new Map();

  for (const s of sessions) {
    const createdDay = _startOfDay(new Date(s.created_at));
    const diff = _dayDiff(today, createdDay);

    let label = null;
    if (diff === 0) label = "Aujourd'hui";
    else if (diff === 1) label = "Hier";
    else if (createdDay >= thisWeekStart) label = "Cette semaine";
    else if (createdDay >= lastWeekStart) label = "Semaine dernière";

    if (label) {
      buckets.get(label).push(s);
    } else {
      const year = createdDay.getFullYear();
      if (!yearBuckets.has(year)) yearBuckets.set(year, []);
      yearBuckets.get(year).push(s);
    }
  }

  const groups = order
    .filter((label) => buckets.get(label).length)
    .map((label) => ({ label, sessions: buckets.get(label) }));

  for (const year of [...yearBuckets.keys()].sort((a, b) => b - a)) {
    groups.push({ label: String(year), sessions: yearBuckets.get(year) });
  }

  return groups;
}

// Pagination cumulative (page_size au maximum autorisé par l'API, 100) --
// nécessaire pour que le classeur groupe un ensemble complet plutôt que la
// première page seulement ; "Charger plus" apparaît uniquement si une page
// pleine laisse supposer qu'il en reste d'autres.
let _sessionsCache = [];
let _sessionsNextPage = 1;
let _hasMoreSessions = false;
// null = racine (grille de dossiers jour/semaine/année) ; sinon le label
// du dossier actuellement ouvert -- navigation 100% cliente, _render() ne
// refait jamais de requête, juste un nouveau découpage de _sessionsCache.
let _currentGroup = null;

async function _loadSessions({ reset = true } = {}) {
  const list = $("#archiveSessionsList");
  if (!list) return;

  const searchValue = $("#archiveSearch")?.value.trim() ?? "";

  if (reset) {
    _sessionsCache = [];
    _sessionsNextPage = 1;
    list.innerHTML = `<div class="skeleton skeleton--card"></div>`;
  }

  try {
    const params = new URLSearchParams({ page: String(_sessionsNextPage), page_size: "100" });
    if (searchValue) params.set("search", searchValue);

    const batch = await safeFetch(`/sessions?${params.toString()}`);
    _sessionsCache = reset ? batch : [..._sessionsCache, ...batch];
    _hasMoreSessions = batch.length === 100;
    _sessionsNextPage += 1;

    // Le badge compte les archives ouvertes toutes confondues -- n'a pas de
    // sens pendant une recherche (ne refléterait que le sous-ensemble
    // filtré), on laisse alors la dernière valeur connue.
    if (!searchValue) _updateSidebarArchivesBadge(_sessionsCache);

    _render();
  } catch (err) {
    if (err.name !== "AuthError") {
      list.innerHTML = `<div class="empty-state"><div class="empty-state__hint text-error">${escapeHtml(err.message)}</div></div>`;
    }
  }
}

// Pure (ne touche jamais au réseau) : relit _sessionsCache/_currentGroup/
// la recherche en cours et redessine la grille d'icônes en conséquence --
// appelée aussi bien après un fetch que lors d'un simple clic sur un
// dossier ou "‹ Archives".
function _render() {
  const list = $("#archiveSessionsList");
  if (!list) return;

  const searchValue = $("#archiveSearch")?.value.trim() ?? "";

  if (!_sessionsCache.length) {
    const hint = searchValue ? "Aucun résultat pour cette recherche." : "Aucune archive créée.";
    list.innerHTML = `<div class="empty-state"><div class="empty-state__hint">${hint}</div></div>`;
    return;
  }

  let bodyHtml;
  // Pendant une recherche, une grille plate (triée par récence, déjà
  // l'ordre renvoyé par l'API) est plus utile que des dossiers à rouvrir
  // un par un -- le classeur ne s'applique qu'en navigation libre.
  if (searchValue) {
    bodyHtml = `<div class="icon-grid">${_sessionsCache.map(_archiveTileHtml).join("")}</div>`;
  } else if (_currentGroup) {
    const group = _groupSessionsByDate(_sessionsCache).find((g) => g.label === _currentGroup);
    if (!group) {
      // Le dossier a disparu (dernière archive qu'il contenait vient
      // d'être supprimée/désarchivée) -- retour silencieux à la racine.
      _currentGroup = null;
      _render();
      return;
    }
    bodyHtml = `
      <div class="icon-browser__path">
        <button type="button" class="icon-browser__back" id="archiveBackBtn">‹ Archives</button>
        <span class="icon-browser__current">${escapeHtml(_currentGroup)}</span>
      </div>
      <div class="icon-grid">${group.sessions.map(_archiveTileHtml).join("")}</div>
    `;
  } else {
    bodyHtml = `<div class="icon-grid">${_groupSessionsByDate(_sessionsCache).map(_groupTileHtml).join("")}</div>`;
  }

  const loadMoreHtml = _hasMoreSessions
    ? `<button class="btn btn--ghost btn--sm" id="archiveLoadMore" type="button" style="margin-top:var(--space-3)">Charger plus d'archives…</button>`
    : "";

  list.innerHTML = bodyHtml + loadMoreHtml;
  $("#archiveLoadMore")?.addEventListener("click", () => _loadSessions({ reset: false }));
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
      ? s.cv_documents.map((d) => `<div class="text-xs text-secondary truncate" title="${escapeHtml(d.path ?? "")}">CV ${d.id} · ${escapeHtml(_basename(d.path))}</div>`).join("")
      : `<span class="text-xs text-muted">Aucun</span>`;

    const jobHtml = s.job_documents?.length
      ? s.job_documents.map((d) => `<div class="text-xs text-secondary truncate" title="${escapeHtml(d.path ?? "")}">Offre ${d.id} · ${escapeHtml(_basename(d.path))}</div>`).join("")
      : `<span class="text-xs text-muted">Aucune</span>`;

    const matchHtml = matches?.length
      ? matches.map((m) => {
          const score = Math.max(0, Math.min(100, Math.round(Number(m.score) || 0)));
          const tone  = scoreTone(score).key;
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
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4);margin-bottom:var(--space-4);min-width:0">
        <div class="card card--flat" style="min-width:0;overflow:hidden">
          <div class="card__title text-sm" style="margin-bottom:var(--space-3)">CV archivés</div>
          <div class="stack" style="gap:var(--space-2)">${cvHtml}</div>
        </div>
        <div class="card card--flat" style="min-width:0;overflow:hidden">
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

      // Avertir si le profil courant a deja une section active : desarchiver
      // mélangerait ces nouveaux CV/offres avec le travail en cours, sans
      // que ce soit forcement voulu -- propose d'archiver d'abord, ou de
      // continuer malgre tout (2026-10-05).
      let hasActiveWork = false;
      try {
        const progress = await safeFetch("/matches/progress");
        hasActiveWork = (progress?.active_cv_count ?? 0) > 0 || (progress?.active_job_count ?? 0) > 0;
      } catch { /* si la verification echoue, on ne bloque pas le desarchivage */ }

      const confirmed = await openConfirm(
        "Désarchiver la session",
        hasActiveWork
          ? `Vous avez déjà des CV/offres actifs dans votre espace de travail. Désarchiver "${s.name}" va s'y ajouter et mélanger les deux. Archivez d'abord votre section active, ou continuez quand même.`
          : `Désarchiver "${s.name}" ? Les CV et offres redeviendront actifs dans l'espace de travail.`,
        hasActiveWork ? "Désarchiver quand même" : "Désarchiver"
      );
      if (!confirmed) return;
      btn.disabled = true;
      try {
        const result = await safeFetch(`/sessions/${sessionId}/unassign`, { method: "POST", json: true });
        window.dispatchEvent(new CustomEvent("load-matches"));
        _loadSessions();
        hide(detailEl);
        if (result?.mode === "copied") {
          setBanner(
            $("#archiveCreateFeedback"),
            `${result.cv_count} CV et ${result.job_count} offre(s) copiés dans votre espace actif -- l'archive "${result.session_name}" reste inchangée pour son propriétaire.`,
            "success"
          );
        }
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
        await safeFetch(`/sessions/${sessionId}?delete_documents=true`, { method: "DELETE" });
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
