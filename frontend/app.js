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

const filterCv = document.getElementById("filterCv");
const filterJob = document.getElementById("filterJob");
const applyFilters = document.getElementById("applyFilters");
const clearFilters = document.getElementById("clearFilters");

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
            <button class="ghost" data-doc="${doc.id}" data-kind="${kind}">View matches</button>
          </div>
        </article>
      `;
    })
    .join("");

  target.querySelectorAll("button[data-doc]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-doc");
      if (btn.getAttribute("data-kind") === "cv") {
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

const showSection = (id) => {
  sections.forEach((section) => {
    section.classList.toggle("is-active", section.id === id);
  });
  navButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.target === id);
  });
};

const loadMatches = async () => {
  const params = new URLSearchParams();
  if (filterCv.value) {
    params.set("cv_id", filterCv.value);
  }
  if (filterJob.value) {
    params.set("job_id", filterJob.value);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  const data = await safeFetch(`/matches${query}`);
  renderMatches(data, matchList);
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
  loadMatches();
});

loadAll();
