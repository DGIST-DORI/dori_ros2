import { useState, useEffect, useCallback } from 'react';
import Panel from '../../components/Panel';
import '../../tabs/KnowledgeTab.css';

const API = '/api/knowledge';

function DocumentBrowserPanel() {
  const [docs,    setDocs]    = useState([]);
  const [loading, setLoading] = useState(false);
  const [filter,  setFilter]  = useState('');

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/documents`);
      if (res.ok) setDocs(await res.json());
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  const filtered = docs.filter(d =>
    d.source.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <Panel title="Indexed Documents" badge={docs.length} className="km-panel">
      <div className="km-section">
        <div className="km-toolbar">
          <input
            className="km-search"
            placeholder="Filter by filename…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
          <button className="km-btn" onClick={fetchDocs} disabled={loading}>
            {loading ? '…' : '↻'}
          </button>
        </div>

        <div className="km-doc-list">
          {filtered.length === 0 && !loading && (
            <div className="km-empty">No documents found.</div>
          )}
          {filtered.map((doc, i) => (
            <div key={i} className="km-doc-item">
              <div className="km-doc-source">{doc.source}</div>
              <div className="km-doc-meta">
                <span>{doc.chunks} chunks</span>
                <span>{doc.size_kb} KB</span>
                <span className="km-doc-mtime">{doc.modified}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

export default DocumentBrowserPanel;
export { DocumentBrowserPanel };
