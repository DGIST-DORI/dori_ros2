import { useState, useEffect, useRef, useCallback } from 'react';
import './IndexBuilderPanel.css';

const API = '/api/knowledge';

function StatusBadge({ status }) {
  const map = {
    idle: ['badge', '—'],
    running: ['badge badge-running', 'RUNNING'],
    ok: ['badge badge-ok', 'OK'],
    error: ['badge badge-error', 'ERROR'],
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
    <div className="log-pane" ref={ref}>
      {lines.length === 0
        ? <span className="log-pane-empty">No output yet.</span>
        : lines.map((l, i) => <div key={i} className="log-pane-line">{l}</div>)}
    </div>
  );
}

function IndexBuilderPanel() {
  const [status, setStatus] = useState('idle');
  const [log, setLog] = useState([]);
  const [incremental, setIncremental] = useState(true);
  const [indexInfo, setIndexInfo] = useState(null);
  const pollRef = useRef(null);
  const cursorRef = useRef(0);
  const seenLineHashesRef = useRef(new Set());

  function appendLog(msg) {
    setLog((prev) => [...prev, `${new Date().toLocaleTimeString()}  ${msg}`]);
  }

  function appendUniqueLines(lines) {
    const uniqueLines = [];
    for (const line of lines ?? []) {
      const key = JSON.stringify(line);
      if (seenLineHashesRef.current.has(key)) continue;
      seenLineHashesRef.current.add(key);
      uniqueLines.push(line);
    }
    uniqueLines.forEach((line) => appendLog(line));
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
    cursorRef.current = 0;
    seenLineHashesRef.current = new Set();
    clearInterval(pollRef.current);
    appendLog(`Starting ${incremental ? 'incremental' : 'full'} index rebuild…`);

    try {
      const res = await fetch(`${API}/build-index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ incremental }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? res.statusText);

      const jobId = data.job_id;
      appendLog(`Job started: ${jobId}`);

      pollRef.current = setInterval(async () => {
        const currentCursor = cursorRef.current;
        const r = await fetch(`${API}/build-index/status/${jobId}?cursor=${currentCursor}`);
        const d = await r.json();
        appendUniqueLines(d.new_lines);
        if (typeof d.next_cursor === 'number') {
          cursorRef.current = Math.max(currentCursor, d.next_cursor);
        } else {
          cursorRef.current = currentCursor + (d.new_lines?.length ?? 0);
        }
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
    <div className="layout-panel-body km-index-builder-panel">
      <div className="panel-section">
        <p className="hint-text">
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
            onChange={(e) => setIncremental(e.target.checked)}
          />
          <span>Incremental (skip unchanged files)</span>
        </label>

        <div className="row row-wrap">
          <button
            className="btn btn-sm btn-primary"
            disabled={status === 'running'}
            onClick={handleBuild}
          >
            {status === 'running' ? 'Building…' : 'Build Index'}
          </button>
          <StatusBadge status={status} />
        </div>

        <LogPane lines={log} />
      </div>
    </div>
  );
}

export default IndexBuilderPanel;
export { IndexBuilderPanel };
