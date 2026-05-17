const apiBaseInput = document.getElementById("apiBase");
const applyApiButton = document.getElementById("applyApi");
const refreshButton = document.getElementById("refreshAll");

const sections = document.querySelectorAll(".section");
const navButtons = document.querySelectorAll(".nav-btn");

const metricUptime = document.getElementById("metricUptime");
const metricEvents = document.getElementById("metricEvents");
const metricExtractions = document.getElementById("metricExtractions");
const metricScores = document.getElementById("metricScores");

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

const cvQuery = document.getElementById("cvQuery");
const cvStatus = document.getElementById("cvStatus");
const applyCvFilters = document.getElementById("applyCvFilters");

const jobQuery = document.getElementById("jobQuery");
const jobStatus = document.getElementById("jobStatus");
const applyJobFilters = document.getElementById("applyJobFilters");

let apiBase = localStorage.getItem("apiBase") || "";
apiBaseInput.value = apiBase;

const safeFetch = async (path) => {
  const response = await fetch(`${apiBase}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
};

const formatEmpty = (message) => `<div class="item"><p class="meta">${message}</p></div>`;

const renderMetrics = (data) => {
  metricUptime.textContent = data.uptime_seconds ?? "--";
  metricEvents.textContent = data.event_count ?? "--";
  metricExtractions.textContent = data.extraction_count ?? "--";
  metricScores.textContent = data.score_count ?? "--";
};

const renderMatches = (matches, target) => {
  if (!matches.length) {
    target.innerHTML = formatEmpty("No match results yet.");
    return;
  }

  target.innerHTML = matches
    .map((match) => {
      const score = Math.round(match.score || 0);
      const keywords = (match.common_keywords || []).slice(0, 6).join(", ") || "No keywords";
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
    target.innerHTML = formatEmpty(`No ${kind} documents yet.`);
    return;
  }

  target.innerHTML = docs
    .map((doc) => {
      const statusClass = doc.status === "ready" ? "badge" : "badge warn";
      const statusLabel = doc.status || "pending";
      const error = doc.last_error ? `<div class="meta">${doc.last_error}</div>` : "";
      return `
        <article class="item">
          <div class="item-title">
            <strong>${doc.path}</strong>
            <span class="${statusClass}">${statusLabel}</span>
          </div>
          <div class="meta">ID ${doc.id} • Updated ${new Date(doc.updated_at).toLocaleString()}</div>
          ${error}
          <div class="actions">
            <button class="ghost" data-doc="${doc.id}" data-kind="${kind}" data-path="${encodeURIComponent(doc.path)}" data-action="details">View details</button>
            <button class="ghost" data-doc="${doc.id}" data-kind="${kind}" data-action="matches">View matches</button>
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
      <strong>Details for ${doc.path}</strong>
      <span class="badge">${doc.status}</span>
    </div>
    <div class="meta">ID ${doc.id} • Updated ${new Date(doc.updated_at).toLocaleString()}</div>
    ${doc.last_error ? `<div class="meta">Error: ${doc.last_error}</div>` : ""}
    <div class="meta">Extraction method: ${extraction.extraction_method || "unknown"}</div>
    <div class="meta">Content hash: ${extraction.content_hash || "n/a"}</div>
    <div class="meta">Text preview:</div>
    <div class="item" style="background: rgba(239, 242, 240, 0.85); padding: 14px; white-space: pre-wrap; max-height: 180px; overflow: auto;">${(extraction.extracted_text || "No extracted text").slice(0, 1200)}</div>
    <div class="section-header"><h2>Top matches</h2></div>
    ${matches.length ? "" : "<div class=\"meta\">No matches yet for this document.</div>"}
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
    const message = error instanceof Error ? error.message : "Unknown error";
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

const loadMatches = async () => {
  const query = buildParams({
    cv_id: filterCv.value,
    job_id: filterJob.value,
    min_score: minScore.value,
    max_score: maxScore.value,
    sort_by: sortMatches.value,
  });
  const data = await safeFetch(`/matches${query}`);
  renderMatches(data, matchList);
};

const loadCvDocuments = async () => {
  const query = buildParams({
    status: cvStatus.value,
    query: cvQuery.value,
  });
  const data = await safeFetch(`/cv-documents${query}`);
  renderDocuments(data, cvList, "cv");
};

const loadJobDocuments = async () => {
  const query = buildParams({
    status: jobStatus.value,
    query: jobQuery.value,
  });
  const data = await safeFetch(`/job-documents${query}`);
  renderDocuments(data, jobList, "job");
};

const loadAll = async () => {
  try {
    const [metrics, cvDocs, jobDocs, matches] = await Promise.all([
      safeFetch("/metrics"),
      safeFetch("/cv-documents"),
      safeFetch("/job-documents"),
      safeFetch("/matches"),
    ]);
    renderMetrics(metrics);
    renderDocuments(cvDocs, cvList, "cv");
    renderDocuments(jobDocs, jobList, "job");
    renderMatches(matches.slice(0, 6), recentMatches);
    renderMatches(matches, matchList);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    recentMatches.innerHTML = formatEmpty(message);
    cvList.innerHTML = formatEmpty(message);
    jobList.innerHTML = formatEmpty(message);
    matchList.innerHTML = formatEmpty(message);
  }
};

navButtons.forEach((button) => {
  button.addEventListener("click", () => {
    showSection(button.dataset.target);
  });
});

applyApiButton.addEventListener("click", () => {
  apiBase = apiBaseInput.value.trim();
  localStorage.setItem("apiBase", apiBase);
  loadAll();
});

refreshButton.addEventListener("click", () => {
  loadAll();
});

applyFilters.addEventListener("click", () => {
  loadMatches();
});

clearFilters.addEventListener("click", () => {
  filterCv.value = "";
  filterJob.value = "";
  minScore.value = "";
  maxScore.value = "";
  sortMatches.value = "score_desc";
  loadMatches();
});

applyCvFilters.addEventListener("click", () => {
  loadCvDocuments();
});

applyJobFilters.addEventListener("click", () => {
  loadJobDocuments();
});

loadAll();
