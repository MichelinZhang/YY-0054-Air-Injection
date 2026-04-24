import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import AnimatedButton from "../components/AnimatedButton";
import { api } from "../api";

export default function HistoryPage() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    setBusy(true);
    try {
      const data = await api.results();
      setItems(data.items || []);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <section className="page history-page">
      <div className="title-row">
        <h2>History Records 历史记录</h2>
        <AnimatedButton onClick={refresh}>{busy ? "Refreshing... 刷新中" : "Refresh 刷新"}</AnimatedButton>
      </div>
      <div className="history-grid">
        {items.map((item, idx) => (
          <motion.article
            key={item.record_id || idx}
            className="history-card"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.05 }}
          >
            <h3>{item.record_id}</h3>
            <p>Time 时间: {item.created_at || "-"}</p>
            <p>Operator 操作员: {item.operator || "-"}</p>
            <p>Note 备注: {item.note || "-"}</p>
            <p>Reading count 测量数: {item.measurements?.length || 0}</p>
            {item.image_paths?.[0] && (
              <a href={item.image_paths[0]} target="_blank" rel="noreferrer">
                View annotated image 查看标注截图
              </a>
            )}
          </motion.article>
        ))}
      </div>
    </section>
  );
}
