import { motion } from "framer-motion";

export default function ColumnCard({ columnId, value, active, cameraId }) {
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
            Pixel delta 像素差 {value.pixel_delta.toFixed(1)} | Confidence 置信度 {Math.round(value.confidence * 100)}%
          </p>
        </>
      )}
    </motion.article>
  );
}
