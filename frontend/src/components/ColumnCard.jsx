import { motion } from "framer-motion";

function confidenceClass(level) {
  if (level === "high") return "confidence-high";
  if (level === "medium") return "confidence-medium";
  return "confidence-low";
}

function confidenceLabel(level) {
  if (level === "high") return "High 高";
  if (level === "medium") return "Medium 中";
  return "Low 低";
}

export default function ColumnCard({ columnId, value, active, cameraId }) {
  const physical = value?.physical;
  const confLevel = value?.confidence_level || "low";
  const confPct = value ? Math.round(value.confidence * 100) : 0;

  return (
    <motion.article
      className={`column-card ${active ? "active" : ""}`}
      whileHover={{ y: -4 }}
      transition={{ type: "spring", stiffness: 220, damping: 18 }}
    >
      <header>
        <h4>Column {columnId} 空气柱</h4>
        <span>{cameraId || "-"}</span>
      </header>
      <div className="column-value">
        {value ? (
          <>
            <strong>{value.tick_delta.toFixed(1)}</strong>
            <em>ticks 刻度</em>
            {physical && (
              <div className="physical-values">
                <span>{physical.volume_ml.toFixed(3)} {physical.volume_unit || "mL"}</span>
                <span>{physical.length_mm.toFixed(2)} mm</span>
              </div>
            )}
          </>
        ) : (
          <span className="empty">No reading 暂无读数</span>
        )}
      </div>
      {value && (
        <>
          <p>
            Top 上限 {value.top_tick.toFixed(1)} | Bottom 下限 {value.bottom_tick.toFixed(1)}
          </p>
          <p>
            Pixel delta 像素差 {value.pixel_delta.toFixed(1)}
          </p>
          <p className={confidenceClass(confLevel)}>
            Confidence 置信度: {confPct}% — {confidenceLabel(confLevel)}
          </p>
          {confLevel === "low" && (
            <div className="warn-tag">Low confidence / 置信度低，建议重测</div>
          )}
        </>
      )}
    </motion.article>
  );
}
