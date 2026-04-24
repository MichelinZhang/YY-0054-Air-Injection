const API_BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, init = {}) {
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init.headers || {}),
      },
    });
  } catch (err) {
    const localDevProxy = !API_BASE && window.location.port === "5173";
    if (localDevProxy) {
      throw new Error(
        "Backend is unreachable at http://127.0.0.1:8000. Start backend: `cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`."
      );
    }
    throw err;
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    let rawText = "";
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      try {
        rawText = await res.text();
      } catch {
        // ignore parse error
      }
    }
    const localDevProxy = !API_BASE && window.location.port === "5173";
    const proxyDown = /ECONNREFUSED|proxy error|socket hang up|127\.0\.0\.1:8000/i.test(rawText);
    if (localDevProxy && (res.status === 500 || res.status === 502) && proxyDown) {
      detail =
        "Backend is not running on http://127.0.0.1:8000. Start backend: `cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.";
    }
    throw new Error(detail);
  }
  return res.json();
}

export function wsPreviewUrl(cameraId) {
  const raw = API_BASE || window.location.origin;
  const url = new URL(raw, window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return `${url.origin}/ws/preview?camera_id=${encodeURIComponent(cameraId)}`;
}

export const api = {
  health: () => request("/api/health"),
  cameras: () => request("/api/cameras"),
  openSession: (payload) =>
    request("/api/session/open", { method: "POST", body: JSON.stringify(payload) }),
  closeSession: () => request("/api/session/close", { method: "POST", body: "{}" }),
  sessionState: () => request("/api/session/state"),
  lightOn: (cameraId) => request(`/api/light/${cameraId}/on`, { method: "POST", body: "{}" }),
  lightOff: (cameraId) => request(`/api/light/${cameraId}/off`, { method: "POST", body: "{}" }),
  measure: (payload) =>
    request("/api/measure", { method: "POST", body: JSON.stringify(payload) }),
  getCameraSettings: (cameraId) => request(`/api/camera/${cameraId}/settings`),
  setCameraSettings: (cameraId, payload) =>
    request(`/api/camera/${cameraId}/settings`, { method: "POST", body: JSON.stringify(payload) }),
  saveResult: (payload) =>
    request("/api/result/save", { method: "POST", body: JSON.stringify(payload) }),
  results: () => request("/api/results"),
};
