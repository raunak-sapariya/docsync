import { api, getUser } from "./api.js";
import { logout } from "./auth.js";

const docList = document.getElementById("doc-list");
const emptyState = document.getElementById("empty-state");
const newDocBtn = document.getElementById("new-doc-btn");
const logoutBtn = document.getElementById("logout-btn");
const userLabel = document.getElementById("user-label");

const shareDialog = document.getElementById("share-dialog");
const shareForm = document.getElementById("share-form");
const shareList = document.getElementById("share-list");
const shareDocTitle = document.getElementById("share-doc-title");
const shareError = document.getElementById("share-error");
let shareDocId = null;

logoutBtn.addEventListener("click", logout);
newDocBtn.addEventListener("click", createDocument);

window.addEventListener("docsync:login", () => {
  const user = getUser();
  userLabel.textContent = user ? user.username : "";
  loadDocuments();
});

async function loadDocuments() {
  docList.innerHTML = "";
  let docs;
  try {
    docs = await api.listDocuments();
  } catch (err) {
    docList.innerHTML = `<p class="error-text">Couldn't load documents: ${escapeHtml(err.message)}</p>`;
    return;
  }

  emptyState.hidden = docs.length > 0;
  for (const doc of docs) {
    docList.appendChild(renderDocCard(doc));
  }
}

function renderDocCard(doc) {
  const card = document.createElement("article");
  card.className = "doc-card";
  card.innerHTML = `
    <div class="doc-card-main">
      <h3 class="doc-title">${escapeHtml(doc.title)}</h3>
      <p class="doc-meta">
        <span class="role-badge role-${doc.my_role}">${doc.my_role}</span>
        <span class="doc-updated">updated ${timeAgo(doc.updated_at)}</span>
      </p>
    </div>
    <div class="doc-card-actions">
      ${doc.my_role === "owner" ? `<button class="icon-btn" data-action="share" title="Share" aria-label="Share"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.6" y1="10.5" x2="15.4" y2="6.5"/><line x1="8.6" y1="13.5" x2="15.4" y2="17.5"/></svg></button>` : ""}
      ${doc.my_role === "owner" ? `<button class="icon-btn icon-btn-danger" data-action="delete" title="Delete" aria-label="Delete"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg></button>` : ""}
    </div>
  `;

  card.querySelector(".doc-card-main").addEventListener("click", () => {
    window.location.href = `editor.html?doc=${doc.id}`;
  });

  const shareBtn = card.querySelector('[data-action="share"]');
  if (shareBtn) {
    shareBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openShareDialog(doc);
    });
  }

  const deleteBtn = card.querySelector('[data-action="delete"]');
  if (deleteBtn) {
    deleteBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete "${doc.title}"? This can't be undone.`)) return;
      try {
        await api.deleteDocument(doc.id);
        loadDocuments();
      } catch (err) {
        alert("Couldn't delete: " + err.message);
      }
    });
  }

  return card;
}

async function createDocument() {
  const title = prompt("Document title", "Untitled document");
  if (title === null) return;
  try {
    const doc = await api.createDocument(title || "Untitled document");
    window.location.href = `editor.html?doc=${doc.id}`;
  } catch (err) {
    alert("Couldn't create document: " + err.message);
  }
}


async function openShareDialog(doc) {
  shareDocId = doc.id;
  shareDocTitle.textContent = doc.title;
  shareError.hidden = true;
  shareForm.reset();
  await refreshShareList();
  shareDialog.showModal();
}

async function refreshShareList() {
  shareList.innerHTML = "<li>Loading...</li>";
  try {
    const perms = await api.listPermissions(shareDocId);
    shareList.innerHTML = "";
    if (perms.length === 0) {
      shareList.innerHTML = "<li class='muted'>Only you have access so far.</li>";
    }
    for (const p of perms) {
      const li = document.createElement("li");
      li.innerHTML = `<span>${escapeHtml(p.email)} <span class="role-badge role-${p.role}">${p.role}</span></span>`;
      const removeBtn = document.createElement("button");
      removeBtn.textContent = "Remove";
      removeBtn.className = "icon-btn";
      removeBtn.addEventListener("click", async () => {
        await api.revokePermission(shareDocId, p.user_id);
        refreshShareList();
      });
      li.appendChild(removeBtn);
      shareList.appendChild(li);
    }
  } catch (err) {
    shareList.innerHTML = `<li class="error-text">${escapeHtml(err.message)}</li>`;
  }
}

shareForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  shareError.hidden = true;
  const email = document.getElementById("share-email").value.trim();
  const role = document.getElementById("share-role").value;
  try {
    await api.grantPermission(shareDocId, email, role);
    document.getElementById("share-email").value = "";
    refreshShareList();
    loadDocuments();
  } catch (err) {
    shareError.textContent = err.message;
    shareError.hidden = false;
  }
});

document.getElementById("close-share-dialog").addEventListener("click", () => shareDialog.close());


function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function timeAgo(isoString) {
  const seconds = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
