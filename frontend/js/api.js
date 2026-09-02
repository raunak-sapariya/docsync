import { API_BASE } from "./config.js";

const TOKEN_KEY = "docsync_token";
const USER_KEY = "docsync_user";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser() {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function setSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function isLoggedIn() {
  return !!getToken();
}

export function requireAuthOrRedirect() {
  if (!isLoggedIn()) {
    window.location.href = "index.html";
  }
}

async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && auth) {
    clearSession();
    window.location.href = "index.html";
    throw new Error("Session expired -- please log in again");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      /* body wasn't JSON, keep statusText */
    }
    throw new Error(detail);
  }

  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  register: (username, email, password) =>
    request("/auth/register", {
      method: "POST",
      body: { username, email, password },
      auth: false,
    }),
  login: (email, password) =>
    request("/auth/login", {
      method: "POST",
      body: { email, password },
      auth: false,
    }),
  logout: () => request("/auth/logout", { method: "POST" }),
  me: () => request("/auth/me"),

  listDocuments: () => request("/documents"),
  createDocument: (title) =>
    request("/documents", { method: "POST", body: { title } }),
  getDocument: (id) => request(`/documents/${id}`),
  getDocumentContent: (id) => request(`/documents/${id}/content`),
  renameDocument: (id, title) =>
    request(`/documents/${id}`, { method: "PATCH", body: { title } }),
  deleteDocument: (id) => request(`/documents/${id}`, { method: "DELETE" }),
  getActivity: (id) => request(`/documents/${id}/activity`),

  listPermissions: (docId) => request(`/documents/${docId}/permissions`),
  grantPermission: (docId, email, role) =>
    request(`/documents/${docId}/permissions`, {
      method: "POST",
      body: { email, role },
    }),
  revokePermission: (docId, userId) =>
    request(`/documents/${docId}/permissions/${userId}`, { method: "DELETE" }),
};
