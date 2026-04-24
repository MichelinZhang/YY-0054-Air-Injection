import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { wsPreviewUrl } from "../api";

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function centerOf(a, b) {
  return {
    x: (a.x + b.x) / 2,
    y: (a.y + b.y) / 2,
  };
}

export default function CameraPreview({
  cameraId,
  title,
  columnScope,
  onPickPoint,
  points = [],
  selected = false,
  settings,
  onAdjustSettings,
  settingsBusy = false,
}) {
  const [frame, setFrame] = useState(null);
  const [status, setStatus] = useState("connecting");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [exposureInput, setExposureInput] = useState("");

  const frameRef = useRef(null);
  const zoomRef = useRef(1);
  const panRef = useRef({ x: 0, y: 0 });
  const pointersRef = useRef(new Map());
  const gestureRef = useRef({
    mode: "idle",
    startX: 0,
    startY: 0,
    startPan: { x: 0, y: 0 },
    startDist: 1,
    startZoom: 1,
    startCenter: { x: 0, y: 0 },
    moved: false,
    lastTapTs: 0,
    lastTapPos: null,
  });

  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);

  useEffect(() => {
    panRef.current = pan;
  }, [pan]);

  useEffect(() => {
    let ws;
    let closed = false;

    const connect = () => {
      ws = new WebSocket(wsPreviewUrl(cameraId));
      ws.onopen = () => setStatus("live");
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.status === "ok") {
          setFrame(data);
          setStatus("live");
        } else {
          setStatus(data.status || "no_frame");
        }
      };
      ws.onerror = () => setStatus("error");
      ws.onclose = () => {
        setStatus("closed");
        if (!closed) setTimeout(connect, 900);
      };
    };

    connect();
    return () => {
      closed = true;
      ws?.close();
    };
  }, [cameraId]);

  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setExposureInput("");
    pointersRef.current.clear();
  }, [cameraId]);

  useEffect(() => {
    if (settings?.exposure_time_us == null) return;
    setExposureInput(String(Math.round(settings.exposure_time_us)));
  }, [settings?.exposure_time_us]);

  const src = useMemo(() => {
    if (!frame?.jpeg_base64) return "";
    return `data:image/jpeg;base64,${frame.jpeg_base64}`;
  }, [frame]);

  const clampPan = (nextPan, nextZoom) => {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) return nextPan;
    const maxX = ((nextZoom - 1) * rect.width) / 2;
    const maxY = ((nextZoom - 1) * rect.height) / 2;
    return {
      x: clamp(nextPan.x, -maxX, maxX),
      y: clamp(nextPan.y, -maxY, maxY),
    };
  };

  const setView = (nextZoom, nextPan) => {
    setZoom(nextZoom);
    setPan(clampPan(nextPan, nextZoom));
  };

  const zoomBy = (delta) => {
    const nextZoom = clamp(zoomRef.current + delta, 1, 4);
    setZoom(nextZoom);
    setPan((prev) => clampPan(prev, nextZoom));
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  const onWheel = (e) => {
    e.preventDefault();
    zoomBy(e.deltaY > 0 ? -0.12 : 0.12);
  };

  const resolvePoint = (clientX, clientY) => {
    if (!frameRef.current || !frame) return null;

    const rect = frameRef.current.getBoundingClientRect();
    const localX = clientX - rect.left;
    const localY = clientY - rect.top;

    const viewX =
      rect.width / 2 + (localX - rect.width / 2 - panRef.current.x) / zoomRef.current;
    const viewY =
      rect.height / 2 + (localY - rect.height / 2 - panRef.current.y) / zoomRef.current;

    // Reverse object-fit: cover mapping so click->source pixel is accurate.
    const fitScale = Math.max(rect.width / frame.width, rect.height / frame.height);
    const drawWidth = frame.width * fitScale;
    const drawHeight = frame.height * fitScale;
    const offsetX = (rect.width - drawWidth) / 2;
    const offsetY = (rect.height - drawHeight) / 2;

    const srcX = (viewX - offsetX) / fitScale;
    const srcY = (viewY - offsetY) / fitScale;

    return {
      x: clamp(srcX, 0, frame.width - 1),
      y: clamp(srcY, 0, frame.height - 1),
    };
  };

  const beginDrag = (clientX, clientY) => {
    gestureRef.current = {
      ...gestureRef.current,
      mode: "drag",
      startX: clientX,
      startY: clientY,
      startPan: { ...panRef.current },
      moved: false,
    };
  };

  const beginPinch = (a, b) => {
    const pinchDist = Math.max(distance(a, b), 1);
    const pinchCenter = centerOf(a, b);
    gestureRef.current = {
      ...gestureRef.current,
      mode: "pinch",
      startDist: pinchDist,
      startZoom: zoomRef.current,
      startPan: { ...panRef.current },
      startCenter: pinchCenter,
      moved: false,
    };
  };

  const maybeHandleTap = (e) => {
    const gesture = gestureRef.current;
    const now = Date.now();
    const isTouch = e.pointerType === "touch";
    const isDoubleTap =
      isTouch &&
      gesture.lastTapPos &&
      now - gesture.lastTapTs < 280 &&
      distance(gesture.lastTapPos, { x: e.clientX, y: e.clientY }) < 24;

    if (isDoubleTap && zoomRef.current > 1) {
      resetView();
      gestureRef.current.lastTapTs = 0;
      gestureRef.current.lastTapPos = null;
      return;
    }

    if (isTouch) {
      gestureRef.current.lastTapTs = now;
      gestureRef.current.lastTapPos = { x: e.clientX, y: e.clientY };
    }

    const point = resolvePoint(e.clientX, e.clientY);
    if (point) onPickPoint?.(cameraId, point);
  };

  const onPointerDown = (e) => {
    if (!frame) return;
    frameRef.current?.setPointerCapture?.(e.pointerId);
    pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pts = Array.from(pointersRef.current.values());
    if (pts.length === 1) beginDrag(e.clientX, e.clientY);
    if (pts.length === 2) beginPinch(pts[0], pts[1]);
  };

  const onPointerMove = (e) => {
    if (!pointersRef.current.has(e.pointerId)) return;
    pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pts = Array.from(pointersRef.current.values());
    const gesture = gestureRef.current;

    if (pts.length >= 2) {
      if (gesture.mode !== "pinch") beginPinch(pts[0], pts[1]);
      const a = pts[0];
      const b = pts[1];
      const nextDist = Math.max(distance(a, b), 1);
      const nextCenter = centerOf(a, b);
      const nextZoom = clamp(
        (gestureRef.current.startZoom * nextDist) / gestureRef.current.startDist,
        1,
        4
      );
      const shiftX = nextCenter.x - gestureRef.current.startCenter.x;
      const shiftY = nextCenter.y - gestureRef.current.startCenter.y;
      const nextPan = {
        x: gestureRef.current.startPan.x + shiftX,
        y: gestureRef.current.startPan.y + shiftY,
      };
      setView(nextZoom, nextPan);
      if (
        Math.abs(shiftX) > 2 ||
        Math.abs(shiftY) > 2 ||
        Math.abs(nextDist - gestureRef.current.startDist) > 2
      ) {
        gestureRef.current.moved = true;
      }
      return;
    }

    if (gesture.mode !== "drag") return;
    const dx = e.clientX - gesture.startX;
    const dy = e.clientY - gesture.startY;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) gestureRef.current.moved = true;

    if (zoomRef.current > 1) {
      setPan(
        clampPan(
          {
            x: gesture.startPan.x + dx,
            y: gesture.startPan.y + dy,
          },
          zoomRef.current
        )
      );
    }
  };

  const onPointerUp = (e) => {
    if (!pointersRef.current.has(e.pointerId)) return;
    frameRef.current?.releasePointerCapture?.(e.pointerId);

    const gesture = gestureRef.current;
    const tapCandidate =
      pointersRef.current.size === 1 && !gesture.moved && gesture.mode === "drag";
    pointersRef.current.delete(e.pointerId);
    if (tapCandidate) maybeHandleTap(e);

    const remaining = Array.from(pointersRef.current.values());
    if (remaining.length === 1) {
      beginDrag(remaining[0].x, remaining[0].y);
      return;
    }
    if (remaining.length === 0) {
      gestureRef.current = { ...gestureRef.current, mode: "idle", moved: false };
    }
  };

  const onPointerCancel = (e) => {
    pointersRef.current.delete(e.pointerId);
    const remaining = Array.from(pointersRef.current.values());
    if (remaining.length === 2) {
      beginPinch(remaining[0], remaining[1]);
    } else if (remaining.length === 1) {
      beginDrag(remaining[0].x, remaining[0].y);
    } else {
      gestureRef.current = { ...gestureRef.current, mode: "idle", moved: false };
    }
  };

  const bumpSetting = async (field, delta) => {
    if (!settings || settingsBusy || !onAdjustSettings) return;
    const range =
      field === "exposure_time_us" ? settings.exposure_range : settings.gain_range;
    const current = Number(settings[field] ?? 0);
    let nextValue = current + delta;
    if (range) nextValue = clamp(nextValue, Number(range.min), Number(range.max));
    await onAdjustSettings(cameraId, { [field]: nextValue });
  };

  const applyExposureInput = async () => {
    if (!settings || settingsBusy || !onAdjustSettings) return;
    const parsed = Number(exposureInput);
    if (!Number.isFinite(parsed)) return;
    const range = settings.exposure_range;
    const nextValue = range
      ? clamp(parsed, Number(range.min), Number(range.max))
      : parsed;
    setExposureInput(String(Math.round(nextValue)));
    await onAdjustSettings(cameraId, { exposure_time_us: nextValue });
  };

  return (
    <motion.section
      layout
      className={`preview-shell ${selected ? "selected" : ""}`}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32 }}
    >
      <header className="preview-head">
        <div>
          <h3>{title || cameraId}</h3>
          <p>
            {cameraId} {columnScope ? `| Columns ${columnScope}` : ""}
          </p>
        </div>
        <div className="status-pill">{status}</div>
      </header>

      <div
        ref={frameRef}
        className="preview-frame"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onDoubleClick={resetView}
      >
        <div
          className="zoom-layer"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          }}
        >
          {src ? <img src={src} alt={cameraId} /> : <div className="placeholder">Waiting frame...</div>}
          <div className="grid-overlay" />
          {points.map((pt) => (
            <div
              key={pt.key}
              className={`point point-${pt.kind}`}
              style={{
                left: `${(pt.x / (frame?.width || 1)) * 100}%`,
                top: `${(pt.y / (frame?.height || 1)) * 100}%`,
              }}
              title={`C${pt.columnId} ${pt.kind}`}
            >
              <span className="point-label">
                {pt.kind === "top" ? "Top" : pt.kind === "bottom" ? "Bottom" : "Top?"}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="preview-actions">
        <div className="zoom-actions">
          <button className="chip" onClick={() => zoomBy(-0.2)}>
            -
          </button>
          <span>Zoom {zoom.toFixed(1)}x</span>
          <button className="chip" onClick={() => zoomBy(0.2)}>
            +
          </button>
          <button className="chip" onClick={resetView}>
            Reset
          </button>
        </div>
        <div className="camera-setting-actions">
          <span>
            Exposure {frame?.exposure_time_us ? `${frame.exposure_time_us.toFixed(0)}us` : "--"}
          </span>
          <button
            className="chip"
            disabled={settingsBusy}
            onClick={() => bumpSetting("exposure_time_us", -200)}
          >
            -
          </button>
          <button
            className="chip"
            disabled={settingsBusy}
            onClick={() => bumpSetting("exposure_time_us", 200)}
          >
            +
          </button>
          <input
            className="setting-input"
            type="number"
            step="100"
            value={exposureInput}
            onChange={(e) => setExposureInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                applyExposureInput();
              }
            }}
            onBlur={applyExposureInput}
            disabled={settingsBusy}
            placeholder="us"
            title="Exposure time in microseconds"
          />
          <button className="chip" disabled={settingsBusy} onClick={applyExposureInput}>
            Apply
          </button>

          <span>Gain {frame?.gain != null ? frame.gain.toFixed(2) : "--"}</span>
          <button className="chip" disabled={settingsBusy} onClick={() => bumpSetting("gain", -0.5)}>
            -
          </button>
          <button className="chip" disabled={settingsBusy} onClick={() => bumpSetting("gain", 0.5)}>
            +
          </button>
        </div>
      </div>

      <footer className="preview-foot">
        <span>FPS: {frame?.fps?.toFixed?.(1) || "--"}</span>
        <span>Lost: {frame?.lost_packets ?? "--"}</span>
        <span>
          {zoom > 1
            ? "Drag or pinch to move, double click/tap to reset."
            : "Click image to pick points."}
        </span>
      </footer>
    </motion.section>
  );
}
