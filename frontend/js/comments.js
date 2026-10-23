/**
 * Anchored comment threads.
 *
 *  Anchors are Yjs *relative* positions, not character offsets, so they
 *  survive concurrent edits above them. That logic lives in anchors.js.
 */
import { decodeAnchor, encodeAnchor } from "./anchors.js";
import { api } from "./api.js";

const HIGHLIGHT_OPEN = "docsync-comment";
const HIGHLIGHT_ACTIVE = "docsync-comment-active";

const highlightsSupported =
  typeof CSS !== "undefined" &&
  CSS.highlights &&
  typeof Highlight !== "undefined";

function domRangeFor(quill, index, length) {
  try {
    const [startLeaf, startOffset] = quill.getLeaf(index);
    const [endLeaf, endOffset] = quill.getLeaf(index + length);
    const startNode = startLeaf?.domNode;
    const endNode = endLeaf?.domNode;
    if (!startNode || !endNode) return null;
    if (
      startNode.nodeType !== Node.TEXT_NODE ||
      endNode.nodeType !== Node.TEXT_NODE
    )
      return null;

    const range = document.createRange();
    range.setStart(startNode, Math.min(startOffset, startNode.length));
    range.setEnd(endNode, Math.min(endOffset, endNode.length));
    return range.collapsed ? null : range;
  } catch {
    return null;
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function timeAgo(isoString) {
  const seconds = Math.floor(
    (Date.now() - new Date(isoString).getTime()) / 1000,
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function initComments({
  docId,
  ydoc,
  ytext,
  quill,
  provider,
  me,
  canComment,
  isOwner,
}) {
  const panel = document.getElementById("comments-panel");
  const toggleBtn = document.getElementById("comments-btn");
  const countBadge = document.getElementById("comment-count");
  const addBtn = document.getElementById("add-comment-btn");
  const list = document.getElementById("comment-list");
  const errorEl = document.getElementById("comment-error");
  const showResolved = document.getElementById("show-resolved");

  const composer = document.getElementById("comment-composer");
  const composerQuote = document.getElementById("composer-quote");
  const composerBody = document.getElementById("composer-body");
  const composerSubmit = document.getElementById("composer-submit");
  const composerCancel = document.getElementById("composer-cancel");

  let threads = [];
  let activeThreadId = null;
  // The selection captured when "Comment" was clicked. Held separately because
  // focusing the textarea drops the editor's own selection.
  let pendingSelection = null;

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function clearError() {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  // highlights
  function paintHighlights() {
    if (!highlightsSupported) return;
    const open = new Highlight();
    const active = new Highlight();

    for (const thread of threads) {
      if (thread.resolved) continue; // resolved threads stop shading the text
      const anchor = decodeAnchor(ydoc, thread);
      if (!anchor) continue;
      const range = domRangeFor(quill, anchor.index, anchor.length);
      if (!range) continue;
      (thread.id === activeThreadId ? active : open).add(range);
    }

    CSS.highlights.set(HIGHLIGHT_OPEN, open);
    CSS.highlights.set(HIGHLIGHT_ACTIVE, active);
  }

  function scrollToThread(thread) {
    const anchor = decodeAnchor(ydoc, thread);
    if (!anchor) return;
    const range = domRangeFor(quill, anchor.index, anchor.length);
    const target = range?.startContainer?.parentElement;
    if (target) target.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  // rendering
  function visibleThreads() {
    return showResolved.checked ? threads : threads.filter((t) => !t.resolved);
  }

  function render() {
    const shown = visibleThreads();
    const openCount = threads.filter((t) => !t.resolved).length;
    countBadge.textContent = openCount > 0 ? String(openCount) : "";
    countBadge.hidden = openCount === 0;

    list.innerHTML = "";
    if (shown.length === 0) {
      list.innerHTML = `<p class="muted comments-empty">${
        threads.length === 0
          ? canComment
            ? "No comments yet. Select some text to start one."
            : "No comments yet."
          : "No open comments."
      }</p>`;
      paintHighlights();
      return;
    }

    for (const thread of shown) list.appendChild(renderThread(thread));
    paintHighlights();
  }

  function renderThread(thread) {
    const anchor = decodeAnchor(ydoc, thread);
    const orphaned = anchor === null;

    const card = document.createElement("article");
    card.className = "comment-thread";
    if (thread.resolved) card.classList.add("is-resolved");
    if (thread.id === activeThreadId) card.classList.add("is-active");
    if (orphaned) card.classList.add("is-orphaned");

    const opener = thread.comments[0];
    const canDeleteThread = isOwner || opener?.user_id === me.id;

    card.innerHTML = `
      <p class="comment-quote">${escapeHtml(thread.quoted_text || "(no quoted text)")}</p>
      ${orphaned ? `<p class="comment-orphan-note">The text this referred to was deleted.</p>` : ""}
      <ul class="comment-messages">
        ${thread.comments
          .map(
            (c, i) => `
          <li data-comment-id="${c.id}">
            <span class="comment-author">${escapeHtml(c.username)}</span>
            <span class="comment-when">${timeAgo(c.created_at)}</span>
            <p class="comment-body">${escapeHtml(c.body)}</p>
            ${
              i > 0 && (isOwner || c.user_id === me.id)
                ? `<button class="comment-link" data-action="delete-comment">Delete</button>`
                : ""
            }
          </li>`,
          )
          .join("")}
      </ul>
      ${thread.resolved ? `<p class="comment-resolved-note">Resolved</p>` : ""}
      <div class="comment-thread-actions">
        ${canComment ? `<button class="comment-link" data-action="reply">Reply</button>` : ""}
        ${
          canComment
            ? `<button class="comment-link" data-action="toggle-resolved">${
                thread.resolved ? "Reopen" : "Resolve"
              }</button>`
            : ""
        }
        ${canDeleteThread ? `<button class="comment-link" data-action="delete-thread">Delete</button>` : ""}
      </div>
      <form class="comment-reply-form" hidden>
        <textarea rows="2" placeholder="Reply&hellip;" required></textarea>
        <button type="submit" class="btn-primary">Reply</button>
      </form>
    `;

    // Clicking the card focuses this thread and scrolls its text into view.
    card.addEventListener("click", (e) => {
      if (e.target.closest("button, textarea, form")) return;
      activeThreadId = thread.id;
      render();
      scrollToThread(thread);
    });

    const replyForm = card.querySelector(".comment-reply-form");
    card
      .querySelector('[data-action="reply"]')
      ?.addEventListener("click", () => {
        replyForm.hidden = false;
        replyForm.querySelector("textarea").focus();
      });

    replyForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const textarea = replyForm.querySelector("textarea");
      const body = textarea.value.trim();
      if (!body) return;
      await mutate(() => api.replyToThread(docId, thread.id, body));
    });

    card
      .querySelector('[data-action="toggle-resolved"]')
      ?.addEventListener("click", () =>
        mutate(() => api.setThreadResolved(docId, thread.id, !thread.resolved)),
      );

    card
      .querySelector('[data-action="delete-thread"]')
      ?.addEventListener("click", () => {
        if (!confirm("Delete this comment thread and its replies?")) return;
        mutate(() => api.deleteThread(docId, thread.id));
      });

    for (const btn of card.querySelectorAll('[data-action="delete-comment"]')) {
      btn.addEventListener("click", () => {
        const commentId = btn.closest("[data-comment-id]").dataset.commentId;
        mutate(() => api.deleteComment(docId, thread.id, commentId));
      });
    }

    return card;
  }

  // data
  async function refresh() {
    try {
      threads = await api.listComments(docId);
      clearError();
    } catch (err) {
      showError(`Couldn't load comments: ${err.message}`);
      return;
    }
    render();
  }

  /** Run a mutation, refresh, and tell the other clients to refresh too. */
  async function mutate(fn) {
    try {
      await fn();
      clearError();
    } catch (err) {
      showError(err.message);
      return;
    }
    await refresh();
    announceChange();
  }

  // live updates using awareness channel
  // Comments don't travel over the CRDT sync protocol, so nothing pushes them to other clients on its own.
  // Use a revision counter on the awareness channel that's already open for cursors: bumping
  // our own field broadcasts to the room, and everyone else refetches.
  const seenRevisions = new Map();

  function announceChange() {
    provider.awareness.setLocalStateField("commentsRev", Date.now());
  }

  let refreshTimer = null;
  function onAwarenessChange() {
    let changed = false;
    for (const [clientId, state] of provider.awareness.getStates()) {
      if (clientId === ydoc.clientID) continue;
      const rev = state?.commentsRev;
      if (rev === undefined) continue;
      if (seenRevisions.get(clientId) !== rev) {
        seenRevisions.set(clientId, rev);
        changed = true;
      }
    }
    if (!changed) return;
    // Awareness fires on every cursor move, so coalesce bursts into one fetch.
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refresh, 250);
  }

  // composer
  function openComposer(selection) {
    pendingSelection = selection;
    composerQuote.textContent = ytext
      .toString()
      .slice(selection.index, selection.index + selection.length);
    composerBody.value = "";
    composer.hidden = false;
    panel.hidden = false;
    composerBody.focus();
  }

  function closeComposer() {
    pendingSelection = null;
    composer.hidden = true;
    composerBody.value = "";
  }

  composerCancel.addEventListener("click", closeComposer);

  composerSubmit.addEventListener("click", async () => {
    const body = composerBody.value.trim();
    if (!body || !pendingSelection) return;
    const { index, length } = pendingSelection;
    const payload = {
      body,
      ...encodeAnchor(ytext, index, length),
      // Trimmed to the column width the API allows. Only ever used as a label
      // for a thread whose anchor no longer resolves.
      quoted_text: ytext
        .toString()
        .slice(index, index + length)
        .slice(0, 300),
    };
    closeComposer();
    await mutate(() => api.createCommentThread(docId, payload));
  });

  // wiring
  toggleBtn.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) refresh();
  });

  showResolved.addEventListener("change", render);

  // "Comment" is only live while there's a non-empty selection. A read-only
  // Quill (what viewers and commenters get) still reports selections, which is
  // what makes commenting on text you can't edit work at all.
  addBtn.hidden = !canComment;
  addBtn.disabled = true;

  let lastSelection = null;
  quill.on("selection-change", (range) => {
    // Quill reports null when focus leaves the editor e.g. when the user
    // clicks the Comment button. Keep the last real selection so the click
    // still has something to anchor to.
    if (range && range.length > 0) {
      lastSelection = { index: range.index, length: range.length };
      addBtn.disabled = false;
    } else if (range && range.length === 0) {
      lastSelection = null;
      addBtn.disabled = true;
    }
  });

  addBtn.addEventListener("click", () => {
    if (lastSelection) openComposer(lastSelection);
  });

  // Text edits move every anchor, so repaint when the document changes.
  let repaintTimer = null;
  ydoc.on("update", () => {
    clearTimeout(repaintTimer);
    repaintTimer = setTimeout(() => {
      paintHighlights();
      // Orphaned/restored state can change with an edit, so re-render cards.
      render();
    }, 150);
  });

  provider.awareness.on("change", onAwarenessChange);

  refresh();

  return { refresh };
}
