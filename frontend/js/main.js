import { initAuth } from "./auth.js";
import { initRouter, onPanelChange } from "./router.js";
import { store } from "./store.js";
import { initMetrics, startAutoRefresh, stopAutoRefresh } from "./components/metrics.js";
import { initCvLibrary } from "./components/cv-library.js";
import { initJobLibrary } from "./components/job-library.js";
import { initPublishCv } from "./components/publish-cv.js";
import { initPublishJob } from "./components/publish-job.js";
import { initMatches } from "./components/matches.js";
import { initArchives } from "./components/archives.js";
import { initAdmin } from "./components/admin.js";
import { initDeleteConfirm, initGenericConfirm } from "./utils/upload.js";

document.addEventListener("DOMContentLoaded", () => {
  initAuth();
  initRouter();
  initDeleteConfirm();
  initGenericConfirm();

  initMetrics();
  initCvLibrary();
  initJobLibrary();
  initPublishCv();
  initPublishJob();
  initMatches();
  initArchives();
  initAdmin();

  onPanelChange((panel) => {
    if (!store.authUser) return;
    if (panel === "dashboard") startAutoRefresh();
    else stopAutoRefresh();

    if (panel === "cv-library")  window.dispatchEvent(new CustomEvent("load-cv-library"));
    if (panel === "job-library") window.dispatchEvent(new CustomEvent("load-job-library"));
    if (panel === "matches")     window.dispatchEvent(new CustomEvent("load-matches"));
    if (panel === "archives")    window.dispatchEvent(new CustomEvent("load-archives"));
    if (panel === "admin")       window.dispatchEvent(new CustomEvent("load-admin"));
  });
});
