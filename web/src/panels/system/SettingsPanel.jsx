/**
 * panels/system/SettingsPanel.jsx
 * Unified settings panel — theme, language, connection.
 * Moved from: Header theme selector.
 */

import { useEffect, useState } from 'react';
import { useStore } from '../../core/store';
import { useI18n, detectBrowserLang, LANG_LABELS } from '../../core/i18n';
import './SettingsPanel.css';

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, children }) {
  return (
    <div className="sp-section">
      <div className="sp-section-title">{title}</div>
      <div className="sp-section-body">{children}</div>
    </div>
  );
}

// ── Row ───────────────────────────────────────────────────────────────────────

function Row({ label, hint, children }) {
  return (
    <div className="sp-row">
      <div className="sp-row-label">
        <span className="sp-label">{label}</span>
        {hint && <span className="sp-hint">{hint}</span>}
      </div>
      <div className="sp-row-control">{children}</div>
    </div>
  );
}

// ── Segmented control ─────────────────────────────────────────────────────────

function Seg({ options, value, onChange }) {
  return (
    <div className="sp-seg">
      {options.map(opt => (
        <button
          key={opt.value}
          className={`sp-seg-btn ${value === opt.value ? 'active' : ''}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function SettingsPanel({ themeMode, onThemeModeChange }) {
  const { t, langPref, effectiveLang } = useI18n();
  const setLangPref = useStore(s => s.setLangPref);
  const wsUrl       = useStore(s => s.wsUrl);
  const setWsUrl    = useStore(s => s.setWsUrl);
  const connected   = useStore(s => s.connected);

  const [wsInput, setWsInput] = useState(wsUrl);
  const detectedLang = detectBrowserLang();

  // Keep wsInput in sync when store changes externally
  useEffect(() => {
    if (!connected) setWsInput(wsUrl);
  }, [wsUrl, connected]);

  function handleWsSave() {
    setWsUrl(wsInput.trim());
  }

  const themeOptions = [
    { value: 'light', label: t('settings.theme.light') },
    { value: 'dark',  label: t('settings.theme.dark') },
    { value: 'auto',  label: t('settings.theme.auto') },
  ];

  const langOptions = [
    { value: 'auto', label: t('settings.lang.auto') },
    { value: 'ko',   label: t('settings.lang.ko') },
    { value: 'en',   label: t('settings.lang.en') },
  ];

  return (
    <div className="sp-root">

      {/* ── Appearance ── */}
      <Section title={t('settings.section.appearance')}>
        <Row label={t('settings.theme.label')}>
          <Seg options={themeOptions} value={themeMode} onChange={onThemeModeChange} />
        </Row>
      </Section>

      {/* ── Language ── */}
      <Section title={t('settings.section.language')}>
        <Row
          label={t('settings.lang.label')}
          hint={langPref === 'auto'
            ? `${t('settings.lang.detected')}: ${LANG_LABELS[detectedLang]}`
            : undefined}
        >
          <Seg options={langOptions} value={langPref} onChange={setLangPref} />
        </Row>
      </Section>

      {/* ── Connection ── */}
      <Section title={t('settings.section.connection')}>
        <Row label={t('settings.ws.label')} hint={t('settings.ws.hint')}>
          <div className="sp-ws-row">
            <input
              className="sp-ws-input"
              value={wsInput}
              onChange={e => setWsInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleWsSave()}
              disabled={connected}
              spellCheck={false}
              placeholder="ws://localhost:9090"
            />
            <button
              className="sp-ws-save"
              onClick={handleWsSave}
              disabled={connected || wsInput.trim() === wsUrl}
            >
              Save
            </button>
          </div>
        </Row>
      </Section>

    </div>
  );
}

export { SettingsPanel };
