import { safeFetch } from "../api.js";
import { $, setBanner, escapeHtml } from "../utils/dom.js";
import { splitItems } from "../utils/docs.js";

export function initPublishJob() {
  const form = $("#jobOfferForm");
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const feedback = $("#jobOfferFeedback");
    const btn = form.querySelector('[type="submit"]');
    setBanner(feedback, "");
    if (btn) { btn.disabled = true; btn.textContent = "Enregistrement…"; }
    try {
      const payload = _buildPayload();
      const result = await safeFetch("/job-offers", {
        method: "POST",
        body: JSON.stringify(payload),
        json: true,
      });
      setBanner(feedback, "Offre publiée avec succès.", "success");
      _renderPreview(result);
    } catch (err) {
      setBanner(feedback, err.message, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Enregistrer l'offre"; }
    }
  });
}

function _buildPayload() {
  return {
    title:              $("#jobOfferTitle")?.value.trim(),
    category:           $("#jobOfferCategory")?.value.trim(),
    contract_type:      $("#jobOfferContractType")?.value.trim(),
    job_type:           $("#jobOfferType")?.value.trim() || null,
    description:        $("#jobOfferDescription")?.value.trim(),
    skills:             splitItems($("#jobOfferSkills")?.value),
    strong_constraints: splitItems($("#jobOfferStrongConstraints")?.value),
    meta_keywords:      splitItems($("#jobOfferMetaKeywords")?.value),
    status:             $("#jobOfferStatus")?.value || "published",
  };
}

function _renderPreview(offer) {
  const target = $("#jobOfferDetails");
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

  const statusVariant = offer.status === "published" ? "success" : "draft";
  const statusLabel = offer.status === "published" ? "Publié" : "Brouillon";

  target.innerHTML = `
    <div class="workspace__detail-body stack" style="gap:var(--space-5)">
      <div>
        <div class="text-lg font-semibold">${escapeHtml(offer.title ?? "")}</div>
        <div class="text-sm text-muted">${escapeHtml(offer.category ?? "")}</div>
        <div style="display:flex;gap:var(--space-2);margin-top:var(--space-2);flex-wrap:wrap">
          ${offer.contract_type ? `<span class="badge badge--primary">${escapeHtml(offer.contract_type)}</span>` : ""}
          ${offer.job_type ? `<span class="badge badge--default">${escapeHtml(offer.job_type)}</span>` : ""}
          <span class="badge badge--${statusVariant}">${statusLabel}</span>
        </div>
      </div>
      ${
        offer.description
          ? `<div>
               <div class="text-xs font-semibold text-muted" style="text-transform:uppercase;letter-spacing:.05em;margin-bottom:var(--space-2)">Description</div>
               <p class="text-sm text-secondary" style="white-space:pre-wrap">${escapeHtml(offer.description)}</p>
             </div>`
          : ""
      }
      ${section("Compétences requises", offer.skills)}
      ${section("Contraintes fortes", offer.strong_constraints)}
      ${
        offer.meta_keywords?.length
          ? `<div>
               <div class="text-xs font-semibold text-muted" style="text-transform:uppercase;letter-spacing:.05em;margin-bottom:var(--space-2)">Mots-clés</div>
               ${chips(offer.meta_keywords)}
             </div>`
          : ""
      }
      ${offer.id ? `<p class="text-xs text-muted">ID : ${offer.id}</p>` : ""}
    </div>
  `;
}
