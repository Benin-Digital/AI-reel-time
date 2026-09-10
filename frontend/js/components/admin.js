import { safeFetch } from "../api.js";
import { $, setBanner, escapeHtml } from "../utils/dom.js";
import { store, persistAuth, setStore } from "../store.js";
import { updateAuthUi } from "../auth.js";

const ADMIN_ROLES = new Set(["admin", "superadmin"]);
const canManage = () => store.authUser && ADMIN_ROLES.has(store.authUser.role);
const isSuperadmin = () => store.authUser?.role === "superadmin";

export function initAdmin() {
  $("#adminCreateUserForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const feedback = $("#adminCreateUserError");
    const btn = $("#adminCreateUserButton");

    setBanner(feedback, "");

    if (!canManage()) {
      setBanner(feedback, "Accès refusé.", "error");
      return;
    }

    if (btn) { btn.disabled = true; btn.textContent = "Création…"; }

    try {
      await safeFetch("/auth/users", {
        method: "POST",
        body: JSON.stringify({
          email:      $("#adminUserEmail")?.value.trim(),
          password:   $("#adminUserPassword")?.value,
          first_name: $("#adminUserFirst")?.value.trim(),
          last_name:  $("#adminUserLast")?.value.trim(),
          role:       $("#adminUserRole")?.value ?? "member",
        }),
        json: true,
      });
      e.target.reset();
      await _loadUsers();
    } catch (err) {
      setBanner(feedback, err.message, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Créer le compte"; }
    }
  });

  // Click delegation on the users list — save button
  $("#adminUsersList")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-user-save]");
    if (!btn) return;
    const userId = btn.dataset.userSave;
    try {
      await _updateUser(userId);
    } catch (err) {
      setBanner($("#adminCreateUserError"), err.message, "error");
    }
  });

  $("#adminSelfUpdateForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("#adminSelfUpdateMsg");
    const btn = $("#adminSelfUpdateButton");
    setBanner(msg, "");

    const currentPassword = $("#selfUpdateCurrentPassword")?.value ?? "";
    const newEmail    = $("#selfUpdateNewEmail")?.value.trim();
    const newPassword = $("#selfUpdateNewPassword")?.value;

    if (!newEmail && !newPassword) {
      setBanner(msg, "Renseignez un nouvel email et/ou un nouveau mot de passe.", "error");
      return;
    }

    if (btn) { btn.disabled = true; btn.textContent = "Mise à jour…"; }

    try {
      const updated = await safeFetch("/auth/me", {
        method: "PATCH",
        body: JSON.stringify({
          current_password: currentPassword,
          new_email:    newEmail || null,
          new_password: newPassword || null,
        }),
        json: true,
      });
      persistAuth(store.authToken, updated);
      setStore({ authUser: updated });
      updateAuthUi();
      setBanner(msg, "Identifiants mis à jour.", "success");
      e.target.reset();
    } catch (err) {
      setBanner(msg, err.message, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Mettre à jour"; }
    }
  });

  window.addEventListener("load-admin", () => {
    if (canManage()) _loadUsers();
    const card = $("#adminSelfCredentialsCard");
    if (card) card.hidden = !isSuperadmin();
  });
}

async function _loadUsers() {
  const list = $("#adminUsersList");
  if (!list) return;

  list.innerHTML = `<div class="skeleton skeleton--card"></div>`;

  try {
    const users = await safeFetch("/auth/users");
    _renderUsers(users);
  } catch (err) {
    if (err.name !== "AuthError") {
      list.innerHTML = `<div class="banner banner--error">${escapeHtml(err.message)}</div>`;
    }
  }
}

function _renderUsers(users) {
  const list = $("#adminUsersList");
  if (!list) return;

  if (!users?.length) {
    list.innerHTML = `<p class="text-sm text-muted">Aucun compte trouvé.</p>`;
    return;
  }

  const me = store.authUser;

  // canEdit: superadmin can edit anyone except other superadmins; admin can only edit members
  const canEdit = (u) =>
    me?.role === "superadmin" ? u.role !== "superadmin" : u.role === "member";

  // canEditRole: only superadmin can change roles, and only for non-superadmin accounts
  const canEditRole = (u) =>
    me?.role === "superadmin" && u.role !== "superadmin";

  list.innerHTML = users
    .map((u) => {
      const name =
        [u.first_name, u.last_name].filter(Boolean).join(" ") || u.email;
      const roleDisabled    = canEditRole(u) ? "" : "disabled";
      const editDisabled    = canEdit(u)     ? "" : "disabled";
      const hideAdminOption = me?.role !== "superadmin" ? "hidden" : "";

      return `
        <article class="card card--flat" style="padding:var(--space-4)">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-4);flex-wrap:wrap">
            <div>
              <div class="font-semibold text-sm">${escapeHtml(name)}</div>
              <div class="text-xs text-muted">${escapeHtml(u.email)}</div>
              <div class="text-xs text-muted">Créé le ${new Date(u.created_at).toLocaleString("fr-FR")}</div>
            </div>
            <div style="display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap">
              <label style="display:flex;flex-direction:column;gap:var(--space-1)">
                <span class="text-xs text-muted">Rôle</span>
                <select data-user-role="${u.id}" style="width:auto" ${roleDisabled}>
                  <option value="member" ${u.role === "member" ? "selected" : ""}>Utilisateur</option>
                  <option value="admin"  ${u.role === "admin"  ? "selected" : ""} ${hideAdminOption}>Admin</option>
                </select>
              </label>
              <label style="display:flex;flex-direction:column;gap:var(--space-1);align-items:center">
                <span class="text-xs text-muted">Actif</span>
                <input type="checkbox"
                  data-user-active="${u.id}"
                  ${u.is_active ? "checked" : ""}
                  ${editDisabled}
                />
              </label>
              <button class="btn btn--ghost btn--sm" data-user-save="${u.id}" ${editDisabled}>
                Enregistrer
              </button>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

async function _updateUser(userId) {
  const roleEl   = $(`[data-user-role="${userId}"]`);
  const activeEl = $(`[data-user-active="${userId}"]`);
  const payload  = {};

  if (roleEl   && !roleEl.disabled)   payload.role      = roleEl.value;
  if (activeEl && !activeEl.disabled) payload.is_active = activeEl.checked;

  if (!Object.keys(payload).length) return;

  await safeFetch(`/auth/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
    json: true,
  });

  await _loadUsers();
}
