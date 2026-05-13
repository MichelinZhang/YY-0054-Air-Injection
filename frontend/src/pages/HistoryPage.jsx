import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import AnimatedButton from "../components/AnimatedButton";
import { api } from "../api";

function matchesFilter(item, search) {
  if (!search) return true;
  const q = search.toLowerCase();
  return (
    (item.record_id || "").toLowerCase().includes(q) ||
    (item.operator || "").toLowerCase().includes(q) ||
    (item.note || "").toLowerCase().includes(q) ||
    (item.created_at || "").toLowerCase().includes(q)
  );
}

function exportCSV(items) {
  const headers = ["record_id", "created_at", "operator", "note", "measurement_count", "using_mock"];
  const rows = items.map((item) => [
    item.record_id || "",
    item.created_at || "",
    item.operator || "",
    (item.note || "").replace(/"/g, '""'),
    item.measurements?.length || 0,
    item.using_mock ? "Yes" : "No",
  ]);
  const csv = [headers.join(","), ...rows.map((r) => r.map((c) => `"${c}"`).join(","))].join("\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `results_export_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const PAGE_SIZE = 20;

export default function HistoryPage() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  const refresh = async () => {
    setBusy(true);
    try {
      const data = await api.results();
      setItems(data.items || []);
    } catch (err) {
      console.error("Failed to load history", err);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const filtered = useMemo(() => items.filter((item) => matchesFilter(item, search)), [items, search]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  useEffect(() => {
    setPage(0);
  }, [search]);

  return (
    <section className="page history-page">
      <div className="title-row">
        <h2>History Records 历史记录</h2>
        <div className="row-actions">
          <input
            className="search-input"
            type="text"
            placeholder="Search / 搜索..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <AnimatedButton onClick={refresh}>{busy ? "Refreshing... 刷新中" : "Refresh 刷新"}</AnimatedButton>
          <AnimatedButton onClick={() => exportCSV(filtered)} disabled={filtered.length === 0}>
            Export CSV 导出
          </AnimatedButton>
        </div>
      </div>

      <p className="hint">
        Total 总计: {items.length} | Filtered 筛选: {filtered.length}
        {totalPages > 1 && ` | Page 页: ${page + 1}/${totalPages}`}
      </p>

      <div className="history-grid">
        {pageItems.map((item, idx) => (
          <motion.article
            key={item.record_id || idx}
            className="history-card"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.03 }}
          >
            <h3>{item.record_id}</h3>
            <p>Time 时间: {item.created_at || "-"}</p>
            <p>Operator 操作员: {item.operator || "-"}</p>
            <p>Note 备注: {item.note || "-"}</p>
            <p>Reading count 测量数: {item.measurements?.length || 0}</p>
            {item.using_mock && <span className="mock-tag">Mock</span>}
            <div className="image-thumbs">
              {(item.image_paths || []).map((src) => (
                <a key={src} href={src} target="_blank" rel="noreferrer">
                  <img src={src} alt="annotated" className="thumb" loading="lazy" />
                </a>
              ))}
            </div>
          </motion.article>
        ))}
        {pageItems.length === 0 && <p className="hint">No records found / 无匹配记录</p>}
      </div>

      {totalPages > 1 && (
        <div className="pagination">
          <button className="chip" disabled={page === 0} onClick={() => setPage(page - 1)}>Prev 上一页</button>
          <span>{page + 1} / {totalPages}</span>
          <button className="chip" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>Next 下一页</button>
        </div>
      )}
    </section>
  );
}
