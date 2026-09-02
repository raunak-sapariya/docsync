const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);

export const API_BASE = isLocal
  ? "http://localhost:8000"
  : `${window.location.protocol}//${window.location.hostname}:8000`;

export const WS_BASE = isLocal
  ? "ws://localhost:8000"
  : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.hostname}:8000`;
