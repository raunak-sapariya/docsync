import { getToken, getUser, requireAuthOrRedirect, api } from "./api.js";
import { WS_BASE } from "./config.js";
import * as Y from "yjs";
import { WebsocketProvider } from "y-websocket";
import { QuillBinding } from "y-quill";

requireAuthOrRedirect();

const Quill = window.Quill;
const QuillCursors = window.QuillCursors;
Quill.register("modules/cursors", QuillCursors);

const params = new URLSearchParams(window.location.search);
const docId = params.get("doc");
if (!docId) {
  window.location.href = "index.html";
}

const titleInput = document.getElementById("doc-title-input");
const saveStatus = document.getElementById("save-status");
const presenceBar = document.getElementById("presence-bar");
const activityBtn = document.getElementById("activity-btn");
const activityPanel = document.getElementById("activity-panel");
const activityList = document.getElementById("activity-list");
const roleBadge = document.getElementById("role-badge");

const CURSOR_COLORS = ["#C77D3A", "#2E8B7C", "#A65B8C", "#7A8B3F", "#5A6FB8", "#B85C5C"];
function colorForUser(userId) {
  let hash = 0;
  for (let i = 0; i < userId.length; i++) hash = (hash * 31 + userId.charCodeAt(i)) >>> 0;
  return CURSOR_COLORS[hash % CURSOR_COLORS.length];
}

function base64ToBytes(b64) {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

async function init() {
  let docMeta;
  try {
    docMeta = await api.getDocument(docId);
  } catch (err) {
    alert("Couldn't open this document: " + err.message);
    window.location.href = "index.html";
    return;
  }

  document.title = `${docMeta.title} - Docsync`;
  titleInput.value = docMeta.title;
  const canEdit = docMeta.my_role === "owner" || docMeta.my_role === "editor";
  titleInput.disabled = !canEdit;
  roleBadge.textContent = docMeta.my_role;
  roleBadge.className = `role-badge role-${docMeta.my_role}`;

  const ydoc = new Y.Doc();
  const ytext = ydoc.getText("content");

  // Fast initial paint from the last durable snapshot, before the socket
  // finishes connecting. Safe on an empty Y.Doc: this replays the same
  // operations (same client ids/clocks) the snapshot was made of, so the
  // sync handshake below won't duplicate anything -- it'll just recognize
  // we already have them.
  try {
    const content = await api.getDocumentContent(docId);
    if (content.content_b64) {
      Y.applyUpdate(ydoc, base64ToBytes(content.content_b64));
    }
  } catch {
    // the WebSocket sync below still delivers current content
  }

  const token = getToken();
  const provider = new WebsocketProvider(`${WS_BASE}/ws`, docId, ydoc, {
    params: { token },
  });

  const quill = new Quill("#editor", {
    theme: "snow",
    readOnly: !canEdit,
    placeholder: canEdit ? "Start writing..." : "",
    modules: {
      toolbar: canEdit
        ? [
            ["bold", "italic", "underline", "strike"],
            ["blockquote", "code-block"],
            [{ header: 1 }, { header: 2 }],
            [{ list: "ordered" }, { list: "bullet" }],
            ["clean"],
          ]
        : false,
      cursors: true,
    },
  });

  new QuillBinding(ytext, quill, provider.awareness);

  const me = getUser();
  provider.awareness.setLocalStateField("user", {
    name: me.username,
    color: colorForUser(me.id),
  });

  provider.on("status", ({ status }) => {
    if (status === "connected") {
      saveStatus.textContent = "Connected";
      saveStatus.className = "status-ok";
    } else {
      saveStatus.textContent = "Connecting...";
      saveStatus.className = "status-pending";
    }
  });

  provider.awareness.on("change", () => renderPresence(provider.awareness));

  // Tear the connection down explicitly when the page goes away. This version
  // of y-websocket only registers an exit handler under Node in the browser
  // nothing runs on unload, so a refresh leaves our awareness state behind and
  // everyone else keeps showing a ghost cursor/dot for us until it times out
  // 30s later. destroy() broadcasts "this client is gone" before closing the
  // socket, so collaborators drop us immediately.
  // `pagehide` rather than `beforeunload`: it also fires when a mobile browser
  // backgrounds the tab, and it doesn't block the bfcache.
  window.addEventListener("pagehide", () => provider.destroy(), { once: true });

  // Title rename goes over REST, not the CRDT doc it's document, metadata, not document content.
  let titleDebounce;
  titleInput.addEventListener("input", () => {
    clearTimeout(titleDebounce);
    titleDebounce = setTimeout(async () => {
      try {
        await api.renameDocument(docId, titleInput.value || "Untitled document");
        document.title = `${titleInput.value} - Docsync`;
      } catch {
        // title save failures are low-stakes; leave the field as typed, but revert the document title in the tab to the last known good value
        titleInput.value = docMeta.title;
        document.title = `${docMeta.title} - Docsync`;
      }
    }, 600);
  });

  activityBtn.addEventListener("click", async () => {
    const willShow = activityPanel.hidden;
    activityPanel.hidden = !willShow;
    if (willShow) {
      try {
        renderActivity(await api.getActivity(docId));
      } catch (err) {
        activityList.innerHTML = `<li class="error-text">${escapeHtml(err.message)}</li>`;
      }
    }
  });
}

function renderPresence(awareness) {
  presenceBar.innerHTML = "";
  // One dot per *person*, not per Yjs client id. The same user has a different
  // client id in every tab, and a client id that vanished without a clean
  // disconnect (crash, killed tab, dropped network) lingers for up to 30s
  // before awareness times it out both would otherwise show them twice.
  const seen = new Set();
  for (const [, state] of awareness.getStates()) {
    if (!state.user) continue;
    const key = state.user.name;
    if (seen.has(key)) continue;
    seen.add(key);
    const dot = document.createElement("span");
    dot.className = "presence-dot";
    dot.style.backgroundColor = state.user.color;
    dot.title = state.user.name;
    dot.textContent = state.user.name.slice(0, 1).toUpperCase();
    presenceBar.appendChild(dot);
  }
}

function renderActivity(activity) {
  activityList.innerHTML = "";
  if (activity.length === 0) {
    activityList.innerHTML = "<li class='muted'>No activity yet.</li>";
    return;
  }
  for (const a of activity) {
    const li = document.createElement("li");
    const when = new Date(a.created_at).toLocaleString();
    li.textContent = `${a.username} ${a.event === "join" ? "joined" : "left"} \u2014 ${when}`;
    activityList.appendChild(li);
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

init();
