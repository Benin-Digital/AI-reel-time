import { safeFetch } from "../api.js";
import { $, setBanner, escapeHtml } from "../utils/dom.js";
import { splitItems } from "../utils/docs.js";

export function initPublishCv() {
  const form = $("#cvPublishForm");
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const feedback = $("#cvPublishFeedback");
    const btn = form.querySelector('[type="submit"]');
    setBanner(feedback, "");
    if (btn) { btn.disabled = true; btn.textContent = "Enregistrement…"; }
    try {
      const payload = _buildPayload();
      const result = await safeFetch("/cv-profiles", {
        method: "POST",
        body: JSON.stringify(payload),
        json: true,
      });
      setBanner(feedback, "CV publié avec succès.", "success");
      _renderPreview(result);
    } catch (err) {
      setBanner(feedback, err.message, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Enregistrer le CV"; }
    }
  });
}

function _buildPayload() {
  return {
    full_name:      $("#cvPublishFullName")?.value.trim(),
    headline:       $("#cvPublishHeadline")?.value.trim(),
    summary:        $("#cvPublishSummary")?.value.trim(),
    skills:         splitItems($("#cvPublishSkills")?.value),
    experience:     splitItems($("#cvPublishExperience")?.value),
    education:      splitItems($("#cvPublishEducation")?.value),
    certifications: splitItems($("#cvPublishCertifications")?.value),
    languages:      splitItems($("#cvPublishLanguages")?.value),
    contract_type:  $("#cvPublishContractType")?.value || null,
    location:       $("#cvPublishLocation")?.value.trim() || null,
    status:         $("#cvPublishStatus")?.value || "published",
  };
}

function _renderPreview(profile) {
  const target = $("#cvPublishDetails");
  if (!target) return;

  const section = (label, items) =>
    items?.length
      ? `<div class="stack" style="gap:var(--space-2)">
           <div class="text-xs font-semibold text-muted" style="text-transform:uppercase;letter-spacing:.05em">${label}</div>
           <ul class="stack" style="gap:var(--space-1);padding-left:var(--space-4)">
             ${items.map((i) => `<li class="text-sm text-secondary">${escapeHtml(i)}</li>`).join("")}
           </ul>
         </div>`
      : "";

  const chips = (items) =>
    items?.length
      ? `<div class="chip-row">${items.map((i) => `<span class="chip">${escapeHtml(i)}</span>`).join("")}</div>`
      : "";

  target.innerHTML = `
    <div class="workspace__detail-body stack" style="gap:var(--space-5)">
      <div>
        <div class="text-lg font-semibold">${escapeHtml(profile.full_name ?? "")}</div>
        <div class="text-sm text-muted">${escapeHtml(profile.headline ?? "")}</div>
        <div style="display:flex;gap:var(--space-2);margin-top:var(--space-2);flex-wrap:wrap">
          ${profile.contract_type ? `<span class="badge badge--primary">${escapeHtml(profile.contract_type)}</span>` : ""}
          ${profile.location ? `<span class="badge badge--default">${escapeHtml(profile.location)}</span>` : ""}
          <span class="badge badge--${profile.status === "published" ? "success" : "draft"}">
            ${profile.status === "published" ? "Publié" : "Brouillon"}
          </span>
        </div>
      </div>
      ${profile.summary ? `<p class="text-sm text-secondary">${escapeHtml(profile.summary)}</p>` : ""}
      ${section("Compétences", profile.skills)}
      ${section("Expérience", profile.experience)}
      ${section("Formation", profile.education)}
      ${section("Certifications", profile.certifications)}
      ${
        profile.languages?.length
          ? `<div>
               <div class="text-xs font-semibold text-muted" style="text-transform:uppercase;letter-spacing:.05em;margin-bottom:var(--space-2)">Langues</div>
               ${chips(profile.languages)}
             </div>`
          : ""
      }
      ${profile.id ? `<p class="text-xs text-muted">ID : ${profile.id}</p>` : ""}
    </div>
  `;
}
