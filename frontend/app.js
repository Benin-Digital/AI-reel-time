const apiBaseInput = document.getElementById("apiBase");
const applyApiButton = document.getElementById("applyApi");
const refreshButton = document.getElementById("refreshAll");
const apiStatus = document.getElementById("apiStatus");
const loginButton = document.getElementById("loginButton");
const logoutButton = document.getElementById("logoutButton");
const authStatus = document.getElementById("authStatus");
const authGate = document.getElementById("authGate");
const dashboardShell = document.getElementById("dashboardShell");
const appFooter = document.getElementById("appFooter");
const openLoginModalButton = document.getElementById("openLoginModal");
const openRegisterModalButton = document.getElementById("openRegisterModal");
const adminTab = document.getElementById("tabAdmin");
const adminPanel = document.getElementById("adminPanel");
const adminUsersList = document.getElementById("adminUsersList");
const adminCreateUserForm = document.getElementById("adminCreateUserForm");
const adminUserEmail = document.getElementById("adminUserEmail");
const adminUserPassword = document.getElementById("adminUserPassword");
const adminUserRole = document.getElementById("adminUserRole");
const adminCreateUserError = document.getElementById("adminCreateUserError");
const loginModal = document.getElementById("loginModal");
const loginForm = document.getElementById("loginForm");
const loginTitle = document.getElementById("loginTitle");
const loginEmail = document.getElementById("loginEmail");
const loginPassword = document.getElementById("loginPassword");
const registerPasswordGroup = document.getElementById("registerPasswordGroup");
const registerPasswordConfirm = document.getElementById("registerPasswordConfirm");
const authModeLoginButton = document.getElementById("authModeLogin");
const authModeRegisterButton = document.getElementById("authModeRegister");
const loginError = document.getElementById("loginError");
const explainModal = document.getElementById("explainModal");
const explainContent = document.getElementById("explainContent");
const deleteConfirmModal = document.getElementById("deleteConfirmModal");
const deleteConfirmText = document.getElementById("deleteConfirmText");
const deleteConfirmList = document.getElementById("deleteConfirmList");
const deleteConfirmInput = document.getElementById("deleteConfirmInput");
const deleteConfirmConfirmBtn = document.getElementById("deleteConfirmConfirm");
const deleteConfirmCancelBtn = document.getElementById("deleteConfirmCancel");
const uploadCvZone = document.getElementById("uploadCvZone");
const uploadCvInput = document.getElementById("uploadCvInput");
const uploadCvButton = document.getElementById("uploadCvButton");
const uploadCvStatus = document.getElementById("uploadCvStatus");
const uploadJobZone = document.getElementById("uploadJobZone");
const uploadJobInput = document.getElementById("uploadJobInput");
const uploadJobButton = document.getElementById("uploadJobButton");
const uploadJobStatus = document.getElementById("uploadJobStatus");


const metricUptime = document.getElementById("metricUptime");
const metricEvents = document.getElementById("metricEvents");
const metricExtractions = document.getElementById("metricExtractions");
const metricScores = document.getElementById("metricScores");
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
const deleteCvAll = document.getElementById("deleteCvAll");

const jobQuery = document.getElementById("jobQuery");
const jobStatus = document.getElementById("jobStatus");
const jobPage = document.getElementById("jobPage");
const jobPageSize = document.getElementById("jobPageSize");
const jobPrev = document.getElementById("jobPrev");
const jobNext = document.getElementById("jobNext");
const applyJobFilters = document.getElementById("applyJobFilters");
const deleteJobAll = document.getElementById("deleteJobAll");

const tabs = Array.from(document.querySelectorAll(".workspace-switcher__button"));
const panelViews = Array.from(document.querySelectorAll(".panel-view"));
const documentSelection = { cv: null, job: null };

let apiBase = localStorage.getItem("apiBase") || "";
apiBaseInput.value = apiBase;
const AUTO_REFRESH_MS = 3000;
const AUTO_REFRESH_MAX_MS = 30000;
const AUTO_REFRESH_BACKOFF_FACTOR = 1.8;
const REQUEST_TIMEOUT_MS = 12000;
const MAX_UPLOAD_MB = 20;
const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".txt"];
const DASHBOARD_CACHE_KEY = "aiRealtimeDashboardCache";
let authToken = localStorage.getItem("authToken") || "";
let authUser = JSON.parse(localStorage.getItem("authUser") || "null");
let authMode = "login";
let autoRefreshTimer = null;
let autoRefreshDelayMs = AUTO_REFRESH_MS;
let autoRefreshInFlight = false;
let activePanel = "cv";
let adminUsersCache = [];
let isHydratingDashboard = false;
let pendingDeleteKind = null;
let pendingDeleteFilenames = [];
let pendingDeleteResolve = null;

const ADMIN_ROLES = new Set(["admin", "superadmin"]);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const setApiStatus = (message) => {
  if (!apiStatus) {
    return;
  }
  if (!message) {
    apiStatus.hidden = true;
    apiStatus.textContent = "";
    return;
  }
  apiStatus.hidden = false;
  apiStatus.textContent = message;
};

const openModal = (modal) => {
  if (modal) {
    modal.hidden = false;
  }
};

const closeModal = (modal) => {
  if (modal) {
    modal.hidden = true;
  }
};

const clearAutoRefreshTimer = () => {
  if (autoRefreshTimer) {
    clearTimeout(autoRefreshTimer);
    autoRefreshTimer = null;
  }
};

const readDashboardCache = () => {
  try {
    return JSON.parse(localStorage.getItem(DASHBOARD_CACHE_KEY) || "null");
  } catch (error) {
    return null;
  }
};

const writeDashboardCache = (patch) => {
  const current = readDashboardCache() || {};
  const next = {
    ...current,
    ...patch,
    updatedAt: new Date().toISOString(),
  };
  try {
    localStorage.setItem(DASHBOARD_CACHE_KEY, JSON.stringify(next));
  } catch (error) {
    // Ignore storage quota or privacy mode failures.
  }
};

const hydrateDashboardFromCache = () => {
  const cache = readDashboardCache();
  if (!cache) {
    return;
  }
  isHydratingDashboard = true;
  try {
    if (cache.selectedDocuments) {
      if (cache.selectedDocuments.cv) {
        setSelectedDocument("cv", cache.selectedDocuments.cv);
      }
      if (cache.selectedDocuments.job) {
        setSelectedDocument("job", cache.selectedDocuments.job);
      }
    }

    if (cache.metrics) {
      renderMetrics(cache.metrics);
    }
    if (Array.isArray(cache.recentMatches)) {
      renderMatches(cache.recentMatches, recentMatches);
    }
    if (Array.isArray(cache.cvDocuments)) {
      renderDocuments(cache.cvDocuments, cvList, "cv");
    }
    if (Array.isArray(cache.jobDocuments)) {
      renderDocuments(cache.jobDocuments, jobList, "job");
    }
  } finally {
    isHydratingDashboard = false;
  }
};

const isTransientFetchError = (error) => {
  if (!(error instanceof Error)) {
    return true;
  }
  return (
    error.name === "AbortError" ||
    error.message.includes("Failed to fetch") ||
    error.message.includes("NetworkError") ||
    error.message.includes("fetch")
  );
};

const openDeleteConfirm = (kind, filenames) => new Promise((resolve) => {
  pendingDeleteKind = kind;
  pendingDeleteFilenames = Array.isArray(filenames) ? filenames : [filenames];
  pendingDeleteResolve = resolve;

  if (deleteConfirmText) {
    if (pendingDeleteFilenames.length === 1) {
      deleteConfirmText.textContent = `Confirmez la suppression du fichier : ${pendingDeleteFilenames[0]}`;
    } else {
      deleteConfirmText.textContent = `Confirmer la suppression de ${pendingDeleteFilenames.length} fichiers.`;
    }
  }

  if (deleteConfirmList) {
    const preview = pendingDeleteFilenames.slice(0, 10).map((f) => `<div>${f}</div>`).join("");
    deleteConfirmList.innerHTML = pendingDeleteFilenames.length > 10
      ? `<div>Affichage des ${Math.min(pendingDeleteFilenames.length, 10)} premiers fichiers :</div>${preview}`
      : preview || "";
  }

  if (deleteConfirmInput) {
    deleteConfirmInput.value = "";
    deleteConfirmInput.focus();
  }
  if (deleteConfirmConfirmBtn) {
    deleteConfirmConfirmBtn.disabled = true;
  }

  openModal(deleteConfirmModal);
});

const fetchWithTimeout = async (url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) => {
  const controller = new AbortController();
  const timerId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timerId);
  }
};

const safeFetch = async (path, options = {}) => {
  if (!apiBase) {
    throw new Error("Base API manquante");
  }
  const {
    method = "GET",
    headers = {},
    body = null,
    json = false,
    skipAuth = false,
    retries = 2,
    allowAuthErrors = false,
  } = options;
  const requestHeaders = new Headers(headers);
  if (json) {
    requestHeaders.set("Content-Type", "application/json");
  }
  if (!skipAuth && authToken) {
    requestHeaders.set("Authorization", `Bearer ${authToken}`);
  }

  const url = `${apiBase}${path}`;
  let lastError = null;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await fetchWithTimeout(url, {
        method,
        headers: requestHeaders,
        body,
      });
      if (response.status === 401) {
        if (allowAuthErrors) {
          const message = await response.text();
          throw new Error(message || "Authentification requise");
        }
        authToken = "";
        authUser = null;
        localStorage.removeItem("authToken");
        localStorage.removeItem("authUser");
        updateAuthUi();
        openModal(loginModal);
        const authError = new Error("AUTH_REQUIRED");
        authError.name = "AuthError";
        throw authError;
      }
      if (!response.ok) {
        const message = await response.text();
        throw new Error(`La requête a échoué : ${response.status} ${message}`.trim());
      }
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        return response.json();
      }
      return response.text();
    } catch (error) {
      lastError = error;
      if (error instanceof Error && error.name === "AuthError") {
        throw error;
      }
      if (attempt >= retries) {
        throw error;
      }
      await sleep(400 + attempt * 400);
    }
  }

  throw lastError || new Error("Erreur inconnue");
};

const formatEmpty = (message) => `<div class="item"><p class="meta">${message}</p></div>`;

const clampScore = (value) => Math.max(0, Math.min(100, Math.round(Number(value) || 0)));

const scoreTone = (score) => {
  if (score >= 85) {
    return { className: "tone tone--excellent", label: "Excellent" };
  }
  if (score >= 70) {
    return { className: "tone tone--strong", label: "Fort" };
  }
  if (score >= 50) {
    return { className: "tone tone--medium", label: "Moyen" };
  }
  return { className: "tone tone--weak", label: "À vérifier" };
};

const buildInsightBlocks = (score, keywords) => {
  const normalizedKeywords = (keywords || []).filter(Boolean);
  const whyMatch = [];
  const vigilance = [];

  if (normalizedKeywords.length) {
    whyMatch.push(`Mots-clés communs: ${normalizedKeywords.slice(0, 3).join(", ")}`);
  } else {
    whyMatch.push("Aucun mot-clé commun détecté");
  }

  if (score >= 75) {
    whyMatch.push("Correspondance solide et lisible d'un coup d'œil");
    vigilance.push("Valider les preuves concrètes dans le CV complet");
  } else if (score >= 50) {
    whyMatch.push("Correspondance partielle mais exploitable");
    vigilance.push("Revoir l'expérience et les détails métier");
  } else {
    whyMatch.push("Correspondance faible, utile pour tri secondaire");
    vigilance.push("Ne pas sur-prioriser sans vérification humaine");
  }

  if (!normalizedKeywords.length) {
    vigilance.unshift("Aucun signal lexical fort à l'instant");
  }

  return { whyMatch, vigilance };
};

const renderKeywordChips = (keywords) => {
  const list = (keywords || []).filter(Boolean).slice(0, 6);
  if (!list.length) {
    return '<p class="meta muted">Aucun mot-clé détecté.</p>';
  }

  return `
    <div class="chip-row">
      ${list.map((keyword) => `<span class="chip">${keyword}</span>`).join("")}
    </div>
  `;
};

const renderScoreChip = (score) => {
  const tone = scoreTone(score);
  return `<span class="score-chip ${tone.className}">${score}%</span>`;
};

const canManageUsers = () => Boolean(authUser && ADMIN_ROLES.has(authUser.role));

const updateAuthUi = () => {
  if (!authStatus) {
    return;
  }
  if (authUser) {
    authStatus.textContent = `${authUser.email} (${authUser.role})`;
  } else {
    authStatus.textContent = "Accès restreint";
  }
  if (loginButton) {
    loginButton.hidden = Boolean(authUser);
  }
  if (logoutButton) {
    logoutButton.hidden = !authUser;
  }
  if (authGate) {
    authGate.hidden = Boolean(authUser);
  }
  if (dashboardShell) {
    dashboardShell.hidden = !authUser;
  }
  if (appFooter) {
    appFooter.hidden = !authUser;
  }
  if (adminTab) {
    adminTab.hidden = !canManageUsers();
  }
  if (adminPanel) {
    adminPanel.hidden = !canManageUsers() || activePanel !== "admin";
  }
  // Toggle a body-level background class so the image covers the header too
  if (typeof document !== "undefined") {
    document.body.classList.toggle("auth-background", Boolean(authGate && !authGate.hidden));
  }
};

const setAuthMode = (mode) => {
  authMode = mode === "register" ? "register" : "login";
  if (loginTitle) {
    loginTitle.textContent = authMode === "register" ? "Créer un compte" : "Connexion";
  }
  if (authModeLoginButton) {
    authModeLoginButton.classList.toggle("is-active", authMode === "login");
  }
  if (authModeRegisterButton) {
    authModeRegisterButton.classList.toggle("is-active", authMode === "register");
  }
  if (registerPasswordGroup) {
    registerPasswordGroup.hidden = authMode !== "register";
  }
  if (registerPasswordConfirm) {
    registerPasswordConfirm.required = authMode === "register";
    if (authMode !== "register") {
      registerPasswordConfirm.value = "";
    }
  }
  if (loginPassword) {
    loginPassword.placeholder = authMode === "register" ? "Choisissez un mot de passe" : "Mot de passe";
  }
};

const openAuthModal = (mode = "login") => {
  clearLoginError();
  setAuthMode(mode);
  openModal(loginModal);
};

const clearAdminError = () => {
  if (!adminCreateUserError) {
    return;
  }
  adminCreateUserError.hidden = true;
  adminCreateUserError.textContent = "";
};

const showAdminError = (message) => {
  if (!adminCreateUserError) {
    return;
  }
  adminCreateUserError.hidden = false;
  adminCreateUserError.textContent = message;
};

const syncAdminRoleOptions = () => {
  if (!adminUserRole) {
    return;
  }
  const adminOption = adminUserRole.querySelector('option[value="admin"]');
  if (adminOption) {
    adminOption.hidden = authUser?.role !== "superadmin";
  }
  if (authUser?.role !== "superadmin") {
    adminUserRole.value = "member";
  }
};

const canEditUser = (user) => {
  if (!authUser) {
    return false;
  }
  if (authUser.role === "superadmin") {
    return user.role !== "superadmin";
  }
  return user.role === "member";
};

const canEditUserRole = (user) => authUser?.role === "superadmin" && user.role !== "superadmin";

const canEditUserActive = (user) => canEditUser(user);

const renderAdminUsers = (users) => {
  if (!adminUsersList) {
    return;
  }
  if (!Array.isArray(users) || !users.length) {
    adminUsersList.innerHTML = '<p class="muted">Aucun compte trouvé.</p>';
    return;
  }

  adminUsersList.className = "stack admin-user-list";
  adminUsersList.innerHTML = users
    .map((user) => `
      <article class="admin-user-card">
        <div>
          <strong>${user.email}</strong>
          <div class="admin-user-meta">Créé le ${new Date(user.created_at).toLocaleString("fr-FR")}</div>
        </div>
        <div class="admin-user-controls" data-user-card="${user.id}">
          <label>
            Rôle
            <select data-user-role="${user.id}" ${canEditUserRole(user) ? "" : "disabled"}>
              <option value="member" ${user.role === "member" ? "selected" : ""}>Utilisateur</option>
              <option value="admin" ${user.role === "admin" ? "selected" : ""}>Admin</option>
            </select>
          </label>
          <label class="admin-user-toggle">
            <input type="checkbox" data-user-active="${user.id}" ${user.is_active ? "checked" : ""} ${canEditUserActive(user) ? "" : "disabled"} />
            Actif
          </label>
          <button class="ghost" type="button" data-user-save="${user.id}" ${canEditUser(user) ? "" : "disabled"}>Enregistrer</button>
          <p class="admin-user-meta">Statut: ${user.is_active ? "actif" : "inactif"}</p>
        </div>
      </article>
    `)
    .join("");
};

const loadAdminUsers = async () => {
  if (!canManageUsers()) {
    return;
  }
  const users = await safeFetch("/auth/users");
  adminUsersCache = Array.isArray(users) ? users : [];
  renderAdminUsers(users);
  syncAdminRoleOptions();
};

const createAdminUser = async (email, password, role) => {
  clearAdminError();
  if (!canManageUsers()) {
    throw new Error("Accès admin requis.");
  }
  if (authUser?.role === "admin" && role !== "member") {
    throw new Error("Un admin ne peut créer que des comptes utilisateur.");
  }
  await safeFetch("/auth/users", {
    method: "POST",
    body: JSON.stringify({ email, password, role }),
    json: true,
  });
  await loadAdminUsers();
};

const updateAdminUser = async (userId) => {
  clearAdminError();
  const roleSelect = document.querySelector(`[data-user-role="${userId}"]`);
  const activeToggle = document.querySelector(`[data-user-active="${userId}"]`);
  const current = adminUsersCache.find((user) => String(user.id) === String(userId));

  if (!current) {
    throw new Error("Utilisateur introuvable dans la liste.");
  }

  const payload = {};
  if (roleSelect && canEditUserRole(current)) {
    const nextRole = roleSelect.value;
    if (nextRole !== current.role) {
      payload.role = nextRole;
    }
  }
  if (activeToggle && canEditUserActive(current)) {
    const nextActive = activeToggle.checked;
    if (nextActive !== current.is_active) {
      payload.is_active = nextActive;
    }
  }

  if (!Object.keys(payload).length) {
    return;
  }

  await safeFetch(`/auth/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
    json: true,
  });
  await loadAdminUsers();
};

const showLoginError = (message) => {
  if (!loginError) {
    return;
  }
  loginError.hidden = false;
  loginError.textContent = message;
};

const clearLoginError = () => {
  if (!loginError) {
    return;
  }
  loginError.hidden = true;
  loginError.textContent = "";
};

const setSelectedDocument = (kind, id) => {
  documentSelection[kind] = String(id);
};

const setActivePanel = (panelName) => {
  if (panelName === "admin" && !canManageUsers()) {
    panelName = "cv";
  }
  activePanel = panelName;
  document.body.setAttribute("data-active-panel", panelName);

  tabs.forEach((tab) => {
    const isActive = tab.getAttribute("data-panel") === panelName;
    tab.classList.toggle("is-active", isActive);
    tab.setAttribute("aria-selected", String(isActive));
  });

  panelViews.forEach((panel) => {
    const isActive = panel.getAttribute("data-panel") === panelName;
    panel.classList.toggle("is-active", isActive);
    panel.hidden = !isActive;
    if (isActive) {
      panel.classList.remove("panel-view--enter");
      requestAnimationFrame(() => {
        panel.classList.add("panel-view--enter");
      });
    }
  });
};

const flashActionState = (button, doneLabel) => {
  if (!(button instanceof HTMLElement)) {
    return;
  }
  const defaultLabel = button.getAttribute("data-default-label") || button.textContent || "";
  button.setAttribute("data-default-label", defaultLabel);
  button.textContent = doneLabel;
  button.classList.add("is-applied");

  const timerId = Number(button.getAttribute("data-flash-id") || 0);
  if (timerId) {
    clearTimeout(timerId);
  }

  const nextTimerId = window.setTimeout(() => {
    button.textContent = defaultLabel;
    button.classList.remove("is-applied");
    button.removeAttribute("data-flash-id");
  }, 1200);

  button.setAttribute("data-flash-id", String(nextTimerId));
};

const updatePagerButtons = (prevButton, pageElement) => {
  const currentPage = getPageNumber(pageElement);
  prevButton.disabled = currentPage <= 1;
};

const formatBytes = (bytes) => {
  if (!bytes && bytes !== 0) {
    return "0 B";
  }
  const sizes = ["B", "KB", "MB", "GB"];
  const index = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(1)} ${sizes[index]}`;
};

const pushUploadStatus = (target, message) => {
  if (!target) {
    return;
  }
  const item = document.createElement("div");
  item.className = "upload-status__item";
  item.textContent = message;
  target.prepend(item);
};

const getDocumentConfig = (kind) => {
  if (kind === "cv") {
    return {
      list: cvList,
      details: cvDetails,
      page: cvPage,
      query: cvQuery,
      status: cvStatus,
      statusTarget: uploadCvStatus,
    };
  }

  return {
    list: jobList,
    details: jobDetails,
    page: jobPage,
    query: jobQuery,
    status: jobStatus,
    statusTarget: uploadJobStatus,
  };
};

const getDocumentLabel = (kind) => (kind === "cv" ? "CV" : "offre");

const deleteDocument = async (kind, filename) => {
  await safeFetch("/ingest/delete", {
    method: "POST",
    body: JSON.stringify({ folder: kind, filename }),
    json: true,
  });
};

const collectAllDocuments = async (kind) => {
  const config = getDocumentConfig(kind);
  const filenames = [];
  let page = 1;
  const pageSize = 200;

  while (true) {
    const query = buildParams({
      page,
      page_size: pageSize,
      status: config.status.value,
      query: config.query.value,
    });
    const docs = await safeFetch(`/${kind}-documents${query}`);
    if (!docs.length) {
      break;
    }
    filenames.push(...docs.map((doc) => doc.path));
    if (docs.length < pageSize) {
      break;
    }
    page += 1;
  }

  return filenames;
};

const deleteDocumentsBatch = async (kind, filenames) => {
  if (!filenames.length) {
    return { results: [] };
  }

  return safeFetch("/ingest/delete-batch", {
    method: "POST",
    body: JSON.stringify({ folder: kind, filenames }),
    json: true,
  });
};

const handleDeleteDocument = async (kind, filename) => {
  const label = getDocumentLabel(kind);
  const confirmed = await openDeleteConfirm(kind, [filename]);
  if (!confirmed) {
    return;
  }

  const config = getDocumentConfig(kind);
  try {
    await deleteDocument(kind, filename);
    pushUploadStatus(config.statusTarget, `${filename} - supprimé`);
    documentSelection[kind] = null;
    if (config.details) {
      config.details.innerHTML = "";
      config.details.classList.add("hidden");
    }
    await loadAll();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Erreur inconnue";
    pushUploadStatus(config.statusTarget, `${filename} - ${message}`);
    setApiStatus(message);
  }
};

const handleDeleteAllDocuments = async (kind) => {
  const config = getDocumentConfig(kind);
  const label = getDocumentLabel(kind);
  const filenames = await collectAllDocuments(kind);

  if (!filenames.length) {
    pushUploadStatus(config.statusTarget, `Aucun ${label} à supprimer`);
    return;
  }

  const confirmed = await openDeleteConfirm(kind, filenames);
  if (!confirmed) {
    return;
  }

  try {
    await deleteDocumentsBatch(kind, filenames);
    documentSelection[kind] = null;
    config.details.innerHTML = "";
    config.details.classList.add("hidden");
    if (kind === "cv") {
      updatePageElement(cvPage, 1);
    } else {
      updatePageElement(jobPage, 1);
    }
    pushUploadStatus(config.statusTarget, `Suppression terminée pour ${filenames.length} fichier(s)`);
    await loadAll();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Erreur inconnue";
    pushUploadStatus(config.statusTarget, `${label} - ${message}`);
    setApiStatus(message);
  }
};

const uploadFile = async (kind, file, statusTarget) => {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!SUPPORTED_EXTENSIONS.includes(ext)) {
    pushUploadStatus(statusTarget, `${file.name} - type non supporte`);
    return false;
  }
  const maxBytes = MAX_UPLOAD_MB * 1024 * 1024;
  if (file.size > maxBytes) {
    pushUploadStatus(
      statusTarget,
      `${file.name} - trop volumineux (${formatBytes(file.size)})`,
    );
    return false;
  }

  const form = new FormData();
  form.append("folder", kind);
  form.append("upload", file, file.name);
  form.append("filename", file.name);

  pushUploadStatus(statusTarget, `${file.name} - envoi en cours...`);
  await safeFetch("/ingest", { method: "POST", body: form });
  pushUploadStatus(statusTarget, `${file.name} - ajoute`);
  return true;
};

const handleUploadFiles = async (kind, files, statusTarget) => {
  if (!files || !files.length) {
    return;
  }
  setApiStatus("");
  for (const file of files) {
    try {
      await uploadFile(kind, file, statusTarget);
    } catch (error) {
      const message =
        error instanceof Error && error.name === "AuthError"
          ? "Authentification requise"
          : error instanceof Error
            ? error.message
            : "Erreur inconnue";
      pushUploadStatus(statusTarget, `${file.name} - ${message}`);
    }
  }
  if (kind === "cv") {
    loadCvDocuments();
  } else {
    loadJobDocuments();
  }
};

const initUploadZone = (kind, zone, input, button, statusTarget) => {
  if (!zone || !input || !button) {
    return;
  }
  const openPicker = () => input.click();

  button.addEventListener("click", (event) => {
    event.preventDefault();
    openPicker();
  });

  zone.addEventListener("click", (event) => {
    if (event.target === button) {
      return;
    }
    openPicker();
  });

  input.addEventListener("change", () => {
    handleUploadFiles(kind, Array.from(input.files || []), statusTarget);
    input.value = "";
  });

  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("is-dragging");
  });

  zone.addEventListener("dragleave", () => {
    zone.classList.remove("is-dragging");
  });

  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("is-dragging");
    const files = Array.from(event.dataTransfer?.files || []);
    handleUploadFiles(kind, files, statusTarget);
  });
};

const documentStatusTone = (status) => {
  if (status === "ready") {
    return { className: "doc-status doc-status--ready", label: "Prêt" };
  }
  if (status === "failed") {
    return { className: "doc-status doc-status--failed", label: "Échec" };
  }
  return { className: "doc-status doc-status--pending", label: "En attente" };
};

const renderDetailsAccordion = (title, details, open = false) => `
  <details class="match-details" ${open ? "open" : ""}>
    <summary>
      <span>${title}</span>
      <span class="chevron">⌄</span>
    </summary>
    <div class="match-details-body">${details}</div>
  </details>
`;

const renderInsightPanel = (title, items, variant) => `
  <div class="insight-card insight-card--${variant}">
    <h4>${title}</h4>
    ${items.map((item) => `<p>${item}</p>`).join("")}
  </div>
`;

const renderMatchCard = (match) => {
  const score = clampScore(match.score);
  const tone = scoreTone(score);
  const keywords = (match.common_keywords || []).filter(Boolean).slice(0, 6);
  const insights = buildInsightBlocks(score, keywords);
  const summaryLabel = score >= 75 ? "Candidat recommandé" : score >= 50 ? "Profil à examiner" : "Profil à trier";

  return `
    <article class="match-card ${tone.className}">
      <div class="match-card__top">
        <div>
          <div class="match-card__title">Match #${match.id}</div>
          <div class="match-card__meta">CV ${match.cv_id} • Job ${match.job_id}</div>
        </div>
        <div class="match-card__score">
          ${renderScoreChip(score)}
          <span class="score-label">${tone.label}</span>
        </div>
      </div>

      <div class="match-card__status">
        <span class="status-pill">${summaryLabel}</span>
        <span class="muted">Score IA</span>
      </div>

      <div class="score-bar"><span class="score-bar__fill ${tone.className}" style="width:${score}%"></span></div>

      <div class="match-card__summary-grid">
        ${renderInsightPanel("Pourquoi ce match", insights.whyMatch, "success")}
        ${renderInsightPanel("Points de vigilance", insights.vigilance, "danger")}
      </div>

      ${renderDetailsAccordion(
        "Voir détails",
        `
          <div class="match-card__details-block">
            <h4>Mots-clés</h4>
            ${renderKeywordChips(keywords)}
          </div>
        `,
        score >= 85,
      )}

      <div class="match-card__actions">
        <button class="match-card__button" data-explain="${match.id}">Voir plus</button>
      </div>
    </article>
  `;
};

const renderExplainModal = (data) => {
  if (!explainContent) {
    return;
  }
  const buildList = (items) => {
    if (!items || !items.length) {
      return "<p class=\"muted\">Aucun detail disponible.</p>";
    }
    return `<ul>${items.map((item) => `<li>${item}</li>`).join("")}</ul>`;
  };

  explainContent.innerHTML = `
    <div class="item">
      <div class="item-title">
        <strong>Resume</strong>
        ${renderScoreChip(clampScore(data.score))}
      </div>
      <p>${data.summary}</p>
    </div>
    <div class="item">
      <div class="item-title"><strong>Pourquoi ce match</strong></div>
      ${buildList(data.why_match)}
    </div>
    <div class="item">
      <div class="item-title"><strong>Points de vigilance</strong></div>
      ${buildList(data.vigilance)}
    </div>
    <div class="item">
      <div class="item-title"><strong>Extraits probants</strong></div>
      ${buildList(data.evidence)}
    </div>
  `;
  openModal(explainModal);
};

const loadMatchExplanation = async (matchId) => {
  try {
    const data = await safeFetch(`/matches/${matchId}/explain`);
    renderExplainModal(data);
  } catch (error) {
    const message =
      error instanceof Error && error.name === "AuthError"
        ? "Authentification requise."
        : error instanceof Error
          ? error.message
          : "Erreur inconnue";
    setApiStatus(message);
  }
};

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
  if (metricUptime) {
    metricUptime.textContent = data.uptime_seconds ?? "--";
  }
  if (metricEvents) {
    metricEvents.textContent = data.event_count ?? "--";
  }
  if (metricExtractions) {
    metricExtractions.textContent = data.extraction_count ?? "--";
  }
  if (metricScores) {
    metricScores.textContent = data.score_count ?? "--";
  }
  if (metricWorkerStatus) {
    metricWorkerStatus.textContent = data.worker_alive
      ? `actif${data.worker_last_error ? ` - erreur : ${data.worker_last_error}` : ""}`
      : "arrêté";
  }
  writeDashboardCache({ metrics: data });
};

const renderMatches = (matches, target) => {
  if (!matches.length) {
    target.classList.remove("match-grid");
    target.classList.add("stack");
    target.innerHTML = formatEmpty("Aucun résultat de correspondance pour le moment.");
    if (target === recentMatches) {
      writeDashboardCache({ recentMatches: matches });
    }
    return;
  }

  target.classList.remove("stack");
  target.classList.add("match-grid");
  target.innerHTML = matches.map(renderMatchCard).join("");

  target.querySelectorAll("[data-explain]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const matchId = button.getAttribute("data-explain");
      if (matchId) {
        loadMatchExplanation(matchId);
      }
    });
  });

  if (target === recentMatches) {
    writeDashboardCache({ recentMatches: matches });
  }
};

const renderDocuments = (docs, target, kind) => {
  if (!docs.length) {
    target.innerHTML = formatEmpty(`Aucun document ${kind === "cv" ? "CV" : "offre"} pour le moment.`);
    if (kind === "cv") {
      writeDashboardCache({ cvDocuments: docs });
    } else if (kind === "job") {
      writeDashboardCache({ jobDocuments: docs });
    }
    return;
  }

  if (!documentSelection[kind] || !docs.some((doc) => String(doc.id) === String(documentSelection[kind]))) {
    setSelectedDocument(kind, docs[0].id);
  }

  target.innerHTML = docs
    .map((doc) => {
      const statusTone = documentStatusTone(doc.status);
      const updatedAt = new Date(doc.updated_at).toLocaleString("fr-FR");
      const error = doc.last_error ? `<div class="doc-card__error">${doc.last_error}</div>` : "";
      const detailTarget = kind === "cv" ? "CV" : "offre";
      const isActive = String(doc.id) === String(documentSelection[kind]);
      return `
        <article class="doc-row ${statusTone.className} ${isActive ? "is-active" : ""}" data-doc-row="${doc.id}" data-kind="${kind}">
          <div class="doc-row__main">
            <div class="doc-row__top">
              <div class="doc-row__identity">
                <span class="doc-row__eyebrow">${detailTarget}</span>
                <strong class="doc-row__title">${doc.path}</strong>
              </div>
            </div>
            <div class="doc-row__meta">
              <span>ID ${doc.id}</span>
              <span>Mis à jour le ${updatedAt}</span>
            </div>
            ${error}
          </div>
          <div class="doc-row__actions">
            <button class="ghost doc-card__button" data-doc="${doc.id}" data-kind="${kind}" data-action="matches" title="Ouvre l'onglet Correspondances avec un filtre déjà appliqué">Voir les matches liés</button>
            <button class="ghost danger doc-card__button doc-card__button--danger" data-delete-doc="${doc.path}" data-delete-id="${doc.id}" data-kind="${kind}" title="Supprime ce fichier du serveur">Supprimer</button>
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

      if (action !== "matches") {
        return;
      }

      if (kind === "cv") {
        filterCv.value = id;
        filterJob.value = "";
      } else {
        filterJob.value = id;
        filterCv.value = "";
      }
      updatePageElement(matchesPage, 1);
      setActivePanel("matches");
      loadMatches();
    });
  });

  target.querySelectorAll("button[data-delete-doc]").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const filename = btn.getAttribute("data-delete-doc");
      const kind = btn.getAttribute("data-kind");
      if (!filename || !kind) {
        return;
      }
      await handleDeleteDocument(kind, filename);
    });
  });

  target.querySelectorAll("[data-doc-row]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target instanceof HTMLElement && event.target.closest("button")) {
        return;
      }
      const id = row.getAttribute("data-doc-row");
      if (!id) {
        return;
      }
      setSelectedDocument(kind, id);
      loadDocumentDetails(kind, id);
      renderDocuments(docs, target, kind);
    });
  });

  const selectedDocumentId = documentSelection[kind];
  if (selectedDocumentId && !isHydratingDashboard) {
    loadDocumentDetails(kind, selectedDocumentId);
  }

  if (kind === "cv") {
    writeDashboardCache({ cvDocuments: docs, selectedDocuments: { ...readDashboardCache()?.selectedDocuments, cv: documentSelection[kind] } });
  } else if (kind === "job") {
    writeDashboardCache({ jobDocuments: docs, selectedDocuments: { ...readDashboardCache()?.selectedDocuments, job: documentSelection[kind] } });
  }
};

const renderDocumentDetails = (doc, target) => {
  const extraction = doc.extraction || {};
  const matches = doc.top_matches || [];
  const keywordChips = renderKeywordChips(doc.top_keywords || []);
  const statusTone = documentStatusTone(doc.status);
  const previewText = (extraction.extracted_text || "Aucun texte extrait").slice(0, 1200);

  target.classList.remove("hidden");
  target.innerHTML = `
    <article class="detail-card ${statusTone.className}">
      <div class="detail-card__top">
        <div>
          <strong class="detail-card__title">${doc.path}</strong>
        </div>
      </div>

      <div class="detail-card__stats">
        <div class="detail-stat">
          <span class="detail-stat__label">ID</span>
          <strong>${doc.id}</strong>
        </div>
        <div class="detail-stat">
          <span class="detail-stat__label">Correspondances</span>
          <strong>${doc.match_count}</strong>
        </div>
        <div class="detail-stat">
          <span class="detail-stat__label">Score moyen</span>
          <strong>${doc.average_score !== null && doc.average_score !== undefined ? `${doc.average_score}%` : "n/a"}</strong>
        </div>
      </div>

      <div class="detail-card__meta-row">
        <div class="doc-card__meta">Mis à jour le ${new Date(doc.updated_at).toLocaleString("fr-FR")}</div>
        <div class="doc-card__meta">Méthode d’extraction : ${extraction.extraction_method || "inconnue"}</div>
        <div class="doc-card__meta">Hash du contenu : ${extraction.content_hash || "n/a"}</div>
      </div>

      ${doc.last_error ? `<div class="doc-card__error doc-card__error--large">Erreur : ${doc.last_error}</div>` : ""}

      ${doc.top_keywords && doc.top_keywords.length ? `<div class="detail-card__section"><div class="meta">Mots-clés principaux</div>${keywordChips}</div>` : ""}

      <div class="detail-card__section">
        <div class="meta">Aperçu du texte</div>
        <div class="detail-preview">${previewText}</div>
      </div>

      <div class="section-header"><h2>Meilleures correspondances</h2></div>
      ${matches.length ? "" : "<div class=\"meta\">Aucune correspondance pour ce document.</div>"}
      <div class="detail-matches">
        ${matches
          .map((match) => {
            const score = Math.round(match.score || 0);
            return `
              <article class="detail-match ${scoreTone(score).className}">
                <div class="item-title">
                  <strong>Match #${match.id}</strong>
                  ${renderScoreChip(score)}
                </div>
                <div class="meta">CV ${match.cv_id} • Job ${match.job_id}</div>
                <div class="score-bar"><span class="score-bar__fill ${scoreTone(score).className}" style="width:${score}%"></span></div>
                <div class="match-card__actions">
                  <button class="match-card__button" data-explain="${match.id}">Voir plus</button>
                </div>
              </article>
            `;
          })
          .join("")}
      </div>
    </article>
  `;

  target.querySelectorAll("[data-explain]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const matchId = button.getAttribute("data-explain");
      if (matchId) {
        loadMatchExplanation(matchId);
      }
    });
  });

  // Persist this document detail in the dashboard cache
  try {
    const kind = target === cvDetails ? "cv" : "job";
    const cache = readDashboardCache() || {};
    cache.documentDetails = cache.documentDetails || {};
    cache.documentDetails[kind] = cache.documentDetails[kind] || {};
    cache.documentDetails[kind][String(doc.id)] = doc;
    cache.updatedAt = new Date().toISOString();
    localStorage.setItem(DASHBOARD_CACHE_KEY, JSON.stringify(cache));
  } catch (e) {
    // ignore storage errors
  }
};

const loadDocumentDetails = async (kind, id) => {
  const detailsTarget = kind === "cv" ? cvDetails : jobDetails;
  try {
    const doc = await safeFetch(`/${kind}-documents/${id}/details`);
    renderDocumentDetails(doc, detailsTarget);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Erreur inconnue";
    if (error instanceof Error && error.name === "AuthError") {
      detailsTarget.innerHTML = formatEmpty(message);
      detailsTarget.classList.remove("hidden");
      return;
    }

    // On transient network errors, try to restore last-good details from cache
    if (isTransientFetchError(error)) {
      try {
        const cache = readDashboardCache() || {};
        const details = (cache.documentDetails || {})[kind] || {};
        const cached = details[String(id)];
        if (cached) {
          renderDocumentDetails(cached, detailsTarget);
          return;
        }
      } catch (e) {
        // ignore cache read errors and fallthrough
      }
      // if no cached detail available, do not overwrite existing UI
      return;
    }

    // Non-transient error: show message
    detailsTarget.innerHTML = formatEmpty(message);
    detailsTarget.classList.remove("hidden");
  }
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
  updatePagerButtons(matchesPrev, matchesPage);
};

const loadCvDocuments = async () => {
  const currentPage = getPageNumber(cvPage);
  const query = buildParams({
    page: currentPage,
    page_size: cvPageSize.value,
    status: cvStatus.value,
    query: cvQuery.value,
  });
  const data = await safeFetch(`/cv-documents${query}`);
  if (!data.length && currentPage > 1) {
    updatePageElement(cvPage, currentPage - 1);
    return loadCvDocuments();
  }
  renderDocuments(data, cvList, "cv");
  updatePagerButtons(cvPrev, cvPage);
};

const loadCvDocumentsSafe = async () => {
  try {
    await loadCvDocuments();
  } catch (error) {
    if (error instanceof Error && error.name === "AuthError") {
      throw error;
    }
    if (!isTransientFetchError(error)) {
      console.warn("CV refresh failure:", error);
    }
  }
};

const loadJobDocuments = async () => {
  const currentPage = getPageNumber(jobPage);
  const query = buildParams({
    page: currentPage,
    page_size: jobPageSize.value,
    status: jobStatus.value,
    query: jobQuery.value,
  });
  const data = await safeFetch(`/job-documents${query}`);
  if (!data.length && currentPage > 1) {
    updatePageElement(jobPage, currentPage - 1);
    return loadJobDocuments();
  }
  renderDocuments(data, jobList, "job");
  updatePagerButtons(jobPrev, jobPage);
};

const loadJobDocumentsSafe = async () => {
  try {
    await loadJobDocuments();
  } catch (error) {
    if (error instanceof Error && error.name === "AuthError") {
      throw error;
    }
    if (!isTransientFetchError(error)) {
      console.warn("Job refresh failure:", error);
    }
  }
};

const loadMatchesSafe = async () => {
  try {
    await loadMatches();
  } catch (error) {
    if (error instanceof Error && error.name === "AuthError") {
      throw error;
    }
    if (!isTransientFetchError(error)) {
      console.warn("Match refresh failure:", error);
    }
  }
};

const loadAll = async () => {
  if (!authUser) {
    return false;
  }
  if (!apiBase) {
    setApiStatus("Base API manquante. Renseignez l'URL puis appliquez.");
    return false;
  }
  if (autoRefreshInFlight) {
    return false;
  }
  autoRefreshInFlight = true;
  let hadFailure = false;
  try {
    const metricsPromise = safeFetch("/metrics").then(renderMetrics).catch((error) => {
      if (error instanceof Error && error.name === "AuthError") {
        throw error;
      }
      if (!isTransientFetchError(error)) {
        console.warn("Metrics refresh failure:", error);
      }
    });

    const recentMatchesPromise = safeFetch("/matches?page=1&page_size=6&sort_by=created_at_desc")
      .then((recent) => renderMatches(recent, recentMatches))
      .catch((error) => {
        if (error instanceof Error && error.name === "AuthError") {
          throw error;
        }
        if (!isTransientFetchError(error)) {
          console.warn("Recent matches refresh failure:", error);
        }
      });

    await Promise.all([
      metricsPromise,
      loadCvDocumentsSafe(),
      loadJobDocumentsSafe(),
      loadMatchesSafe(),
      recentMatchesPromise,
    ]);
  } catch (error) {
    const message =
      error instanceof Error && error.name === "AuthError"
        ? "Authentification requise."
        : error instanceof Error
          ? error.message
          : "Erreur inconnue";
    if (error instanceof Error && error.name === "AuthError") {
      setApiStatus(message);
      return true;
    }

    if (isTransientFetchError(error)) {
      console.debug("Transient refresh failure suppressed:", message);
      hadFailure = true;
      return hadFailure;
    }

    console.warn("Refresh failure:", message);
    hadFailure = true;
  } finally {
    autoRefreshInFlight = false;
  }
  return hadFailure;
};

const login = async (email, password) => {
  clearLoginError();
  const payload = { email, password };
  const response = await safeFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
    json: true,
    skipAuth: true,
    allowAuthErrors: true,
  });
  authToken = response.access_token;
  authUser = response.user;
  localStorage.setItem("authToken", authToken);
  localStorage.setItem("authUser", JSON.stringify(authUser));
  updateAuthUi();
  setAuthMode("login");
  closeModal(loginModal);
  hydrateDashboardFromCache();
  await loadAll();
  if (canManageUsers()) {
    await loadAdminUsers();
  }
  startAutoRefresh();
};

const register = async (email, password) => {
  clearLoginError();
  const payload = { email, password };
  const response = await safeFetch("/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
    json: true,
    skipAuth: true,
    allowAuthErrors: true,
  });
  authToken = response.access_token;
  authUser = response.user;
  localStorage.setItem("authToken", authToken);
  localStorage.setItem("authUser", JSON.stringify(authUser));
  updateAuthUi();
  setAuthMode("login");
  closeModal(loginModal);
  hydrateDashboardFromCache();
  await loadAll();
  if (canManageUsers()) {
    await loadAdminUsers();
  }
  startAutoRefresh();
};

const logout = () => {
  authToken = "";
  authUser = null;
  localStorage.removeItem("authToken");
  localStorage.removeItem("authUser");
  clearAutoRefreshTimer();
  autoRefreshDelayMs = AUTO_REFRESH_MS;
  updateAuthUi();
  setApiStatus("");
  openAuthModal("login");
};

const loadAuthUser = async () => {
  if (!authToken) {
    return false;
  }
  try {
    const user = await safeFetch("/auth/me");
    authUser = user;
    localStorage.setItem("authUser", JSON.stringify(authUser));
    updateAuthUi();
    return true;
  } catch (error) {
    authToken = "";
    authUser = null;
    localStorage.removeItem("authToken");
    localStorage.removeItem("authUser");
    updateAuthUi();
    return false;
  }
};

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    const panelName = tab.getAttribute("data-panel");
    if (panelName) {
      if (panelName === "admin" && !canManageUsers()) {
        return;
      }
      setActivePanel(panelName);
      if (panelName === "cv") {
        loadCvDocuments();
      }
      if (panelName === "job") {
        loadJobDocuments();
      }
      if (panelName === "matches") {
        loadMatches();
      }
      if (panelName === "admin") {
        loadAdminUsers();
      }
    }
  });
});

if (loginButton) {
  loginButton.addEventListener("click", () => {
    openAuthModal("login");
  });
}

if (openLoginModalButton) {
  openLoginModalButton.addEventListener("click", () => {
    openAuthModal("login");
  });
}

if (openRegisterModalButton) {
  openRegisterModalButton.addEventListener("click", () => {
    openAuthModal("register");
  });
}

if (logoutButton) {
  logoutButton.addEventListener("click", () => {
    logout();
  });
}

if (authModeLoginButton) {
  authModeLoginButton.addEventListener("click", () => {
    setAuthMode("login");
    clearLoginError();
  });
}

if (authModeRegisterButton) {
  authModeRegisterButton.addEventListener("click", () => {
    setAuthMode("register");
    clearLoginError();
  });
}

if (loginForm) {
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const email = loginEmail.value.trim();
      const password = loginPassword.value;
      if (authMode === "register") {
        if (!registerPasswordConfirm) {
          throw new Error("Le formulaire d'inscription est indisponible.");
        }
        if (password !== registerPasswordConfirm.value) {
          throw new Error("Les mots de passe ne correspondent pas.");
        }
        await register(email, password);
        return;
      }
      await login(email, password);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Erreur inconnue";
      showLoginError(message);
    }
  });
}

document.querySelectorAll("[data-modal-close]").forEach((button) => {
  button.addEventListener("click", () => {
    closeModal(loginModal);
    closeModal(explainModal);
    closeModal(deleteConfirmModal);
    if (pendingDeleteResolve) {
      pendingDeleteResolve(false);
      pendingDeleteResolve = null;
    }
  });
});

if (deleteConfirmInput) {
  deleteConfirmInput.addEventListener("input", () => {
    const ok = deleteConfirmInput.value.trim().toUpperCase() === "SUPPRIMER";
    if (deleteConfirmConfirmBtn) {
      deleteConfirmConfirmBtn.disabled = !ok;
    }
  });
}

if (deleteConfirmConfirmBtn) {
  deleteConfirmConfirmBtn.addEventListener("click", async () => {
    closeModal(deleteConfirmModal);
    const filenames = pendingDeleteFilenames || [];
    const kind = pendingDeleteKind;
    // clear pending before resolution
    pendingDeleteFilenames = [];
    pendingDeleteKind = null;
    if (pendingDeleteResolve) {
      pendingDeleteResolve(true);
      pendingDeleteResolve = null;
    }
  });
}

initUploadZone("cv", uploadCvZone, uploadCvInput, uploadCvButton, uploadCvStatus);
initUploadZone("job", uploadJobZone, uploadJobInput, uploadJobButton, uploadJobStatus);

const startAutoRefresh = () => {
  clearAutoRefreshTimer();

  const scheduleNextRefresh = (delayMs = autoRefreshDelayMs) => {
    clearAutoRefreshTimer();
    autoRefreshTimer = window.setTimeout(async () => {
      const hadFailure = await loadAll();
      if (!authUser) {
        clearAutoRefreshTimer();
        return;
      }
      if (hadFailure) {
        autoRefreshDelayMs = Math.min(
          AUTO_REFRESH_MAX_MS,
          Math.max(AUTO_REFRESH_MS, Math.round(autoRefreshDelayMs * AUTO_REFRESH_BACKOFF_FACTOR)),
        );
      } else {
        autoRefreshDelayMs = AUTO_REFRESH_MS;
      }
      scheduleNextRefresh(autoRefreshDelayMs);
    }, delayMs);
  };

  autoRefreshDelayMs = AUTO_REFRESH_MS;
  scheduleNextRefresh(autoRefreshDelayMs);
};

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
  setApiStatus("");
  if (authUser) {
    autoRefreshDelayMs = AUTO_REFRESH_MS;
    loadAll();
    startAutoRefresh();
  }
});

refreshButton.addEventListener("click", () => {
  if (!authUser) {
    openAuthModal("login");
    return;
  }
  loadAll();
});

applyFilters.addEventListener("click", () => {
  updatePageElement(matchesPage, 1);
  flashActionState(applyFilters, "Filtres appliqués");
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
  flashActionState(clearFilters, "Filtres remis à zéro");
  loadMatches();
});

applyCvFilters.addEventListener("click", () => {
  updatePageElement(cvPage, 1);
  flashActionState(applyCvFilters, "Filtres CV appliqués");
  loadCvDocuments();
});

if (deleteCvAll) {
  deleteCvAll.addEventListener("click", async () => {
    await handleDeleteAllDocuments("cv");
  });
}

applyJobFilters.addEventListener("click", () => {
  updatePageElement(jobPage, 1);
  flashActionState(applyJobFilters, "Filtres offres appliqués");
  loadJobDocuments();
});

if (deleteJobAll) {
  deleteJobAll.addEventListener("click", async () => {
    await handleDeleteAllDocuments("job");
  });
}

if (adminCreateUserForm) {
  adminCreateUserForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await createAdminUser(
        adminUserEmail.value.trim(),
        adminUserPassword.value,
        adminUserRole ? adminUserRole.value : "member",
      );
      adminCreateUserForm.reset();
      syncAdminRoleOptions();
      clearAdminError();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Erreur inconnue";
      showAdminError(message);
    }
  });
}

if (adminUsersList) {
  adminUsersList.addEventListener("click", async (event) => {
    const button = event.target instanceof HTMLElement ? event.target.closest("[data-user-save]") : null;
    if (!(button instanceof HTMLElement)) {
      return;
    }
    const userId = button.getAttribute("data-user-save");
    if (!userId) {
      return;
    }
    try {
      await updateAdminUser(userId);
      clearAdminError();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Erreur inconnue";
      showAdminError(message);
    }
  });
}

const bootstrapApp = async () => {
  setAuthMode("login");
  updateAuthUi();

  const authenticated = await loadAuthUser();
  if (!authenticated) {
    clearAutoRefreshTimer();
    setApiStatus("");
    openAuthModal("login");
    return;
  }

  hydrateDashboardFromCache();
  await loadAll();
  if (canManageUsers()) {
    await loadAdminUsers();
  }
  startAutoRefresh();
  setActivePanel(activePanel);
};

bootstrapApp();
