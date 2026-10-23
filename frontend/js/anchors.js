/**
 * Encoding and resolving comment anchors.
 *
 * Anchors are Yjs *relative* positions rather than character offsets. A
 * relative position names a place in the CRDT's item graph, so it keeps
 * pointing at the same words when a collaborator inserts or deletes text
 * above it. A stored integer offset would silently drift to the wrong
 * sentence the first time someone edited earlier in the document.
 */
import * as Y from "yjs";

export function bytesToBase64(bytes) {
  let out = "";
  for (const b of bytes) out += String.fromCharCode(b);
  return btoa(out);
}

export function base64ToBytes(b64) {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

/**
 * Encode a selection as a pair of relative positions.
 *
 * The `assoc` arguments decide which side of each boundary newly typed text
 * lands on. The start uses the default (0, associating rightward with the
 * first selected character) and the end uses -1 (associating leftward with
 * the last selected character). The effect is that typing immediately before
 * or immediately after the commented phrase leaves the highlight where it
 * was, instead of stretching it to swallow the new text.
 */
export function encodeAnchor(ytext, index, length) {
  const start = Y.createRelativePositionFromTypeIndex(ytext, index);
  const end = Y.createRelativePositionFromTypeIndex(ytext, index + length, -1);
  return {
    anchor_start: bytesToBase64(Y.encodeRelativePosition(start)),
    anchor_end: bytesToBase64(Y.encodeRelativePosition(end)),
  };
}

/**
 * Resolve a stored anchor back to {index, length} in the current document, or
 * null if it can't be placed any more.
 *
 * Null is a normal outcome rather than an error: it means the commented text
 * has since been deleted, which leaves the thread "orphaned" still worth
 * showing in the sidebar, with its quoted snippet and nothing to highlight.
 */
export function decodeAnchor(ydoc, thread) {
  try {
    const start = Y.createAbsolutePositionFromRelativePosition(
      Y.decodeRelativePosition(base64ToBytes(thread.anchor_start)),
      ydoc
    );
    const end = Y.createAbsolutePositionFromRelativePosition(
      Y.decodeRelativePosition(base64ToBytes(thread.anchor_end)),
      ydoc
    );
    if (!start || !end) return null;
    const length = end.index - start.index;
    if (length <= 0) return null;
    return { index: start.index, length };
  } catch {
    return null;
  }
}
