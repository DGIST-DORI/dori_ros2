import { useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import { TOPIC_META, useStore } from '../../core/store';
import { fmt, hzClass } from './shared/formatters';
import '../../tabs/SystemTab.css';

const COLUMNS = [
  { key: 'topic', label: 'Topic', sortFn: (a, b) => a.topic.localeCompare(b.topic) },
  { key: 'msgType', label: 'Type', sortFn: (a, b) => (a.msgType ?? '').localeCompare(b.msgType ?? '') },
  { key: 'pubSub', label: 'Pub/Sub', sortFn: null },
  { key: 'avgHz', label: 'Avg Hz', sortFn: (a, b) => (a.avgHz ?? -1) - (b.avgHz ?? -1) },
  { key: 'jitterMs', label: 'Jitter', sortFn: (a, b) => (a.jitterMs ?? -1) - (b.jitterMs ?? -1) },
  { key: 'bwBps', label: 'BW (B/s)', sortFn: (a, b) => (a.bwBps ?? -1) - (b.bwBps ?? -1) },
  { key: 'avgMsgBytes', label: 'Avg Msg', sortFn: (a, b) => (a.avgMsgBytes ?? -1) - (b.avgMsgBytes ?? -1) },
  { key: 'qosSummary', label: 'QoS', sortFn: null },
  { key: 'lastSeen', label: 'Last seen', sortFn: (a, b) => (b.lastSeenMs ?? 0) - (a.lastSeenMs ?? 0) },
];

function TopicDiagnosticsPanel({ className = 'sys-panel-diag' }) {
  const topicStats = useStore((s) => s.topicStats);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState('topic');
  const [sortDir, setSortDir] = useState(1);

  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  function handleSortClick(key) {
    if (COLUMNS.find((c) => c.key === key)?.sortFn === null) return;
    setSortDir((prev) => (sortKey === key ? -prev : 1));
    setSortKey(key);
  }

  const allRows = useMemo(
    () => Object.keys(TOPIC_META).map((topicName) => {
      const stat = topicStats[topicName] || {};
      return {
        topic: topicName,
        msgType: stat.msgType ?? null,
        pubSub: `${fmt(stat.pubCount)}/${fmt(stat.subCount)}`,
        avgHz: stat.avgHz ?? null,
        jitterMs: stat.jitterMs ?? null,
        bwBps: stat.bwBps ?? null,
        avgMsgBytes: stat.avgMsgBytes ?? null,
        qosSummary: stat.qosSummary ?? null,
        lastSeenMs: stat.lastSeenMs ?? null,
      };
    }),
    [topicStats],
  );

  const filteredSorted = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = query ? allRows.filter((row) => row.topic.toLowerCase().includes(query)) : allRows;
    const col = COLUMNS.find((c) => c.key === sortKey);
    if (!col?.sortFn) return filtered;
    return [...filtered].sort((a, b) => col.sortFn(a, b) * sortDir);
  }, [allRows, search, sortKey, sortDir]);

  return (
    <div className={`sys-panel-root sys-panel-diag-root ${className}`.trim()}>
      <div className="sys-topic-diag">
        <div className="sys-diag-toolbar">
          <input
            className="sys-diag-search"
            placeholder="Search topics…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <span className="sys-diag-count">{filteredSorted.length}/{allRows.length}</span>
          <span
            className="sys-tooltip"
            title="BW (B/s) = total JSON payload bytes ÷ rolling window. Avg Hz and jitter derived from inter-message timestamps."
          >ⓘ</span>
        </div>

        <div className="sys-topic-diag-table-wrap">
          <table className="sys-topic-diag-table">
            <thead>
              <tr>
                {COLUMNS.map((col) => {
                  const sortable = col.sortFn !== null;
                  const active = sortKey === col.key;
                  return (
                    <th
                      key={col.key}
                      className={`${sortable ? 'sortable' : ''} ${active ? 'sorted' : ''}`}
                      onClick={() => handleSortClick(col.key)}
                      title={sortable ? `Sort by ${col.label}` : undefined}
                    >
                      {col.label}
                      {sortable && (
                        <span className="sys-sort-arrow">
                          {active
                            ? (sortDir === 1
                              ? <ArrowUp size={9} strokeWidth={2.5} />
                              : <ArrowDown size={9} strokeWidth={2.5} />)
                            : <ArrowUpDown size={9} strokeWidth={2} />}
                        </span>
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {filteredSorted.length === 0 ? (
                <tr>
                  <td colSpan={COLUMNS.length} className="sys-diag-empty">
                    No topics match "{search}"
                  </td>
                </tr>
              ) : filteredSorted.map((row) => {
                const lastSeenText = row.lastSeenMs
                  ? `${Math.max(0, Math.round((nowMs - row.lastSeenMs) / 1000))}s ago`
                  : 'N/A';
                return (
                  <tr key={row.topic}>
                    <td className="sys-topic-cell" title={row.topic}>{row.topic}</td>
                    <td className="sys-type-cell">{fmt(row.msgType)}</td>
                    <td>{row.pubSub}</td>
                    <td className={hzClass(row.avgHz)}>{fmt(row.avgHz)}</td>
                    <td>{fmt(row.jitterMs, ' ms')}</td>
                    <td>{fmt(row.bwBps)}</td>
                    <td>{fmt(row.avgMsgBytes, ' B')}</td>
                    <td>{fmt(row.qosSummary)}</td>
                    <td>{lastSeenText}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default TopicDiagnosticsPanel;
export { TopicDiagnosticsPanel };
