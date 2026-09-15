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
import { initFeedbackStats } from "./components/feedback-stats.js";
import { initDeleteConfirm, initGenericConfirm } from "./utils/upload.js";

document.addEventListener("DOMContentLoaded", () => {
  initAuth();
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
  initFeedbackStats();

  onPanelChange((panel) => {
    if (!store.authUser) return;
    if (panel === "dashboard") {
      startAutoRefresh();
      window.dispatchEvent(new CustomEvent("load-dashboard"));
    } else {
      stopAutoRefresh();
    }

    if (panel === "cv-library")  window.dispatchEvent(new CustomEvent("load-cv-library"));
    if (panel === "job-library") window.dispatchEvent(new CustomEvent("load-job-library"));
    if (panel === "matches")     window.dispatchEvent(new CustomEvent("load-matches"));
    if (panel === "archives")    window.dispatchEvent(new CustomEvent("load-archives"));
    if (panel === "admin")          window.dispatchEvent(new CustomEvent("load-admin"));
    if (panel === "feedback-stats") window.dispatchEvent(new CustomEvent("load-feedback-stats"));
  });

  // initRouter() calls navigateTo(store.activePanel) synchronously as its
  // last step, which immediately runs every onPanelChange callback above --
  // it must run AFTER those registrations, or the very first navigation on
  // a fresh page load (there is no earlier one) fires with an empty
  // listener list. Real bug this caused: the dashboard's "Meilleure
  // correspondance active" card only ever loads via the "load-dashboard"
  // event dispatched here, so on every reload it stayed empty until the
  // user clicked the sidebar's own "Tableau de bord" link (a SECOND,
  // later navigation, by which point this callback was registered) --
  // while the other two dashboard cards looked unaffected only because
  // initMetrics() fetches its own data directly, independent of routing.
  initRouter();
});
