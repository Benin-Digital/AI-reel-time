/**
 * Configuration de l'application.
 *
 * En production sur OVH, le serveur nginx injecte window.APP_API_BASE
 * via un bloc `sub_filter` ou un fichier config.runtime.js servi avant main.js.
 * En développement local, on tombe sur le fallback localhost.
 */
export const API_BASE = window.APP_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";
