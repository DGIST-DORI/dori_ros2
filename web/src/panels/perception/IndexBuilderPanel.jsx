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

function IndexBuilderPanel() {
  const [status,    setStatus]    = useState('idle');
  const [log,       setLog]       = useState([]);
  const [incremental, setIncremental] = useState(true);
  const [indexInfo, setIndexInfo] = useState(null);
  const pollRef = useRef(null);

  function appendLog(msg) {
    setLog(prev => [...prev, `${new Date().toLocaleTimeString()}  ${msg}`]);
  }

  const fetchIndexInfo = useCallback(async () => {
    try {
      const res = await fetch(`${API}/index-info`);
      if (res.ok) setIndexInfo(await res.json());
    } catch { /* backend might be offline */ }
  }, []);

  useEffect(() => {
    fetchIndexInfo();
  }, [fetchIndexInfo]);

  async function handleBuild() {
    setStatus('running');
    setLog([]);
    appendLog(`Starting ${incremental ? 'incremental' : 'full'} index rebuild…`);

    try {
      const res = await fetch(`${API}/build-index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ incremental }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? res.statusText);

      // Poll job status
      const jobId = data.job_id;
      appendLog(`Job started: ${jobId}`);

      pollRef.current = setInterval(async () => {
        const r = await fetch(`${API}/build-index/status/${jobId}`);
        const d = await r.json();
        d.new_lines?.forEach(l => appendLog(l));
        if (d.status === 'done') {
          clearInterval(pollRef.current);
          appendLog(`[OK] Done — ${d.total_chunks} chunks indexed.`);
          setStatus('ok');
          fetchIndexInfo();
        } else if (d.status === 'error') {
          clearInterval(pollRef.current);
          appendLog(`[ERR] Build failed: ${d.error}`);
          setStatus('error');
        }
      }, 800);
    } catch (e) {
      appendLog(`ERROR: ${e.message}`);
      setStatus('error');
    }
  }

  useEffect(() => () => clearInterval(pollRef.current), []);

  return (
    <Panel title="Index Builder" className="km-panel">
      <div className="km-section">
        <p className="km-hint">
          Embeds <code>data/campus/processed/**/*.txt</code> with
          MiniLM-L12 and saves a FAISS index for RAG retrieval.
        </p>

        {indexInfo && (
          <div className="km-index-info">
            <div className="km-info-row">
              <span>Vectors</span><span>{indexInfo.total_vectors ?? '—'}</span>
            </div>
            <div className="km-info-row">
              <span>Documents</span><span>{indexInfo.total_docs ?? '—'}</span>
            </div>
            <div className="km-info-row">
              <span>Built</span><span>{indexInfo.built_at ?? '—'}</span>
            </div>
          </div>
        )}

        <label className="km-checkbox-row">
          <input
            type="checkbox"
            checked={incremental}
            onChange={e => setIncremental(e.target.checked)}
          />
          <span>Incremental (skip unchanged files)</span>
        </label>

        <div className="km-actions">
          <button
            className="km-btn km-btn-primary"
            disabled={status === 'running'}
            onClick={handleBuild}
          >
            {status === 'running' ? 'Building…' : 'Build Index'}
          </button>
          <StatusBadge status={status} />
        </div>

        <LogPane lines={log} />
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

export default IndexBuilderPanel;
export { IndexBuilderPanel };
