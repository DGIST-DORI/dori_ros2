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

// ── Section 4: Building Editor ────────────────────────────────────────────────

const EMPTY_BUILDING = {
  bldg_no: '', name_ko: '', name_en: '',
  description_ko: '', description_en: '',
  coordinates: [0.0, 0.0], floor: 1,
  keywords: [], hours: '', facilities: [], url: '',
};

function BuildingEditorPanel() {
  const [buildings, setBuildings]   = useState({});
  const [selected,  setSelected]    = useState(null);
  const [draft,     setDraft]       = useState(null);
  const [saving,    setSaving]      = useState(false);
  const [saveStatus, setSaveStatus] = useState('idle');
  const [filter,    setFilter]      = useState('');

  const fetchBuildings = useCallback(async () => {
    try {
      const res = await fetch(`${API}/buildings`);
      if (res.ok) setBuildings(await res.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchBuildings(); }, [fetchBuildings]);

  function selectBuilding(key) {
    setSelected(key);
    setDraft({ ...EMPTY_BUILDING, ...buildings[key] });
    setSaveStatus('idle');
  }

  function updateDraft(field, value) {
    setDraft(prev => ({ ...prev, [field]: value }));
  }

  async function handleSave() {
    if (!selected || !draft) return;
    setSaving(true);
    setSaveStatus('running');
    try {
      const res = await fetch(`${API}/buildings/${encodeURIComponent(selected)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      await fetchBuildings();
      setSaveStatus('ok');
    } catch (e) {
      setSaveStatus('error');
    }
    setSaving(false);
  }

  const keys = Object.keys(buildings).filter(k =>
    k.toLowerCase().includes(filter.toLowerCase()) ||
    (buildings[k].name_ko ?? '').includes(filter) ||
    (buildings[k].name_en ?? '').toLowerCase().includes(filter.toLowerCase())
  );

  const isEmpty = (b) => !b.name_ko && !b.name_en;

  return (
    <Panel title="Building Editor" className="km-panel km-panel-wide">
      <div className="km-building-layout">
        {/* Left: key list */}
        <div className="km-building-list">
          <input
            className="km-search"
            placeholder="Search…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
          <div className="km-building-keys">
            {keys.map(k => (
              <button
                key={k}
                className={`km-building-key ${selected === k ? 'active' : ''} ${isEmpty(buildings[k]) ? 'empty' : ''}`}
                onClick={() => selectBuilding(k)}
              >
                <span className="km-key-id">{k}</span>
                {isEmpty(buildings[k])
                  ? <span className="km-key-empty">unfilled</span>
                  : <span className="km-key-name">{buildings[k].name_ko}</span>
                }
              </button>
            ))}
          </div>
        </div>

        {/* Right: editor */}
        <div className="km-building-editor">
          {!draft
            ? <div className="km-empty km-empty-center">Select a building to edit</div>
            : (
              <>
                <div className="km-field-grid">
                  {[
                    ['Name (KO)',    'name_ko',          'text'],
                    ['Name (EN)',    'name_en',          'text'],
                    ['Hours',        'hours',             'text'],
                    ['URL',          'url',               'text'],
                    ['Floor',        'floor',             'number'],
                  ].map(([label, field, type]) => (
                    <label key={field} className="km-field">
                      <span className="km-field-label">{label}</span>
                      <input
                        type={type}
                        className="km-input"
                        value={draft[field] ?? ''}
                        onChange={e => updateDraft(field,
                          type === 'number' ? Number(e.target.value) : e.target.value
                        )}
                      />
                    </label>
                  ))}
                  <label className="km-field km-field-full">
                    <span className="km-field-label">Description (KO)</span>
                    <textarea
                      className="km-input km-textarea"
                      value={draft.description_ko ?? ''}
                      onChange={e => updateDraft('description_ko', e.target.value)}
                    />
                  </label>
                  <label className="km-field km-field-full">
                    <span className="km-field-label">Description (EN)</span>
                    <textarea
                      className="km-input km-textarea"
                      value={draft.description_en ?? ''}
                      onChange={e => updateDraft('description_en', e.target.value)}
                    />
                  </label>
                  <label className="km-field km-field-full">
                    <span className="km-field-label">Keywords (comma-separated)</span>
                    <input
                      type="text"
                      className="km-input"
                      value={(draft.keywords ?? []).join(', ')}
                      onChange={e => updateDraft('keywords',
                        e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                      )}
                    />
                  </label>
                  <label className="km-field km-field-full">
                    <span className="km-field-label">Facilities (comma-separated)</span>
                    <input
                      type="text"
                      className="km-input"
                      value={(draft.facilities ?? []).join(', ')}
                      onChange={e => updateDraft('facilities',
                        e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                      )}
                    />
                  </label>
                  <label className="km-field">
                    <span className="km-field-label">Coord lat</span>
                    <input
                      type="number"
                      step="0.0001"
                      className="km-input"
                      value={draft.coordinates?.[0] ?? 0}
                      onChange={e => updateDraft('coordinates',
                        [parseFloat(e.target.value), draft.coordinates?.[1] ?? 0]
                      )}
                    />
                  </label>
                  <label className="km-field">
                    <span className="km-field-label">Coord lng</span>
                    <input
                      type="number"
                      step="0.0001"
                      className="km-input"
                      value={draft.coordinates?.[1] ?? 0}
                      onChange={e => updateDraft('coordinates',
                        [draft.coordinates?.[0] ?? 0, parseFloat(e.target.value)]
                      )}
                    />
                  </label>
                </div>

                <div className="km-actions">
                  <button
                    className="km-btn km-btn-primary"
                    disabled={saving}
                    onClick={handleSave}
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                  <button
                    className="km-btn"
                    onClick={() => { setDraft({ ...EMPTY_BUILDING, ...buildings[selected] }); setSaveStatus('idle'); }}
                  >
                    Reset
                  </button>
                  <StatusBadge status={saveStatus} />
                </div>
              </>
            )
          }
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

export default BuildingEditorPanel;
export { BuildingEditorPanel };
