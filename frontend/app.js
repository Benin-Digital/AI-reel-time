const apiBaseInput = document.getElementById("apiBase");
const applyApiButton = document.getElementById("applyApi");
const refreshButton = document.getElementById("refreshAll");

const sections = document.querySelectorAll(".section");
const navButtons = document.querySelectorAll(".nav-btn");

const metricUptime = document.getElementById("metricUptime");
const metricEvents = document.getElementById("metricEvents");
const metricExtractions = document.getElementById("metricExtractions");
const metricScores = document.getElementById("metricScores");
const metricQueueHealth = document.getElementById("metricQueueHealth");
const metricWorkerStatus = document.getElementById("metricWorkerStatus");

const recentMatches = document.getElementById("recentMatches");
const cvList = document.getElementById("cvList");
const jobList = document.getElementById("jobList");
const matchList = document.getElementById("matchList");
const cvDetails = document.getElementById("cvDetails");
const jobDetails = document.getElementById("jobDetails");

const filterCv = document.getElementById("filterCv");
const filterJob = document.getElementById("filterJob");
const minScore = document.getElementById("minScore");
const maxScore = document.getElementById("maxScore");
const sortMatches = document.getElementById("sortMatches");
const applyFilters = document.getElementById("applyFilters");
const clearFilters = document.getElementById("clearFilters");
const matchSearch = document.getElementById("matchSearch");
const matchesPage = document.getElementById("matchesPage");
const matchesPageSize = document.getElementById("matchPageSize");
const matchesPrev = document.getElementById("matchesPrev");
const matchesNext = document.getElementById("matchesNext");

const cvQuery = document.getElementById("cvQuery");
const cvStatus = document.getElementById("cvStatus");
const cvPage = document.getElementById("cvPage");
const cvPageSize = document.getElementById("cvPageSize");
const cvPrev = document.getElementById("cvPrev");
const cvNext = document.getElementById("cvNext");
const applyCvFilters = document.getElementById("applyCvFilters");

const jobQuery = document.getElementById("jobQuery");
const jobStatus = document.getElementById("jobStatus");
const jobPage = document.getElementById("jobPage");
const jobPageSize = document.getElementById("jobPageSize");
const jobPrev = document.getElementById("jobPrev");
const jobNext = document.getElementById("jobNext");
const applyJobFilters = document.getElementById("applyJobFilters");

let apiBase = localStorage.getItem("apiBase") || "";
apiBaseInput.value = apiBase;
const AUTO_REFRESH_MS = 3000;
let autoRefreshTimer = null;
let autoRefreshInFlight = false;

const safeFetch = async (path) => {
  const response = await fetch(`${apiBase}${path}`);
  if (!response.ok) {
    throw new Error(`La requête a échoué : ${response.status}`);
  }
  return response.json();
};

const formatEmpty = (message) => `<div class="item"><p class="meta">${message}</p></div>`;

const statusLabel = (status) => {
  if (status === "ready") {
    return "Prêt";
  }
  if (status === "failed") {
    return "Échec";
  }
  if (status === "pending") {
    return "En attente";
  }
  return status || "En attente";
};

const renderMetrics = (data) => {
  metricUptime.textContent = data.uptime_seconds ?? "--";
  metricEvents.textContent = data.event_count ?? "--";
  metricExtractions.textContent = data.extraction_count ?? "--";
  metricScores.textContent = data.score_count ?? "--";
  metricQueueHealth.textContent = data.redis_available
    ? `en ligne (${data.redis_queue_length} en file, ${data.memory_queue_length} en mémoire)`
    : "hors ligne";
  metricWorkerStatus.textContent = data.worker_alive
    ? `actif${data.worker_last_error ? ` - erreur : ${data.worker_last_error}` : ""}`
    : "arrêté";
};

const renderMatches = (matches, target) => {
  if (!matches.length) {
    target.innerHTML = formatEmpty("Aucun résultat de correspondance pour le moment.");
    return;
  }

  target.innerHTML = matches
    .map((match) => {
      const score = Math.round(match.score || 0);
      const keywords = (match.common_keywords || []).slice(0, 6).join(", ") || "Aucun mot-clé";
      return `
        <article class="item">
          <div class="item-title">
            <strong>Match #${match.id}</strong>
            <span class="badge">${score}%</span>
          </div>
          <div class="meta">CV ${match.cv_id} • Job ${match.job_id}</div>
          <div class="score-bar"><span style="width:${score}%"></span></div>
          <div class="meta">${keywords}</div>
        </article>
      `;
    })
    .join("");
};

const renderDocuments = (docs, target, kind) => {
  if (!docs.length) {
    target.innerHTML = formatEmpty(`Aucun document ${kind === "cv" ? "CV" : "offre"} pour le moment.`);
    return;
  }

  target.innerHTML = docs
    .map((doc) => {
      const statusClass = doc.status === "ready" ? "badge" : "badge warn";
      const error = doc.last_error ? `<div class="meta">${doc.last_error}</div>` : "";
      return `
        <article class="item">
          <div class="item-title">
            <strong>${doc.path}</strong>
            <span class="${statusClass}">${statusLabel(doc.status)}</span>
          </div>
          <div class="meta">ID ${doc.id} • Mis à jour le ${new Date(doc.updated_at).toLocaleString("fr-FR")}</div>
          ${error}
          <div class="actions">
            <button class="ghost" data-doc="${doc.id}" data-kind="${kind}" data-path="${encodeURIComponent(doc.path)}" data-action="details">Voir les détails</button>
            <button class="ghost" data-doc="${doc.id}" data-kind="${kind}" data-action="matches">Voir les correspondances</button>
          </div>
        </article>
      `;
    })
    .join("");

  target.querySelectorAll("button[data-doc]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-doc");
      const kind = btn.getAttribute("data-kind");
      const action = btn.getAttribute("data-action");

      if (action === "details") {
        loadDocumentDetails(kind, id);
        return;
      }

      if (kind === "cv") {
        filterCv.value = id;
        filterJob.value = "";
      } else {
        filterJob.value = id;
        filterCv.value = "";
      }
      showSection("matches");
      loadMatches();
    });
  });
};

const renderDocumentDetails = (doc, target) => {
  const extraction = doc.extraction || {};
  const matches = doc.top_matches || [];

  target.classList.remove("hidden");
  target.innerHTML = `
    <div class="item-title">
      <strong>Détails pour ${doc.path}</strong>
      <span class="badge">${statusLabel(doc.status)}</span>
    </div>
    <div class="meta">ID ${doc.id} • Mis à jour le ${new Date(doc.updated_at).toLocaleString("fr-FR")}</div>
    ${doc.last_error ? `<div class="meta">Erreur : ${doc.last_error}</div>` : ""}
    <div class="meta">Correspondances : ${doc.match_count}</div>
    ${doc.average_score !== null && doc.average_score !== undefined ? `<div class="meta">Score moyen : ${doc.average_score}%</div>` : ""}
    ${doc.top_keywords && doc.top_keywords.length ? `<div class="meta">Mots-clés principaux : ${doc.top_keywords.slice(0, 10).join(", ")}</div>` : ""}
    <div class="meta">Méthode d’extraction : ${extraction.extraction_method || "inconnue"}</div>
    <div class="meta">Hash du contenu : ${extraction.content_hash || "n/a"}</div>
    <div class="meta">Aperçu du texte :</div>
    <div class="item" style="background: rgba(239, 242, 240, 0.85); padding: 14px; white-space: pre-wrap; max-height: 180px; overflow: auto;">${(extraction.extracted_text || "Aucun texte extrait").slice(0, 1200)}</div>
    <div class="section-header"><h2>Meilleures correspondances</h2></div>
    ${matches.length ? "" : "<div class=\"meta\">Aucune correspondance pour ce document.</div>"}
    ${matches
      .map((match) => {
        const score = Math.round(match.score || 0);
        return `
          <article class="item">
            <div class="item-title">
              <strong>Match #${match.id}</strong>
              <span class="badge">${score}%</span>
            </div>
            <div class="meta">CV ${match.cv_id} • Job ${match.job_id}</div>
            <div class="score-bar"><span style="width:${score}%"></span></div>
          </article>
        `;
      })
      .join("")}
  `;
};

const loadDocumentDetails = async (kind, id) => {
  const detailsTarget = kind === "cv" ? cvDetails : jobDetails;
  try {
    const doc = await safeFetch(`/${kind}-documents/${id}/details`);
    renderDocumentDetails(doc, detailsTarget);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Erreur inconnue";
    detailsTarget.innerHTML = formatEmpty(message);
    detailsTarget.classList.remove("hidden");
  }
};

const showSection = (id) => {
  sections.forEach((section) => {
    section.classList.toggle("is-active", section.id === id);
  });
  navButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.target === id);
  });
};

const buildParams = (params) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, value);
    }
  });
  return search.toString() ? `?${search.toString()}` : "";
};

const updatePageElement = (element, value) => {
  element.textContent = String(Math.max(1, value));
};

const getPageNumber = (element) => Math.max(1, Number(element.textContent || 1));

const loadMatches = async () => {
  const query = buildParams({
    page: getPageNumber(matchesPage),
    page_size: matchesPageSize.value,
    cv_id: filterCv.value,
    job_id: filterJob.value,
    min_score: minScore.value,
    max_score: maxScore.value,
    sort_by: sortMatches.value,
    search: matchSearch.value,
  });
  const data = await safeFetch(`/matches${query}`);
  renderMatches(data, matchList);
};

const loadCvDocuments = async () => {
  const query = buildParams({
    page: getPageNumber(cvPage),
    page_size: cvPageSize.value,
    status: cvStatus.value,
    query: cvQuery.value,
  });
  const data = await safeFetch(`/cv-documents${query}`);
  renderDocuments(data, cvList, "cv");
};

const loadJobDocuments = async () => {
  const query = buildParams({
    page: getPageNumber(jobPage),
    page_size: jobPageSize.value,
    status: jobStatus.value,
    query: jobQuery.value,
  });
  const data = await safeFetch(`/job-documents${query}`);
  renderDocuments(data, jobList, "job");
};

const loadAll = async () => {
  if (autoRefreshInFlight) {
    return;
  }
  autoRefreshInFlight = true;
  try {
    const metrics = await safeFetch("/metrics");
    renderMetrics(metrics);
    await Promise.all([loadCvDocuments(), loadJobDocuments(), loadMatches()]);
    const recent = await safeFetch("/matches?page=1&page_size=6&sort_by=created_at_desc");
    renderMatches(recent, recentMatches);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Erreur inconnue";
    recentMatches.innerHTML = formatEmpty(message);
    cvList.innerHTML = formatEmpty(message);
    jobList.innerHTML = formatEmpty(message);
    matchList.innerHTML = formatEmpty(message);
  } finally {
    autoRefreshInFlight = false;
  }
};

const startAutoRefresh = () => {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
  }
  autoRefreshTimer = setInterval(() => {
    loadAll();
  }, AUTO_REFRESH_MS);
};

navButtons.forEach((button) => {
  button.addEventListener("click", () => {
    showSection(button.dataset.target);
  });
});

cvPrev.addEventListener("click", () => {
  const nextPage = getPageNumber(cvPage) - 1;
  if (nextPage >= 1) {
    updatePageElement(cvPage, nextPage);
    loadCvDocuments();
  }
});

cvNext.addEventListener("click", () => {
  updatePageElement(cvPage, getPageNumber(cvPage) + 1);
  loadCvDocuments();
});

jobPrev.addEventListener("click", () => {
  const nextPage = getPageNumber(jobPage) - 1;
  if (nextPage >= 1) {
    updatePageElement(jobPage, nextPage);
    loadJobDocuments();
  }
});

jobNext.addEventListener("click", () => {
  updatePageElement(jobPage, getPageNumber(jobPage) + 1);
  loadJobDocuments();
});

matchesPrev.addEventListener("click", () => {
  const nextPage = getPageNumber(matchesPage) - 1;
  if (nextPage >= 1) {
    updatePageElement(matchesPage, nextPage);
    loadMatches();
  }
});

matchesNext.addEventListener("click", () => {
  updatePageElement(matchesPage, getPageNumber(matchesPage) + 1);
  loadMatches();
});

applyApiButton.addEventListener("click", () => {
  apiBase = apiBaseInput.value.trim();
  localStorage.setItem("apiBase", apiBase);
  loadAll();
  startAutoRefresh();
});

refreshButton.addEventListener("click", () => {
  loadAll();
});

applyFilters.addEventListener("click", () => {
  updatePageElement(matchesPage, 1);
  loadMatches();
});

clearFilters.addEventListener("click", () => {
  filterCv.value = "";
  filterJob.value = "";
  minScore.value = "";
  maxScore.value = "";
  matchSearch.value = "";
  sortMatches.value = "score_desc";
  updatePageElement(matchesPage, 1);
  loadMatches();
});

applyCvFilters.addEventListener("click", () => {
  updatePageElement(cvPage, 1);
  loadCvDocuments();
});

applyJobFilters.addEventListener("click", () => {
  updatePageElement(jobPage, 1);
  loadJobDocuments();
});

loadAll();
startAutoRefresh();
