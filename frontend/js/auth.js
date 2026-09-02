import { api } from "./api.js";
import { setSession, isLoggedIn, clearSession } from "./api.js";

const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");
const authError = document.getElementById("auth-error");
const authSection = document.getElementById("auth-section");
const appSection = document.getElementById("app-section");

function showError(message) {
  authError.textContent = message;
  authError.hidden = false;
}

function clearError() {
  authError.hidden = true;
  authError.textContent = "";
}

document.getElementById("show-register").addEventListener("click", (e) => {
  e.preventDefault();
  clearError();
  loginForm.hidden = true;
  registerForm.hidden = false;
});

document.getElementById("show-login").addEventListener("click", (e) => {
  e.preventDefault();
  clearError();
  registerForm.hidden = true;
  loginForm.hidden = false;
});

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  try {
    const { access_token, user } = await api.login(email, password);
    setSession(access_token, user);
    enterApp();
  } catch (err) {
    showError(err.message);
  }
});

registerForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();
  const username = document.getElementById("register-username").value.trim();
  const email = document.getElementById("register-email").value.trim();
  const password = document.getElementById("register-password").value;
  if (password.length < 8) {
    showError("Password needs to be at least 8 characters.");
    return;
  }
  try {
    const { access_token, user } = await api.register(username, email, password);
    setSession(access_token, user);
    enterApp();
  } catch (err) {
    showError(err.message);
  }
});

export async function logout() {
  try {
    await api.logout();
  } catch {
    /* even if the network call fails, still clear the local session */
  }
  clearSession();
  authSection.hidden = false;
  appSection.hidden = true;
}

function enterApp() {
  authSection.hidden = true;
  appSection.hidden = false;
  window.dispatchEvent(new CustomEvent("docsync:login"));
}

// Exported rather than run as a bare top-level side effect: this must run
// AFTER dashboard.js has registered its docsync:login listener, which ES
// module evaluation order can't guarantee from inside this file alone (see
// the bootstrap script at the bottom of index.html).
export function initAuth() {
  if (isLoggedIn()) {
    enterApp();
  } else {
    authSection.hidden = false;
    appSection.hidden = true;
  }
}
