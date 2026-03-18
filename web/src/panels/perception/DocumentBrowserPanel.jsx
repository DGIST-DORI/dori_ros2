/** Panel implementation (standalone file). */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Check, X, AlertCircle, Upload, RefreshCw } from 'lucide-react';
import Panel from '../../components/Panel';
import '../../tabs/KnowledgeTab.css';

const API = '/api/knowledge';

// ── Helpers ───────────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const map = {
    idle:    ['km-badge km-badge-idle',    '—'],
    running: ['km-badge km-badge-running', 'RUNNING'],
    ok:      ['km-badge km-badge-ok',      'OK'],
    error:   ['km-badge km-badge-error',   'ERROR'],
  };
  const [cls, label] = map[status] ?? map.idle;
  return <span className={cls}>{label}</span>;
}

function LogPane({ lines }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines]);
  return (
    <div className="km-log" ref={ref}>
      {lines.length === 0
        ? <span className="km-log-empty">No output yet.</span>
        : lines.map((l, i) => <div key={i} className="km-log-line">{l}</div>)
      }
    </div>
  );
}

// ── Section 3: Document Browser ───────────────────────────────────────────────

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

// ── Root tab ──────────────────────────────────────────────────────────────────

function KnowledgeTab() {
  return (
    <div className="km-layout">
      <div className="km-col km-col-left">
        <MenuParserPanel />
        <IndexBuilderPanel />
      </div>
      <div className="km-col km-col-right">
        <DocumentBrowserPanel />
        <BuildingEditorPanel />
      </div>
    </div>
  );
}

export default DocumentBrowserPanel;
export { DocumentBrowserPanel };
