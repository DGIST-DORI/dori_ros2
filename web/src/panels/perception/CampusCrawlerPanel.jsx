import { useEffect, useRef, useState } from 'react';
import './CampusCrawlerPanel.css';

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

function CampusCrawlerPanel() {
  const [status, setStatus] = useState('idle');
  const [log, setLog] = useState([]);
  const [noLlm, setNoLlm] = useState(false);
  const [delay, setDelay] = useState(0.8);
  const [urlsPath, setUrlsPath] = useState('');
  const [outputDir, setOutputDir] = useState('data/campus');
  const [summary, setSummary] = useState(null);
  const pollRef = useRef(null);
  const linesSeenRef = useRef(0);

  function appendLog(msg) {
    setLog((prev) => [...prev, `${new Date().toLocaleTimeString()}  ${msg}`]);
  }

  function resetPolling() {
    clearInterval(pollRef.current);
    pollRef.current = null;
    linesSeenRef.current = 0;
  }

  function summarize(lines, finalStatus, errorMessage = '') {
    const processedCount = lines.filter((line) => /^\[[^\]]+\]\s+/.test(line) && !line.startsWith('[WARN]')).length;
    const fallbackCount = lines.filter((line) => line.includes('(raw fallback)') || line.includes('LLM refinement failed')).length;

    return {
      finalStatus,
      processedCount,
      fallbackUsed: fallbackCount > 0,
      fallbackCount,
      errorMessage,
    };
  }

  async function handleRun() {
    setStatus('running');
    setLog([]);
    setSummary(null);
    resetPolling();

    const body = {
      no_llm: noLlm,
      delay: Number.isFinite(delay) ? Number(delay) : 0,
      output_dir: outputDir || 'data/campus',
    };
    if (urlsPath.trim()) body.urls_path = urlsPath.trim();

    appendLog('Starting campus crawl job…');

    try {
      const res = await fetch(`${API}/crawl-campus`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? res.statusText);

      const jobId = data.job_id;
      appendLog(`Job started: ${jobId}`);

      pollRef.current = setInterval(async () => {
        try {
          const r = await fetch(`${API}/crawl-campus/status/${jobId}`);
          const d = await r.json();
          if (!r.ok) throw new Error(d.detail ?? r.statusText);

          const newLines = d.new_lines?.slice(linesSeenRef.current) ?? [];
          linesSeenRef.current += newLines.length;
          newLines.forEach((line) => appendLog(line));

          if (d.status === 'done') {
            resetPolling();
            setStatus('ok');
            appendLog('[OK] Campus crawl completed.');
            setSummary(summarize(d.new_lines ?? [], 'ok'));
          } else if (d.status === 'error') {
            resetPolling();
            setStatus('error');
            appendLog(`[ERR] Crawl failed: ${d.error}`);
            setSummary(summarize(d.new_lines ?? [], 'error', d.error));
          }
        } catch (e) {
          resetPolling();
          setStatus('error');
          appendLog(`ERROR: ${e.message}`);
          setSummary({
            finalStatus: 'error',
            processedCount: 0,
            fallbackUsed: false,
            fallbackCount: 0,
            errorMessage: e.message,
          });
        }
      }, 1000);
    } catch (e) {
      appendLog(`ERROR: ${e.message}`);
      setStatus('error');
      setSummary({
        finalStatus: 'error',
        processedCount: 0,
        fallbackUsed: false,
        fallbackCount: 0,
        errorMessage: e.message,
      });
    }
  }

  useEffect(() => () => resetPolling(), []);

  return (
    <div className="layout-panel-body km-campus-crawler-panel">
      <div className="panel-section">
        <p className="hint-text">
          Crawl campus webpages and save outputs under <code>data/campus/</code>.
          This panel calls <code>POST /api/knowledge/crawl-campus</code> and live-polls job status.
        </p>

        <label className="km-checkbox-row">
          <input
            type="checkbox"
            checked={noLlm}
            onChange={(e) => setNoLlm(e.target.checked)}
          />
          <span>No LLM (save raw fallback text only)</span>
        </label>

        <div className="km-crawler-grid">
          <label className="km-input-field">
            <span>Delay (sec)</span>
            <input
              type="number"
              min="0"
              step="0.1"
              value={delay}
              onChange={(e) => setDelay(Number(e.target.value))}
            />
          </label>

          <label className="km-input-field km-input-field-wide">
            <span>Extra URL file path (optional)</span>
            <input
              type="text"
              placeholder="e.g. data/campus/urls_extra.csv"
              value={urlsPath}
              onChange={(e) => setUrlsPath(e.target.value)}
            />
          </label>

          <label className="km-input-field km-input-field-wide">
            <span>Output dir</span>
            <input
              type="text"
              value={outputDir}
              onChange={(e) => setOutputDir(e.target.value)}
            />
          </label>
        </div>

        <div className="row row-wrap">
          <button
            className="btn btn-sm btn-primary"
            disabled={status === 'running'}
            onClick={handleRun}
          >
            {status === 'running' ? 'Crawling…' : 'Run Campus Crawl'}
          </button>
          <StatusBadge status={status} />
        </div>

        {summary && (
          <div className={`km-crawl-summary ${summary.finalStatus === 'ok' ? 'is-ok' : 'is-error'}`}>
            <div><strong>Result:</strong> {summary.finalStatus === 'ok' ? 'Success' : 'Failed'}</div>
            <div><strong>Processed URLs:</strong> {summary.processedCount}</div>
            <div><strong>Fallback used:</strong> {summary.fallbackUsed ? `Yes (${summary.fallbackCount})` : 'No'}</div>
            {summary.errorMessage && <div><strong>Error:</strong> {summary.errorMessage}</div>}
          </div>
        )}

        <LogPane lines={log} />
      </div>
    </div>
  );
}

export default CampusCrawlerPanel;
export { CampusCrawlerPanel };
