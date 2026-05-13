import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import AnimatedButton from "../components/AnimatedButton";
import CameraPreview from "../components/CameraPreview";
import ColumnCard from "../components/ColumnCard";

function cameraColumns(columnMap, cameraId) {
  return Object.entries(columnMap)
    .filter(([, cid]) => cid === cameraId)
    .map(([col]) => Number(col))
    .sort((a, b) => a - b);
}

export default function MeasurePage({
  session,
  readings,
  onMeasure,
  onSaveResult,
  onToggleLight,
  lightState,
  busySave,
  cameraSettings,
  onAdjustCameraSetting,
  cameraSettingsBusy,
  onClearReading,
}) {
  const [selectedColumn, setSelectedColumn] = useState(1);
  const [pickMode, setPickMode] = useState("top");
  const [draft, setDraft] = useState(null);
  const [message, setMessage] = useState("");
  const [showGuide, setShowGuide] = useState(true);

  const columnMap = session?.column_camera_map || {};
  const activeCameraIds = session?.active_camera_ids || [];
  const targetCameraId = columnMap[selectedColumn];
  const isSingleCamera = activeCameraIds.length <= 1;

  const overlayPoints = useMemo(() => {
    const list = [];
    Object.values(readings).forEach((m) => {
      list.push({
        key: `${m.reading_id}-top`,
        cameraId: m.camera_id,
        columnId: m.column_id,
        kind: "top",
        x: m.top_point.x,
        y: m.top_point.y,
      });
      list.push({
        key: `${m.reading_id}-bottom`,
        cameraId: m.camera_id,
        columnId: m.column_id,
        kind: "bottom",
        x: m.bottom_point.x,
        y: m.bottom_point.y,
      });
    });
    if (draft?.topPoint) {
      list.push({
        key: "draft-top",
        cameraId: draft.cameraId,
        columnId: draft.columnId,
        kind: "pending",
        x: draft.topPoint.x,
        y: draft.topPoint.y,
      });
    }
    return list;
  }, [readings, draft]);

  const pointsByCamera = useMemo(() => {
    const grouped = {};
    overlayPoints.forEach((pt) => {
      if (!grouped[pt.cameraId]) grouped[pt.cameraId] = [];
      grouped[pt.cameraId].push(pt);
    });
    return grouped;
  }, [overlayPoints]);

  const startTopPick = () => {
    setPickMode("top");
    setDraft(null);
    setMessage(`Column ${selectedColumn}: click image to mark TOP / 请选择上限点`);
  };

  const startBottomPick = () => {
    if (!draft?.topPoint || draft.columnId !== selectedColumn) {
      setMessage(`Column ${selectedColumn}: mark TOP first / 请先标注上限`);
      return;
    }
    setPickMode("bottom");
    setMessage(`Column ${selectedColumn}: click image to mark BOTTOM / 请选择下限点`);
  };

  const undoPick = () => {
    if (draft?.topPoint && pickMode === "bottom") {
      setDraft(null);
      setPickMode("top");
      setMessage(`Column ${selectedColumn}: TOP mark cleared / 已撤销上限点`);
      return;
    }
    setMessage("Nothing to undo / 当前无可撤销操作");
  };

  const remeasureColumn = () => {
    setDraft(null);
    setPickMode("top");
    onClearReading?.(selectedColumn);
    setMessage(`Column ${selectedColumn}: ready to re-measure / 已重置，重新标注`);
  };

  const pickPoint = async (cameraId, point) => {
    if (!targetCameraId) return;
    if (cameraId !== targetCameraId) {
      setMessage(`Column ${selectedColumn} belongs to ${targetCameraId}. Pick on that camera / 请在对应相机画面上标注`);
      return;
    }

    if (pickMode === "top") {
      setDraft({
        columnId: selectedColumn,
        cameraId,
        topPoint: point,
      });
      setPickMode("bottom");
      setMessage(`Column ${selectedColumn}: TOP recorded. Pick BOTTOM next / 上限已记录，请选择下限`);
      return;
    }

    if (!draft?.topPoint || draft.columnId !== selectedColumn) {
      setMessage(`Column ${selectedColumn}: mark TOP first / 请先标注上限`);
      setPickMode("top");
      return;
    }

    const p1 = draft.topPoint;
    const p2 = point;
    const top = p1.y <= p2.y ? p1 : p2;
    const bottom = p1.y <= p2.y ? p2 : p1;
    setDraft(null);
    setPickMode("top");

    try {
      const reading = await onMeasure({
        camera_id: cameraId,
        column_id: selectedColumn,
        top_point: top,
        bottom_point: bottom,
      });
      setMessage(
        `Column ${selectedColumn}: Δ ${reading.tick_delta.toFixed(1)} ticks (Top ${reading.top_tick.toFixed(1)}, Bottom ${reading.bottom_tick.toFixed(1)}) / 已完成测量`
      );
    } catch (err) {
      setMessage(err.message);
    }
  };

  return (
    <section className="page measure-page">
      <div className="title-row">
        <h2>Ruler Reading Assist 刻度读数辅助</h2>
        <div className="row-actions">
          <AnimatedButton className="primary" onClick={onSaveResult} disabled={busySave}>
            {busySave ? "Saving... 正在保存" : "Save Current Readings 保存结果"}
          </AnimatedButton>
        </div>
      </div>

      <div className="measure-grid">
        <div className={`previews ${isSingleCamera ? "single-camera" : ""}`}>
          {activeCameraIds.map((cameraId) => {
            const cols = cameraColumns(columnMap, cameraId);
            return (
              <CameraPreview
                key={cameraId}
                cameraId={cameraId}
                title={`Preview ${cameraId}`}
                columnScope={cols.join("/")}
                selected={cameraId === targetCameraId}
                points={pointsByCamera[cameraId] || []}
                onPickPoint={pickPoint}
                settings={cameraSettings[cameraId]}
                onAdjustSettings={onAdjustCameraSetting}
                settingsBusy={!!cameraSettingsBusy[cameraId]}
              />
            );
          })}
        </div>

        <aside className="control-panel">
          <h3>Reading Panel 读数面板</h3>

          {showGuide && (
            <div className="guide-banner">
              <strong>Quick Guide 操作指南:</strong>
              <ol>
                <li>Select column (C1-C4) 选择列</li>
                <li>Click image to mark TOP point 点击图像标上限</li>
                <li>Click image to mark BOTTOM point 点击图像标下限</li>
                <li>Repeat for other columns 重复其他列</li>
                <li>Click "Save" to store results 保存结果</li>
              </ol>
              <button className="chip" onClick={() => setShowGuide(false)}>Got it 知道了</button>
            </div>
          )}

          <div className="column-chooser">
            {[1, 2, 3, 4].map((id) => (
              <button
                key={id}
                className={selectedColumn === id ? "chip active" : "chip"}
                onClick={() => {
                  setSelectedColumn(id);
                  setDraft(null);
                  setPickMode("top");
                }}
              >
                C{id}
              </button>
            ))}
          </div>

          <p className="hint">Current column camera 当前列相机: {targetCameraId || "-"}</p>
          <p className="hint">Step 当前步骤: {pickMode === "top" ? "Mark TOP 标上限" : "Mark BOTTOM 标下限"}</p>

          <div className="mark-actions">
            <button className={pickMode === "top" ? "chip active" : "chip"} onClick={startTopPick}>
              Mark Top 标上限
            </button>
            <button className={pickMode === "bottom" ? "chip active" : "chip"} onClick={startBottomPick}>
              Mark Bottom 标下限
            </button>
            <button className="chip" onClick={undoPick}>
              Undo 撤销
            </button>
            <button className="chip" onClick={remeasureColumn}>
              Re-measure 重测
            </button>
          </div>

          <div className="light-group">
            {activeCameraIds.map((cameraId) => {
              const on = !!lightState[cameraId];
              return (
                <div key={cameraId} className="light-row">
                  <span>{cameraId}</span>
                  <AnimatedButton onClick={() => onToggleLight(cameraId, !on)} className={on ? "warn" : "primary"}>
                    {on ? "Light Off 关灯" : "Light On 开灯"}
                  </AnimatedButton>
                </div>
              );
            })}
          </div>

          <AnimatePresence mode="wait">
            <motion.p
              key={message || "idle"}
              className="message"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
            >
              {message || "Select a column, then mark TOP and BOTTOM points / 选择列后依次标注上限和下限。"}
            </motion.p>
          </AnimatePresence>

          <div className="column-cards">
            {[1, 2, 3, 4].map((id) => (
              <ColumnCard key={id} columnId={id} active={selectedColumn === id} cameraId={columnMap[id]} value={readings[id]} />
            ))}
          </div>
        </aside>
      </div>
    </section>
  );
}
