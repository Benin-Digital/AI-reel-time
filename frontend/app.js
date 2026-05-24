const apiBaseInput = document.getElementById("apiBase");
const applyApiButton = document.getElementById("applyApi");
const apiStatus = document.getElementById("apiStatus");
const loginButton = document.getElementById("loginButton");
const logoutButton = document.getElementById("logoutButton");
const authStatus = document.getElementById("authStatus");
const authGate = document.getElementById("authGate");
const dashboardShell = document.getElementById("dashboardShell");
const appFooter = document.getElementById("appFooter");
const appLogo = document.getElementById("appLogo");
const openLoginModalButton = document.getElementById("openLoginModal");
const openRegisterModalButton = document.getElementById("openRegisterModal");
const adminTab = document.getElementById("tabAdmin");
const adminPanel = document.getElementById("adminPanel");
const adminUsersList = document.getElementById("adminUsersList");
const adminCreateUserForm = document.getElementById("adminCreateUserForm");
const adminUserEmail = document.getElementById("adminUserEmail");
const adminUserFirst = document.getElementById("adminUserFirst");
const adminUserLast = document.getElementById("adminUserLast");
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
const jobOfferForm = document.getElementById("jobOfferForm");
const jobOfferId = document.getElementById("jobOfferId");
const jobOfferSubmitButton = document.getElementById("jobOfferSubmitButton");
const jobOfferFeedback = document.getElementById("jobOfferFeedback");
const jobOffersQuery = document.getElementById("jobOffersQuery");
const jobOffersStatus = document.getElementById("jobOffersStatus");
const jobOffersPage = document.getElementById("jobOffersPage");
const jobOffersPageSize = document.getElementById("jobOffersPageSize");
const jobOffersPrev = document.getElementById("jobOffersPrev");
const jobOffersNext = document.getElementById("jobOffersNext");
const jobOfferList = document.getElementById("jobOfferList");
const applyJobOffersFilters = document.getElementById("applyJobOffersFilters");
const refreshJobOffers = document.getElementById("refreshJobOffers");


const metricUptime = document.getElementById("metricUptime");
const metricEvents = document.getElementById("metricEvents");
const metricExtractions = document.getElementById("metricExtractions");
const metricScores = document.getElementById("metricScores");
const metricWorkerStatus = document.getElementById("metricWorkerStatus");

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

const tabs = Array.from(document.querySelectorAll(".workspace-switcher__button"));
const panelViews = Array.from(document.querySelectorAll(".panel-view"));
const documentSelection = { cv: null, job: null };
const matchDetailsState = Object.create(null);
const documentPreviewState = {
  cv: { objectUrl: null, previewMode: "text" },
  job: { objectUrl: null, previewMode: "text" },
};

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
let jobOfferListCache = [];
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

const buildDocumentPdfUrl = (kind, id) => {
  if (!apiBase) {
    return "";
  }
  return `${apiBase}/${kind}-documents/${id}/pdf`;
};

const openAuthenticatedHtmlRoute = async (path) => {
  if (!apiBase) {
    throw new Error("Base API manquante");
  }

  const popup = window.open("", "_blank");
  if (!popup) {
    throw new Error("Impossible d’ouvrir la fenêtre d’export");
  }

  const headers = new Headers();
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }

  const response = await fetchWithTimeout(`${apiBase}${path}`, { method: "GET", headers });
  if (response.status === 401) {
    popup.close();
    openModal(loginModal);
    throw new Error("Authentification requise pour accéder à l’export");
  }
  if (!response.ok) {
    popup.close();
    throw new Error(`Impossible d’ouvrir l’export (${response.status})`);
  }

  const html = await response.text();
  popup.document.open();
  popup.document.write(html);
  popup.document.close();
  popup.focus();
  return popup;
};

const openAuthenticatedPdf = async (kind, id) => {
  const pdfUrl = buildDocumentPdfUrl(kind, id);
  if (!pdfUrl) {
    throw new Error("Base API manquante");
  }

  const headers = new Headers();
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }

  const response = await fetchWithTimeout(pdfUrl, { method: "GET", headers });
  if (response.status === 401) {
    openModal(loginModal);
    throw new Error("Authentification requise pour afficher le PDF");
  }
  if (!response.ok) {
    throw new Error(`Impossible de charger le PDF (${response.status})`);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const popup = window.open(objectUrl, "_blank");
  if (!popup) {
    URL.revokeObjectURL(objectUrl);
    throw new Error("Impossible d'ouvrir la fenêtre PDF");
  }

  window.setTimeout(() => {
    URL.revokeObjectURL(objectUrl);
  }, 60000);
};

const clearDocumentPdfUrl = (kind) => {
  const state = documentPreviewState[kind];
  if (state && state.objectUrl) {
    URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = null;
  }
};

const setDocumentPreviewMode = (target, mode) => {
  const nextMode = mode === "pdf" ? "pdf" : "text";
  const kind = target.querySelector("[data-document-kind]")?.getAttribute("data-document-kind");
  const textPanel = target.querySelector('[data-document-preview-panel="text"]');
  const pdfPanel = target.querySelector('[data-document-preview-panel="pdf"]');
  const toggleButton = target.querySelector('[data-document-preview-toggle]');
  if (kind && documentPreviewState[kind]) {
    documentPreviewState[kind].previewMode = nextMode;
  }
  if (textPanel) {
    textPanel.hidden = nextMode !== "text";
  }
  if (pdfPanel) {
    pdfPanel.hidden = nextMode !== "pdf";
  }
  if (toggleButton) {
    toggleButton.textContent = nextMode === "text" ? "Voir le PDF" : "Voir le texte extrait";
    toggleButton.setAttribute("aria-pressed", nextMode === "pdf" ? "true" : "false");
    toggleButton.dataset.previewMode = nextMode;
  }
  target.dataset.previewMode = nextMode;
};

const loadDocumentPdfPreview = async (kind, docId, iframe, loadingNode) => {
  const pdfUrl = buildDocumentPdfUrl(kind, docId);
  if (!pdfUrl || !iframe) {
    return;
  }

  if (iframe.dataset.pdfLoading === "true") {
    return;
  }
  const state = documentPreviewState[kind] || {};
  // If we're already in PDF preview mode and the iframe already has
  // the same object URL loaded, don't reload — this prevents the
  // periodic auto-refresh from reloading the iframe every AUTO_REFRESH_MS.
  if (state.previewMode === "pdf" && state.objectUrl && iframe.src && iframe.src === state.objectUrl) {
    if (iframe.isConnected) {
      iframe.hidden = false;
    }
    if (loadingNode) {
      loadingNode.hidden = true;
    }
    return;
  }

  iframe.dataset.pdfLoading = "true";

  clearDocumentPdfUrl(kind);
  try {
    const headers = new Headers();
    if (authToken) {
      headers.set("Authorization", `Bearer ${authToken}`);
    }
    const response = await fetchWithTimeout(pdfUrl, { method: "GET", headers });
    if (response.status === 401) {
      openModal(loginModal);
      throw new Error("Authentification requise pour afficher le PDF");
    }
    if (!response.ok) {
      throw new Error(`Impossible de charger le PDF (${response.status})`);
    }

    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    documentPreviewState[kind].objectUrl = objectUrl;

    if (!iframe.isConnected) {
      URL.revokeObjectURL(objectUrl);
      if (documentPreviewState[kind].objectUrl === objectUrl) {
        documentPreviewState[kind].objectUrl = null;
      }
      return;
    }

    iframe.src = objectUrl;
    iframe.hidden = false;
    if (loadingNode) {
      loadingNode.hidden = true;
    }
  } catch (error) {
    if (iframe.isConnected) {
      iframe.hidden = true;
    }
    if (loadingNode) {
      loadingNode.textContent = error instanceof Error ? error.message : "Aperçu PDF indisponible";
      loadingNode.hidden = false;
    }
  } finally {
    if (iframe.isConnected) {
      iframe.dataset.pdfLoading = "false";
    }
  }
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
    const displayName = authUser.first_name || authUser.last_name ? `${authUser.first_name || ""} ${authUser.last_name || ""}`.trim() : authUser.email;
    authStatus.textContent = `${displayName} (${authUser.role})`;
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
  document.body.classList.toggle("auth-active", !authUser);
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
          <strong>${user.first_name || user.last_name ? `${user.first_name || ""} ${user.last_name || ""}`.trim() : user.email}</strong>
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

const createAdminUser = async (email, firstName, lastName, password, role) => {
  clearAdminError();
  if (!canManageUsers()) {
    throw new Error("Accès admin requis.");
  }
  if (authUser?.role === "admin" && role !== "member") {
    throw new Error("Un admin ne peut créer que des comptes utilisateur.");
  }
  await safeFetch("/auth/users", {
    method: "POST",
    body: JSON.stringify({ email, password, first_name: firstName, last_name: lastName, role }),
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
  const nextId = String(id);
  if (documentSelection[kind] !== nextId) {
    clearDocumentPdfUrl(kind);
    documentPreviewState[kind].previewMode = "text";
  }
  documentSelection[kind] = nextId;
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

const splitOfferItems = (value) =>
  String(value || "")
    .split(/[\n,;]/)
    .map((item) => item.trim())
    .filter(Boolean);

const parseOptionalInteger = (value) => {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? Math.round(parsed) : null;
};

const setOfferFeedback = (message, tone = "info") => {
  if (!jobOfferFeedback) {
    return;
  }
  jobOfferFeedback.hidden = !message;
  jobOfferFeedback.textContent = message || "";
  jobOfferFeedback.dataset.tone = tone;
};

const buildJobOfferPayloadFromForm = (form) => ({
    title: form.jobOfferTitle.value.trim(),
    meta_keywords: splitOfferItems(form.jobOfferMetaKeywords.value),
    department: form.jobOfferDepartment.value.trim() || null,
    contract_type: form.jobOfferContractType.value,
    company: form.jobOfferCompany.value.trim(),
    category: form.jobOfferCategory.value.trim(),
    job_type: form.jobOfferType.value || null,
    salary_min: parseOptionalInteger(form.jobOfferSalaryMin.value),
    salary_max: parseOptionalInteger(form.jobOfferSalaryMax.value),
    salary_period: form.jobOfferSalaryPeriod.value || null,
    tjm: parseOptionalInteger(form.jobOfferTjm.value),
    languages: splitOfferItems(form.jobOfferLanguages.value),
    location: form.jobOfferLocation.value.trim() || null,
    headcount: parseOptionalInteger(form.jobOfferHeadcount.value),
    publish_start: form.jobOfferStart.value || null,
    publish_end: form.jobOfferEnd.value || null,
    description: form.jobOfferDescription.value.trim(),
    visual_code: form.jobOfferVisualCode.value.trim() || null,
    paragraph: form.jobOfferParagraph.value.trim() || null,
    skills: splitOfferItems(form.jobOfferSkills.value),
    strong_constraints: splitOfferItems(form.jobOfferStrongConstraints.value),
    status: form.jobOfferStatus.value,
  });

const submitStructuredJobOffer = async (form) => {
  const payload = buildJobOfferPayloadFromForm(form);
  if (!payload.title || !payload.company || !payload.category || !payload.contract_type || !payload.description) {
    throw new Error("Merci de remplir les champs obligatoires en français.");
  }

  const offerIdValue = form.jobOfferId?.value?.trim();
  const isEdit = Boolean(offerIdValue);
  const response = await safeFetch(isEdit ? `/job-offers/${offerIdValue}` : "/job-offers", {
    method: isEdit ? "PATCH" : "POST",
    body: JSON.stringify(payload),
    json: true,
  });

  return response;
};

const setJobOfferEditorMode = (offerId = "") => {
  if (jobOfferId) {
    jobOfferId.value = offerId ? String(offerId) : "";
  }
  if (jobOfferSubmitButton) {
    jobOfferSubmitButton.textContent = offerId ? "Mettre à jour l’offre" : "Enregistrer l’offre";
  }
};

const toLocalDatetimeValue = (value) => {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 16);
};

const resetJobOfferForm = () => {
  if (!jobOfferForm) {
    return;
  }
  jobOfferForm.reset();
  const languageField = jobOfferForm.querySelector("[name='jobOfferLanguages']");
  if (languageField) {
    languageField.value = "Français";
  }
  setJobOfferEditorMode("");
};

const fillJobOfferForm = (offer) => {
  if (!jobOfferForm || !offer) {
    return;
  }
  const setValue = (name, value) => {
    const field = jobOfferForm.querySelector(`[name='${name}']`);
    if (!field) {
      return;
    }
    field.value = value ?? "";
  };

  setJobOfferEditorMode(String(offer.id));
  setValue("jobOfferTitle", offer.title);
  setValue("jobOfferCompany", offer.company);
  setValue("jobOfferDepartment", offer.department || "");
  setValue("jobOfferCategory", offer.category);
  setValue("jobOfferContractType", offer.contract_type);
  setValue("jobOfferType", offer.job_type || "");
  setValue("jobOfferSalaryMin", offer.salary_min ?? "");
  setValue("jobOfferSalaryMax", offer.salary_max ?? "");
  setValue("jobOfferSalaryPeriod", offer.salary_period || "");
  setValue("jobOfferTjm", offer.tjm ?? "");
  setValue("jobOfferLanguages", (offer.languages || []).join(", ") || "Français");
  setValue("jobOfferLocation", offer.location || "");
  setValue("jobOfferHeadcount", offer.headcount ?? "");
  setValue("jobOfferStart", toLocalDatetimeValue(offer.publish_start));
  setValue("jobOfferEnd", toLocalDatetimeValue(offer.publish_end));
  setValue("jobOfferMetaKeywords", (offer.meta_keywords || []).join(", "));
  setValue("jobOfferDescription", offer.description || "");
  setValue("jobOfferVisualCode", offer.visual_code || "");
  setValue("jobOfferParagraph", offer.paragraph || "");
  setValue("jobOfferSkills", (offer.skills || []).join(", "));
  setValue("jobOfferStrongConstraints", (offer.strong_constraints || []).join(", "));
  setValue("jobOfferStatus", offer.status || "published");
  setApiStatus("");
  setOfferFeedback(`Offre ${offer.id} chargée dans l’éditeur.`, "info");
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

const renderDetailsAccordion = (title, details, open = false, matchId = "") => `
  <details class="match-details" data-match-details="${matchId}" ${open ? "open" : ""}>
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

const EXPLAIN_VARIANTS = [
  {
    intro: "Lecture synthétique: cette correspondance est portée par des signaux forts et des éléments concrets qui justifient le score.",
    lead: "Ce qui pèse le plus dans l’évaluation",
    focus: "Points à retenir en priorité",
    close: "En pratique, ce profil mérite un examen rapide si vous ciblez un candidat aligné sur le cœur du besoin.",
  },
  {
    intro: "Analyse structurée: le moteur a croisé les mots-clés, la proximité des contenus et les indices de cohérence globale.",
    lead: "Ce qui explique la note obtenue",
    focus: "Éléments à surveiller avant validation",
    close: "En synthèse, la lecture du dossier reste favorable, avec un équilibre entre adéquation et vigilance métier.",
  },
  {
    intro: "Interprétation guidée: la correspondance ressort clairement, avec plusieurs signaux utiles pour décider rapidement.",
    lead: "Signaux les plus déterminants",
    focus: "Ce qui doit rester visible pour le RH",
    close: "Au final, le résultat est exploitable immédiatement et met en avant les critères les plus utiles à la décision.",
  },
];

const pickExplainVariant = () => EXPLAIN_VARIANTS[Math.floor(Math.random() * EXPLAIN_VARIANTS.length)];

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

const renderExplainLoading = () => `
  <div class="explain-loading">
    <div class="explain-loading__spinner" aria-hidden="true"></div>
    <div class="explain-loading__copy">
      <strong>Analyse en cours</strong>
      <p>Le système prépare une explication structurée à partir des données extraites.</p>
    </div>
  </div>
`;

const buildBulletList = (items) =>
  items && items.length ? `<ul class="explain-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "<p class=\"muted\">Aucun détail disponible.</p>";

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
        Boolean(matchDetailsState[String(match.id)]) || score >= 85,
        match.id,
      )}

      <div class="match-card__actions">
        <button class="match-card__button" data-explain="${match.id}">Voir l'explication</button>
      </div>
    </article>
  `;
};

const renderExplainContent = (data) => {
  const score = clampScore(data.score);
  const level = score >= 90 ? "Très élevé" : score >= 70 ? "Élevé" : score >= 45 ? "Moyen" : score >= 20 ? "Faible" : "Très faible";
  const scorePct = Number.isFinite(score) ? `${Math.round(score)}` : "n/a";

  const keywords = (data.common_keywords || data.top_keywords || []).filter(Boolean).slice(0, 12);
  const keywordsText = keywords.length ? escapeHtml(keywords.join(", ")) : "Aucun mot-clé significatif détecté";

  let experience = "Non identifié";
  if (data.experience) {
    experience = `${escapeHtml(String(data.experience))} ans`;
  } else if (data.summary) {
    const m = String(data.summary).match(/(\d{1,3})\s*(?:ans|years)/i);
    if (m) experience = `${m[1]} ans`;
  }

  const synth = escapeHtml(data.summary || "L'évaluation combine similarité lexicale et vectorielle pour produire ce score.");

  const vigilance = (data.vigilance || []).filter(Boolean).slice(0, 6);
  const vigilanceText = vigilance.length ? escapeHtml(vigilance.join("; ")) : "Aucun point de vigilance majeur n’a été identifié à ce stade.";

  const evidence = (data.evidence || []).filter(Boolean).slice(0, 6);
  const evidenceHtml = evidence.length ? evidence.map((e) => `« ${escapeHtml(e)} »`).join("<br/>") : "Aucun extrait représentatif disponible.";

  return `
    <div class="explain-copy">
      <p><strong>Niveau de correspondance :</strong> ${level}</p>

      <p>${escapeHtml( (data.summary && data.summary.length>0) ? data.summary : (level === 'Très élevé' ? 'L’analyse réalisée met en évidence une forte adéquation entre le profil et les critères recherchés.' : 'L’analyse met en évidence une adéquation limitée entre le profil évalué et les exigences du poste.') )}</p>

      <p><strong>Score de compatibilité obtenu :</strong> ${scorePct} %</p>

      <p><strong>Éléments ayant contribué à cette évaluation</strong></p>
      <p>Correspondance significative des mots-clés identifiés : ${keywordsText}.</p>
      <p>Expérience professionnelle détectée : ${escapeHtml(String(experience))}.</p>

      <p><strong>Synthèse de l’analyse</strong></p>
      <p>${synth}</p>

      <p><strong>Points de vigilance</strong></p>
      <p>${vigilanceText}</p>

      <p><strong>Extraits représentatifs relevés</strong></p>
      <p>${evidenceHtml}</p>

      <p><strong>Conclusion</strong></p>
      <p>${level === 'Très élevé' ? 'Dans l’ensemble, l’analyse du dossier est très favorable et met en évidence une excellente adéquation entre le profil évalué et les exigences du poste.' : 'Le dossier reste exploitable pour une première lecture RH mais présente des écarts importants par rapport aux exigences du poste.'}</p>
    </div>
  `;
};

const renderExplainModal = (data) => {
  if (!explainContent) {
    return;
  }
  explainContent.innerHTML = renderExplainContent(data);

  // Add action buttons at the bottom of the modal body (footer area)
  // remove existing footer actions if present
  const existingFooter = explainContent.querySelector(".explain-actions--footer");
  if (existingFooter) existingFooter.remove();

  const footerActions = document.createElement("div");
  footerActions.className = "explain-actions--footer";

  const makeBtn = (label, cls = "ghost") => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = cls + " explain-action-btn";
    b.textContent = label;
    return b;
  };

  const cvBtn = makeBtn("Voir le CV (PDF)");
  const jobBtn = makeBtn("Voir l'offre (PDF)");
  const copyBtn = makeBtn("Copier le texte");
  const dlBtn = makeBtn("Télécharger le rapport");

  footerActions.appendChild(cvBtn);
  footerActions.appendChild(jobBtn);
  footerActions.appendChild(copyBtn);
  footerActions.appendChild(dlBtn);

  explainContent.appendChild(footerActions);

  // Handlers (same behavior as before)
  cvBtn.addEventListener("click", () => {
    const matchId = data.match_id || data.matchId || null;
    if (!matchId) return;
    safeFetch(`/matches/${matchId}`)
      .then((m) => openAuthenticatedPdf("cv", m.cv_id))
      .catch((e) => setApiStatus("Impossible d'ouvrir le PDF CV"));
  });

  jobBtn.addEventListener("click", () => {
    const matchId = data.match_id || data.matchId || null;
    if (!matchId) return;
    safeFetch(`/matches/${matchId}`)
      .then((m) => openAuthenticatedPdf("job", m.job_id))
      .catch((e) => setApiStatus("Impossible d'ouvrir le PDF de l'offre"));
  });

  copyBtn.addEventListener("click", async () => {
    try {
      const textParts = [];
      if (data.summary) textParts.push(`Résumé:\n${data.summary}`);
      if (data.why_match && data.why_match.length) textParts.push(`Pourquoi: \n- ${data.why_match.join("\n- ")}`);
      if (data.vigilance && data.vigilance.length) textParts.push(`Points de vigilance:\n- ${data.vigilance.join("\n- ")}`);
      if (data.evidence && data.evidence.length) textParts.push(`Extraits:\n${data.evidence.join("\n\n")}`);
      const final = textParts.join("\n\n");
      await navigator.clipboard.writeText(final);
      setApiStatus("Texte copié dans le presse-papiers");
    } catch (err) {
      setApiStatus("La copie a échoué");
    }
  });

  dlBtn.addEventListener("click", () => {
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>Rapport d'analyse</title><style>body{font-family:Arial,Helvetica,sans-serif;padding:24px;color:#111}h1{font-size:20px}pre{white-space:pre-wrap}</style></head><body><h1>Rapport d'analyse - Match ${escapeHtml(String(data.match_id || ""))}</h1><h2>Résumé</h2><p>${escapeHtml(data.summary || "")}</p><h2>Pourquoi</h2><pre>${escapeHtml((data.why_match||[]).join("\n- "))}</pre><h2>Points de vigilance</h2><pre>${escapeHtml((data.vigilance||[]).join("\n- "))}</pre><h2>Extraits</h2><pre>${escapeHtml((data.evidence||[]).join("\n\n"))}</pre></body></html>`;
    const w = window.open("", "_blank");
    if (!w) return setApiStatus("Impossible d'ouvrir la fenêtre de téléchargement");
    w.document.open();
    w.document.write(html);
    w.document.close();
    try {
      w.focus();
      w.print();
    } catch (e) {
      // ignore
    }
  });

  openModal(explainModal);
};

const loadMatchExplanation = async (matchId) => {
  if (explainContent) {
    explainContent.innerHTML = renderExplainLoading();
    openModal(explainModal);
  }

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
    if (explainContent) {
      explainContent.innerHTML = `<div class="doc-card__error doc-card__error--large">${message}</div>`;
    }
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
    metricUptime.innerHTML = `
      <span class="uptime-animation" aria-hidden="true">
        <span></span>
        <span></span>
        <span></span>
      </span>
      <span class="uptime-label">En continu</span>
    `;
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
        const panel = target.querySelector(`[data-explanation-panel="${matchId}"]`);
        const isExpanded = button.getAttribute("aria-expanded") === "true";

        if (panel && isExpanded) {
          panel.classList.add("hidden");
          button.setAttribute("aria-expanded", "false");
          button.textContent = "Voir l'explication";
          return;
        }

        if (panel) {
          panel.classList.remove("hidden");
          panel.innerHTML = '<div class="muted">Chargement de l\'explication...</div>';
        }

        button.setAttribute("aria-expanded", "true");
        button.textContent = "Masquer l'explication";

        loadMatchExplanation(matchId)
          .then((data) => {
            if (!panel) {
              return;
            }
            panel.innerHTML = renderExplainContent(data);
          })
          .catch((error) => {
            if (!panel) {
              return;
            }
            const message = error instanceof Error ? error.message : "Erreur inconnue";
            panel.innerHTML = `<div class="doc-card__error doc-card__error--large">${message}</div>`;
          });
      }
    });
  });

  target.querySelectorAll("[data-match-details]").forEach((details) => {
    const matchId = details.getAttribute("data-match-details");
    if (!matchId) {
      return;
    }

    matchDetailsState[matchId] = details.open;

    details.addEventListener("toggle", () => {
      matchDetailsState[matchId] = details.open;
    });
  });
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

const renderDocumentDetails = (doc, target, kind = "cv") => {
  const extraction = doc.extraction || {};
  const matches = doc.top_matches || [];
  const keywordChips = renderKeywordChips(doc.top_keywords || []);
  const statusTone = documentStatusTone(doc.status);
  const previewText = extraction.extracted_text || "Aucun texte extrait";
  const previewLabel = kind === "job" ? "Aperçu de l’offre" : "Aperçu du texte";
  const pdfUrl = buildDocumentPdfUrl(kind, doc.id);
  const hasPdf = typeof doc.path === "string" && doc.path.toLowerCase().endsWith(".pdf");

  target.classList.remove("hidden");
  target.dataset.currentDocumentId = String(doc.id);
  target.innerHTML = `
    <article class="detail-card ${statusTone.className}" data-document-kind="${kind}">
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

      <div class="detail-card__section detail-card__section--preview">
        ${hasPdf ? `
          <div class="detail-preview-toolbar">
            <button type="button" class="detail-preview-toggle" data-document-preview-toggle>
              Voir le PDF
            </button>
          </div>
        ` : ""}

        <div class="detail-preview-stack" data-document-preview-stack>
          <div class="detail-preview-panel" data-document-preview-panel="text">
            <div class="meta">${previewLabel}</div>
            <div class="detail-preview">${previewText}</div>
          </div>

          ${hasPdf && pdfUrl ? `
            <div class="detail-preview-panel" data-document-preview-panel="pdf" hidden>
              <div class="meta">Aperçu PDF</div>
              <div class="pdf-frame">
                <div class="pdf-frame__loading">Chargement du PDF…</div>
                <iframe title="Aperçu PDF du document ${doc.id}" loading="lazy" hidden></iframe>
              </div>
            </div>
          ` : ""}
        </div>
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
                  <button class="match-card__button" data-explain="${match.id}">Voir l'explication</button>
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

  const previewToggle = target.querySelector("[data-document-preview-toggle]");
  if (previewToggle) {
    const previewMode = documentPreviewState[kind]?.previewMode || "text";
    setDocumentPreviewMode(target, previewMode);
    previewToggle.addEventListener("click", async () => {
      const currentMode = target.dataset.previewMode === "pdf" ? "pdf" : "text";
      const nextMode = currentMode === "text" ? "pdf" : "text";
      setDocumentPreviewMode(target, nextMode);

      if (nextMode === "pdf") {
        const iframe = target.querySelector("[data-document-preview-panel=\"pdf\"] iframe");
        const loadingNode = target.querySelector("[data-document-preview-panel=\"pdf\"] .pdf-frame__loading");
        if (iframe && !iframe.src && iframe.dataset.pdfLoading !== "true") {
          await loadDocumentPdfPreview(kind, doc.id, iframe, loadingNode);
        }
      }
    });
  }

  if (hasPdf) {
    const iframe = target.querySelector("[data-document-preview-panel=\"pdf\"] iframe");
    const loadingNode = target.querySelector("[data-document-preview-panel=\"pdf\"] .pdf-frame__loading");
    if (iframe) {
      loadDocumentPdfPreview(kind, doc.id, iframe, loadingNode);
    }
  }

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
  const nextId = String(id);

  if (
    detailsTarget?.dataset.currentDocumentId === nextId &&
    documentPreviewState[kind]?.previewMode === "pdf"
  ) {
    return;
  }

  try {
    const doc = await safeFetch(`/${kind}-documents/${id}/details`);
    renderDocumentDetails(doc, detailsTarget, kind);
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
          renderDocumentDetails(cached, detailsTarget, kind);
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

const formatJobOfferCardMeta = (offer) => {
  const parts = [
    offer.company,
    offer.category,
    offer.department,
    offer.location,
    offer.contract_type,
    offer.status === "published" ? "Publié" : "Brouillon",
  ].filter(Boolean);
  return parts.join(" • ");
};

const renderJobOffers = (offers) => {
  if (!jobOfferList) {
    return;
  }
  if (!Array.isArray(offers) || !offers.length) {
    jobOfferList.innerHTML = formatEmpty("Aucune offre RH trouvée.");
    return;
  }

  jobOfferList.innerHTML = offers
    .map((offer) => {
      const isPublished = offer.status === "published";
      const statusLabel = isPublished ? "Publié" : "Brouillon";
      const skills = Array.isArray(offer.skills) ? offer.skills.slice(0, 4) : [];
      const languages = Array.isArray(offer.languages) && offer.languages.length ? offer.languages.join(", ") : "Français";
      return `
        <article class="card job-offer-item ${isPublished ? "job-offer-item--published" : "job-offer-item--draft"}" data-job-offer-id="${offer.id}">
          <div class="job-offer-item__top">
            <div>
              <strong>${offer.title}</strong>
              <div class="meta">${formatJobOfferCardMeta(offer)}</div>
            </div>
            <span class="tone ${isPublished ? "tone--strong" : "tone--medium"}">${statusLabel}</span>
          </div>
          <div class="job-offer-item__summary">
            <div><span>Langue(s)</span><strong>${languages}</strong></div>
            <div><span>Compétences</span><strong>${skills.length ? skills.join(", ") : "Non renseigné"}</strong></div>
            <div><span>Publication</span><strong>${offer.publish_start ? new Date(offer.publish_start).toLocaleDateString("fr-FR") : "—"} → ${offer.publish_end ? new Date(offer.publish_end).toLocaleDateString("fr-FR") : "—"}</strong></div>
          </div>
          <div class="job-offer-item__actions">
            <button type="button" class="ghost" data-job-offer-edit="${offer.id}">Modifier</button>
            <button type="button" class="ghost" data-job-offer-html="${offer.id}">HTML</button>
            <button type="button" class="ghost" data-job-offer-pdf="${offer.id}">PDF</button>
          </div>
        </article>
      `;
    })
    .join("");

  jobOfferList.querySelectorAll("[data-job-offer-edit]").forEach((button) => {
    button.addEventListener("click", async () => {
      const offerId = button.getAttribute("data-job-offer-edit");
      if (!offerId) {
        return;
      }
      try {
        const offer = await safeFetch(`/job-offers/${offerId}`);
        fillJobOfferForm(offer);
        setActivePanel("job");
        if (jobOfferForm) {
          jobOfferForm.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        loadJobDocuments();
      } catch (error) {
        const message = error instanceof Error ? error.message : "Erreur inconnue";
        setApiStatus(message);
      }
    });
  });

  jobOfferList.querySelectorAll("[data-job-offer-html]").forEach((button) => {
    button.addEventListener("click", async () => {
      const offerId = button.getAttribute("data-job-offer-html");
      if (!offerId) {
        return;
      }
      try {
        await openAuthenticatedHtmlRoute(`/job-offers/${offerId}/html`);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Erreur inconnue";
        setApiStatus(message);
      }
    });
  });

  jobOfferList.querySelectorAll("[data-job-offer-pdf]").forEach((button) => {
    button.addEventListener("click", async () => {
      const offerId = button.getAttribute("data-job-offer-pdf");
      if (!offerId) {
        return;
      }
      try {
        await openAuthenticatedHtmlRoute(`/job-offers/${offerId}/pdf`);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Erreur inconnue";
        setApiStatus(message);
      }
    });
  });
  // Attach click handler to show details in the RH offers detail panel
  jobOfferList.querySelectorAll(".job-offer-item").forEach((item) => {
    item.addEventListener("click", async (ev) => {
      // ignore clicks on action buttons inside the card
      if (ev.target.closest("[data-job-offer-edit], [data-job-offer-html], [data-job-offer-pdf]")) {
        return;
      }
      const offerId = item.getAttribute("data-job-offer-id");
      if (!offerId) return;
      try {
        const offer = await safeFetch(`/job-offers/${offerId}`);
        const detailsTarget = document.getElementById("jobOfferDetails");
        renderJobOfferDetails(offer, detailsTarget);
        // ensure the details panel is visible
        if (detailsTarget) detailsTarget.classList.remove("hidden");
      } catch (error) {
        const message = error instanceof Error ? error.message : "Erreur inconnue";
        setApiStatus(message);
      }
    });
  });
};

const renderJobOfferDetails = (offer, target) => {
  if (!target) return;
  if (!offer) {
    target.innerHTML = '<div class="item"><p class="meta">Aucune offre sélectionnée.</p></div>';
    return;
  }

  const skills = Array.isArray(offer.skills) && offer.skills.length ? offer.skills.join(', ') : '—';
  const languages = Array.isArray(offer.languages) && offer.languages.length ? offer.languages.join(', ') : 'Français';
  const constraints = Array.isArray(offer.strong_constraints) && offer.strong_constraints.length ? offer.strong_constraints.join(', ') : 'Aucune';

  target.innerHTML = `
    <div class="card">
      <div class="section-header compact">
        <h4>${offer.title}</h4>
        <div class="meta">${offer.company || ''} • ${offer.category || ''} • ${offer.location || ''}</div>
      </div>
      <div class="card-body">
        <p><strong>Description</strong></p>
        <p class="muted">${offer.description || '—'}</p>
        <p><strong>Compétences</strong></p>
        <p class="muted">${skills}</p>
        <p><strong>Langues</strong></p>
        <p class="muted">${languages}</p>
        <p><strong>Contraintes fortes</strong></p>
        <p class="muted">${constraints}</p>
        <p><strong>Publication</strong></p>
        <p class="muted">${offer.publish_start ? new Date(offer.publish_start).toLocaleString('fr-FR') : '—'} → ${offer.publish_end ? new Date(offer.publish_end).toLocaleString('fr-FR') : '—'}</p>
      </div>
      <div class="card-actions">
        <button class="ghost" data-job-offer-edit="${offer.id}">Modifier</button>
        <button class="ghost" data-job-offer-html="${offer.id}">Ouvrir HTML</button>
        <button class="ghost" data-job-offer-pdf="${offer.id}">Ouvrir PDF</button>
      </div>
    </div>
  `;

  // wire the inline buttons we added
  const editBtn = target.querySelector('[data-job-offer-edit]');
  if (editBtn) {
    editBtn.addEventListener('click', async () => {
      try {
        fillJobOfferForm(offer);
        setActivePanel('job');
        if (jobOfferForm) jobOfferForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } catch (e) {
        setApiStatus(e instanceof Error ? e.message : 'Erreur');
      }
    });
  }
  const htmlBtn = target.querySelector('[data-job-offer-html]');
  if (htmlBtn) htmlBtn.addEventListener('click', async () => openAuthenticatedHtmlRoute(`/job-offers/${offer.id}/html`));
  const pdfBtn = target.querySelector('[data-job-offer-pdf]');
  if (pdfBtn) pdfBtn.addEventListener('click', async () => openAuthenticatedHtmlRoute(`/job-offers/${offer.id}/pdf`));
};

const loadJobOffers = async () => {
  const currentPage = getPageNumber(jobOffersPage);
  const query = buildParams({
    page: currentPage,
    page_size: jobOffersPageSize?.value || 25,
    status: jobOffersStatus?.value || "",
    query: jobOffersQuery?.value || "",
  });
  const data = await safeFetch(`/job-offers${query}`);
  if (!data.length && currentPage > 1) {
    updatePageElement(jobOffersPage, currentPage - 1);
    return loadJobOffers();
  }
  renderJobOffers(data);
  updatePagerButtons(jobOffersPrev, jobOffersPage);
  if (jobOffersNext) {
    jobOffersNext.disabled = !Array.isArray(data) || data.length < Number(jobOffersPageSize?.value || 25);
  }
};

const loadJobOffersSafe = async () => {
  try {
    await loadJobOffers();
  } catch (error) {
    if (error instanceof Error && error.name === "AuthError") {
      throw error;
    }
    if (!isTransientFetchError(error)) {
      console.warn("Job offer refresh failure:", error);
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

    await Promise.all([
      metricsPromise,
      loadCvDocumentsSafe(),
      loadJobDocumentsSafe(),
      loadJobOffersSafe(),
      loadMatchesSafe(),
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
      if (panelName === "jobOffers") {
        loadJobOffers();
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

if (jobOfferForm) {
  jobOfferForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      setOfferFeedback("");
      const createdOffer = await submitStructuredJobOffer(jobOfferForm);
      const publishedLabel = createdOffer.status === "published" ? "publiée et indexée" : "enregistrée en brouillon";
      setOfferFeedback(`Offre ${publishedLabel}.`, "success");
      resetJobOfferForm();
      await loadAll();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Erreur inconnue";
      setOfferFeedback(message, "error");
      setApiStatus(message);
    }
  });
}

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

if (jobOffersPrev) {
  jobOffersPrev.addEventListener("click", () => {
    const nextPage = getPageNumber(jobOffersPage) - 1;
    if (nextPage >= 1) {
      updatePageElement(jobOffersPage, nextPage);
      loadJobOffers();
    }
  });
}

if (jobOffersNext) {
  jobOffersNext.addEventListener("click", () => {
    updatePageElement(jobOffersPage, getPageNumber(jobOffersPage) + 1);
    loadJobOffers();
  });
}

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

applyFilters.addEventListener("click", () => {
  updatePageElement(matchesPage, 1);
  flashActionState(applyFilters, "Filtres appliqués");
  loadMatches();
});

if (applyJobOffersFilters) {
  applyJobOffersFilters.addEventListener("click", () => {
    updatePageElement(jobOffersPage, 1);
    flashActionState(applyJobOffersFilters, "Filtres appliqués");
    loadJobOffers();
  });
}

if (refreshJobOffers) {
  refreshJobOffers.addEventListener("click", () => {
    flashActionState(refreshJobOffers, "Rafraîchi");
    loadJobOffers();
  });
}

const reloadPage = () => {
  window.location.reload();
};

if (appLogo) {
  appLogo.addEventListener("click", reloadPage);
  appLogo.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      reloadPage();
    }
  });
}

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


applyJobFilters.addEventListener("click", () => {
  updatePageElement(jobPage, 1);
  flashActionState(applyJobFilters, "Filtres offres appliqués");
  loadJobDocuments();
});

// 'Supprimer tout' buttons removed from UI; individual delete actions remain available.

if (adminCreateUserForm) {
  adminCreateUserForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await createAdminUser(
        adminUserEmail.value.trim(),
        adminUserFirst.value.trim(),
        adminUserLast.value.trim(),
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
