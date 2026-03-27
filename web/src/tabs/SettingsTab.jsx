import { useState } from 'react';
import { useStore } from '../core/store';
import { useI18n, detectBrowserLang, LANG_LABELS } from '../core/i18n';
import { parseWsUrl } from '../core/url';
import DeployStatusPanel from '../panels/system/DeployStatusPanel';
import CloseIcon from '../assets/icons/icon-close.svg?react';
import './SettingsTab.css';

function Section({ title, children }) {
  return (
    <div className="sp-section">
      <div className="sp-section-title">{title}</div>
      <div className="sp-section-body">{children}</div>
    </div>
  );
}

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

export default function SettingsTab({ themeMode, onThemeModeChange, onClose }) {
  const { t, langPref } = useI18n();
  const setLangPref = useStore(s => s.setLangPref);
  const wsUrl       = useStore(s => s.wsUrl);
  const setWsUrl    = useStore(s => s.setWsUrl);
  const connected   = useStore(s => s.connected);
  const isDemoMode  = useStore(s => s.isDemoMode);

  const [wsInput, setWsInput] = useState(wsUrl);
  const detectedLang = detectBrowserLang();

  const parsedWsUrl = parseWsUrl(wsUrl);
  const statusLabel = connected ? 'Connected' : 'Disconnected';
  const statusTone = connected
    ? 'ok'
    : isDemoMode
      ? 'warn'
      : 'neutral';

  function handleWsSave() {
    setWsUrl(wsInput.trim());
  }

  const themeOptions = [
    { value: 'light', label: t('settings.theme.light') },
    { value: 'dark',  label: t('settings.theme.dark') },
    { value: 'auto',  label: t('settings.theme.auto') },
  ];

  const langOptions = [
    { value: 'ko',   label: t('settings.lang.ko') },
    { value: 'en',   label: t('settings.lang.en') },
    { value: 'auto', label: t('settings.lang.auto') },
  ];

  return (
    <div className="sp-root">
      <header className="sp-header">
        <h2 className="sp-title">{t('settings.title')}</h2>
        <button className="sp-close-btn" onClick={onClose} aria-label={t('sidebar.close')}>
          <CloseIcon />
        </button>
      </header>

      <Section title={t('settings.section.appearance')}>
        <Row label={t('settings.theme.label')}>
          <Seg options={themeOptions} value={themeMode} onChange={onThemeModeChange} />
        </Row>
      </Section>

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

      <Section title={t('settings.section.connection')}>
        <div className="sp-connection-split">
          <div className="sp-connection-card">
            <div className="sp-subtitle">설정 (WS URL)</div>
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
          </div>

          <div className="sp-connection-card sp-connection-status-card">
            <div className="sp-subtitle">현재 상태</div>
            <div className="sp-status-row">
              <span className="sp-status-label">Connection</span>
              <span className={`sp-status-pill ${statusTone}`}>{statusLabel}</span>
            </div>
            <div className="sp-info-list">
              <div className="sp-info-row">
                <span>{connected ? 'Current URL' : 'Configured URL'}</span>
                <span>{wsUrl}</span>
              </div>
              {parsedWsUrl ? (
                <>
                  <div className="sp-info-row"><span>Transport</span><span>{parsedWsUrl.protocol.toUpperCase()}</span></div>
                  <div className="sp-info-row"><span>Host</span><span>{parsedWsUrl.host}</span></div>
                  <div className="sp-info-row"><span>Port</span><span>{parsedWsUrl.port}</span></div>
                  <div className="sp-info-row"><span>Path</span><span>{parsedWsUrl.path || '/'}</span></div>
                </>
              ) : (
                <div className="sp-info-row">
                  <span>Transport</span>
                  <span className="sp-invalid">Invalid URL</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </Section>

      <Section title="Deploy Status">
        <DeployStatusPanel className="sp-deploy" />
      </Section>
    </div>
  );
}
