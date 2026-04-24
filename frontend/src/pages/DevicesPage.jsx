import { motion } from "framer-motion";
import AnimatedButton from "../components/AnimatedButton";

function mappingPreview(autoCameraIds) {
  if (autoCameraIds.length === 0) return [];
  if (autoCameraIds.length === 1) {
    return [
      { columns: "1 / 2 / 3 / 4", cameraId: autoCameraIds[0] },
    ];
  }
  return [
    { columns: "1 / 2", cameraId: autoCameraIds[0] },
    { columns: "3 / 4", cameraId: autoCameraIds[1] },
  ];
}

export default function DevicesPage({
  cameras,
  autoCameraIds,
  detectedRealCameraCount,
  sdkAvailable,
  sdkError,
  forceMock,
  setForceMock,
  onRefresh,
  onOpen,
  busy,
}) {
  const planRows = mappingPreview(autoCameraIds);

  return (
    <section className="page devices-page">
      <div className="title-row">
        <h2>Device Connection 设备连接</h2>
        <div className="row-actions">
          <AnimatedButton onClick={onRefresh}>Refresh Devices 刷新设备</AnimatedButton>
          <AnimatedButton className="primary" onClick={onOpen} disabled={busy}>
            {busy ? "Opening... 正在启动" : "Start Auto Session 自动启动"}
          </AnimatedButton>
        </div>
      </div>

      <p className="hint">
        SDK: {sdkAvailable ? "loaded 已加载" : "unavailable 不可用"}
        {sdkError ? ` | ${sdkError}` : ""}
      </p>

      <div className="auto-summary">
        <h3>Auto Detection 自动判定</h3>
        <p>
          Detected real cameras: {detectedRealCameraCount} | Will use: {Math.min(autoCameraIds.length || 1, 2)} (1 or 2)
        </p>
        {planRows.length > 0 ? (
          <div className="mapping-preview">
            {planRows.map((row) => (
              <div key={row.columns} className="mapping-chip">
                <strong>Columns 列 {row.columns}</strong>
                <span>{row.cameraId}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="hint">No physical camera found. Auto mode will fallback to 1 mock camera. 未检测到真机，将自动回退到1个模拟相机。</p>
        )}
      </div>

      <details className="advanced-panel">
        <summary>Advanced Settings 高级设置</summary>
        <label className="mock-toggle">
          <input
            type="checkbox"
            checked={forceMock}
            onChange={(e) => setForceMock(e.target.checked)}
          />
          Force Mock 强制模拟模式
        </label>
        <p className="hint">Use only for debugging/testing. 仅用于调试测试场景。</p>
      </details>

      <div className="device-grid">
        {cameras.map((cam, idx) => {
          const willUse = autoCameraIds.includes(cam.camera_id);
          const isFallbackMock = detectedRealCameraCount === 0;
          return (
            <motion.article
              key={cam.camera_id}
              className={`device-card ${willUse ? "selected" : ""}`}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.05 }}
            >
              <h3>{cam.model_name}</h3>
              <p>ID: {cam.camera_id}</p>
              <p>SN: {cam.serial_number}</p>
              <p>Link: {cam.transport}</p>
              <span className="online-tag">{cam.online ? "Online 在线" : "Offline 离线"}</span>
              <p className="hint">
                {isFallbackMock ? "Mock preview 模拟预览" : willUse ? "Will be used 将使用" : "Standby 备用"}
              </p>
            </motion.article>
          );
        })}
      </div>
      <p className="hint">Auto mode always maps 1 camera to all columns, or 2 cameras to 1/2 and 3/4. 自动模式固定映射。</p>
    </section>
  );
}
