import { useEffect, useMemo, useState } from "react";
import AnimatedButton from "./components/AnimatedButton";
import { api } from "./api";
import DevicesPage from "./pages/DevicesPage";
import HistoryPage from "./pages/HistoryPage";
import MeasurePage from "./pages/MeasurePage";

function isGigETransport(transport) {
  return transport === "GigE" || transport === "GenTL-GigE";
}

function sortByTransportPriority(items) {
  return [...items].sort((a, b) => Number(isGigETransport(b.transport)) - Number(isGigETransport(a.transport)));
}

function pickPreferredCameraIds(items, maxCount = 2) {
  const gigeIds = items.filter((cam) => isGigETransport(cam.transport)).map((cam) => cam.camera_id);
  const fallbackIds = items.map((cam) => cam.camera_id);
  const merged = [...gigeIds, ...fallbackIds];
  const unique = [];
  for (const id of merged) {
    if (!unique.includes(id)) unique.push(id);
    if (unique.length >= maxCount) break;
  }
  return unique;
}

function initialLightState(sessionLike) {
  const state = {};
  for (const cameraId of sessionLike?.active_camera_ids || []) {
    state[cameraId] = false;
  }
  return state;
}

export default function App() {
  const [page, setPage] = useState("devices");
  const [booting, setBooting] = useState(true);
  const [busyOpen, setBusyOpen] = useState(false);
  const [busySave, setBusySave] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [sdkAvailable, setSdkAvailable] = useState(false);
  const [sdkError, setSdkError] = useState("");
  const [cameras, setCameras] = useState([]);
  const [detectedRealCameraCount, setDetectedRealCameraCount] = useState(0);
  const [forceMock, setForceMock] = useState(false);
  const [session, setSession] = useState(null);
  const [readings, setReadings] = useState({});
  const [lightState, setLightState] = useState({});
  const [cameraSettings, setCameraSettings] = useState({});
  const [cameraSettingsBusy, setCameraSettingsBusy] = useState({});

  const hasSession = (session?.active_camera_ids || []).length > 0;
  const readingCount = useMemo(() => Object.keys(readings).length, [readings]);
  const recommendedAutoIds = useMemo(() => {
    if (detectedRealCameraCount <= 0) return [];
    return pickPreferredCameraIds(cameras, 2);
  }, [cameras, detectedRealCameraCount]);

  const syncCameras = async () => {
    const data = await api.cameras();
    const sortedItems = sortByTransportPriority(data.items || []);
    setCameras(sortedItems);
    setDetectedRealCameraCount(Number(data.detected_real_camera_count || 0));
    setSdkAvailable(!!data.sdk_available);
    setSdkError(data.sdk_error || "");
  };

  const loadCameraSettings = async (cameraIds) => {
    const entries = await Promise.all(
      cameraIds.map(async (cameraId) => {
        try {
          const settings = await api.getCameraSettings(cameraId);
          return [cameraId, settings];
        } catch {
          return [cameraId, null];
        }
      })
    );
    const next = {};
    entries.forEach(([cameraId, settings]) => {
      if (settings) next[cameraId] = settings;
    });
    setCameraSettings(next);
  };

  const bootstrap = async () => {
    setBooting(true);
    setError("");
    try {
      const [healthData, sessionData] = await Promise.all([api.health(), api.sessionState()]);
      setSdkAvailable(!!healthData.sdk_available);
      setSdkError(healthData.sdk_error || "");
      await syncCameras();
      if ((sessionData?.active_camera_ids || []).length > 0) {
        setSession(sessionData);
        setLightState(initialLightState(sessionData));
        await loadCameraSettings(sessionData.active_camera_ids || []);
        setPage("measure");
      }
    } catch (err) {
      setError(err.message || "Failed to load initial state.");
    } finally {
      setBooting(false);
    }
  };

  useEffect(() => {
    bootstrap();
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => setError(""), 8000);
    return () => clearTimeout(timer);
  }, [error]);

  const withFeedback = async (fn, okMessage = "") => {
    setError("");
    setNotice("");
    try {
      const out = await fn();
      if (okMessage) setNotice(okMessage);
      return out;
    } catch (err) {
      setError(err.message || "Request failed.");
      throw err;
    }
  };

  const onOpenSession = async () => {
    setBusyOpen(true);
    try {
      await withFeedback(async () => {
        const resp = await api.openSession({
          selection_mode: "auto",
          max_camera_count: 2,
          force_mock: forceMock,
          use_mock_when_unavailable: true,
        });
        setSession(resp);
        setReadings({});
        setLightState(initialLightState(resp));
        await loadCameraSettings(resp.active_camera_ids || []);
        setPage("measure");
        return resp;
      }, "Session opened / 会话已启动");
    } finally {
      setBusyOpen(false);
    }
  };

  const onCloseSession = async () => {
    await withFeedback(async () => {
      await api.closeSession();
      setSession(null);
      setReadings({});
      setLightState({});
      setCameraSettings({});
      setCameraSettingsBusy({});
      setPage("devices");
    }, "Session closed / 会话已关闭");
  };

  const onToggleLight = async (cameraId, on) => {
    await withFeedback(async () => {
      if (on) {
        await api.lightOn(cameraId);
      } else {
        await api.lightOff(cameraId);
      }
      setLightState((prev) => ({ ...prev, [cameraId]: on }));
    });
  };

  const onMeasure = async (payload) => {
    return withFeedback(async () => {
      const result = await api.measure(payload);
      setReadings((prev) => ({ ...prev, [result.column_id]: result }));
      return result;
    });
  };

  const onAdjustCameraSetting = async (cameraId, patch) => {
    setCameraSettingsBusy((prev) => ({ ...prev, [cameraId]: true }));
    try {
      const updated = await api.setCameraSettings(cameraId, patch);
      setCameraSettings((prev) => ({ ...prev, [cameraId]: updated }));
    } catch (err) {
      setError(err.message || "Failed to update camera settings / 相机参数更新失败");
    } finally {
      setCameraSettingsBusy((prev) => ({ ...prev, [cameraId]: false }));
    }
  };

  const onClearReading = (columnId) => {
    setReadings((prev) => {
      if (!prev[columnId]) return prev;
      const next = { ...prev };
      delete next[columnId];
      return next;
    });
  };

  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [saveOperator, setSaveOperator] = useState("");
  const [saveNote, setSaveNote] = useState("");

  const onSaveRequest = () => {
    if (readingCount === 0) {
      setError("No readings to save yet / 暂无可保存读数");
      return;
    }
    setShowSaveDialog(true);
  };

  const onSaveConfirm = async () => {
    setShowSaveDialog(false);
    setBusySave(true);
    try {
      await withFeedback(async () => {
        const resp = await api.saveResult({
          measurements: Object.values(readings),
          operator: saveOperator.trim() || null,
          note: saveNote.trim() || null,
        });
        setSaveOperator("");
        setSaveNote("");
        setPage("history");
        return resp;
      }, "Result saved / 结果已保存");
    } finally {
      setBusySave(false);
    }
  };

  const onSaveCancel = () => {
    setShowSaveDialog(false);
  };

  const goPage = (next) => {
    if (next === "measure" && !hasSession) return;
    setPage(next);
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">
          <h1>Air Column Assistant</h1>
          <p>
            SDK: {sdkAvailable ? "loaded 已加载" : "unavailable 不可用"}
            {sdkError ? ` | ${sdkError}` : ""}
          </p>
        </div>
        <div className="header-actions">
          <div className="tab-row">
            <button className={page === "devices" ? "tab active" : "tab"} onClick={() => goPage("devices")}>
              Devices 设备
            </button>
            <button
              className={page === "measure" ? "tab active" : "tab"}
              disabled={!hasSession}
              onClick={() => goPage("measure")}
            >
              Read 测量
            </button>
            <button className={page === "history" ? "tab active" : "tab"} onClick={() => goPage("history")}>
              History 历史
            </button>
          </div>
          <AnimatedButton onClick={syncCameras}>Refresh 刷新</AnimatedButton>
          {hasSession && (
            <AnimatedButton className="warn" onClick={onCloseSession}>
              Close Session 关闭会话
            </AnimatedButton>
          )}
        </div>
      </header>

      {session?.using_mock && (
        <div className="mock-global-banner">
          MOCK MODE ACTIVE / 当前为模拟模式 — 数据非真实采集，仅用于调试
        </div>
      )}
      {error && <div className="error-banner">{error}</div>}
      {notice && <div className="notice-banner">{notice}</div>}
      {booting && <div className="hint">Loading... 正在加载</div>}

      <main className="app-main">
        {page === "devices" && (
          <DevicesPage
            cameras={cameras}
            autoCameraIds={recommendedAutoIds}
            detectedRealCameraCount={detectedRealCameraCount}
            sdkAvailable={sdkAvailable}
            sdkError={sdkError}
            forceMock={forceMock}
            setForceMock={setForceMock}
            onRefresh={syncCameras}
            onOpen={onOpenSession}
            busy={busyOpen}
          />
        )}
        {page === "measure" && (
          <MeasurePage
            session={session}
            readings={readings}
            onMeasure={onMeasure}
            onSaveResult={onSaveRequest}
            onToggleLight={onToggleLight}
            lightState={lightState}
            busySave={busySave}
            cameraSettings={cameraSettings}
            onAdjustCameraSetting={onAdjustCameraSetting}
            cameraSettingsBusy={cameraSettingsBusy}
            onClearReading={onClearReading}
          />
        )}
        {page === "history" && <HistoryPage />}
      </main>

      {showSaveDialog && (
        <div className="dialog-overlay" onClick={onSaveCancel}>
          <div className="dialog-box" onClick={(e) => e.stopPropagation()}>
            <h3>Save Results 保存结果</h3>
            <p className="hint">Readings to save 待保存读数: {readingCount}</p>
            {session?.using_mock && (
              <div className="mock-warn-inline">Mock mode active / 当前为模拟模式</div>
            )}
            <label>
              <span>Operator 操作员 *</span>
              <input
                type="text"
                value={saveOperator}
                onChange={(e) => setSaveOperator(e.target.value)}
                placeholder="Enter operator name / 输入操作员姓名"
                autoFocus
              />
            </label>
            <label>
              <span>Note 备注</span>
              <textarea
                value={saveNote}
                onChange={(e) => setSaveNote(e.target.value)}
                placeholder="Optional notes / 可选备注"
                rows={3}
              />
            </label>
            <div className="dialog-actions">
              <button className="btn-cancel" onClick={onSaveCancel}>Cancel 取消</button>
              <button className="btn-confirm" onClick={onSaveConfirm} disabled={busySave}>
                {busySave ? "Saving... 保存中" : "Confirm Save 确认保存"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
