import { useState, useEffect } from 'react';
import { LOG_TAGS, useStore } from '../core/store';
import { useI18n } from '../core/i18n';
import { connectROS, disconnectROS } from '../core/ros';
import { startDemo, stopDemo } from '../core/demo';
import { PANEL_TREE, findLeaf } from '../panelTree';
import DashLogoText     from '../assets/logo/dash-text.svg?react';
import DashLogoTextDark from '../assets/logo/dash-text-dark.svg?react';
import './Header.css';

export default function Header({ onLogoClick, themeMode, sidebarExpanded }) {
  const { t } = useI18n();
  const connected    = useStore(s => s.connected);
  const isDemoMode   = useStore(s => s.isDemoMode);
  const wsUrl        = useStore(s => s.wsUrl);
  const setConnected = useStore(s => s.setConnected);
  const setWsUrl     = useStore(s => s.setWsUrl);
  const addLog       = useStore(s => s.addLog);
  const openPanel    = useStore(s => s.openPanel);
  const setActiveMainView = useStore(s => s.setActiveMainView);
  const deployStatus = useStore(s => s.deployStatus);

  const isOnline = connected || isDemoMode;
  const deployedCommit = deployStatus?.deployed_commit ?? null;
  const shortCommit = deployedCommit ? deployedCommit.slice(0, 7) : 'N/A';
  const deployChipLabel = `Deploy: ${shortCommit}`;
  const deployChipTitle = deployedCommit
    ? `Deploy: ${deployedCommit}`
    : 'Deploy: unavailable';
  const deployDetail = [
    `Status: ${deployStatus?.status ?? 'idle'}`,
    `Deployed commit: ${deployedCommit ?? 'N/A'}`,
    `Current commit: ${deployStatus?.current_commit ?? 'N/A'}`,
    `Branch: ${deployStatus?.deployed_branch ?? 'N/A'}`,
    `Deployed at: ${deployStatus?.deployed_at ?? 'N/A'}`,
  ].join('\n');

  const [urlInput,     setUrlInput]     = useState(wsUrl);
  const [isConnecting, setIsConnecting] = useState(false);
  const [showDeployDetail, setShowDeployDetail] = useState(false);

  // Keep URL input in sync when wsUrl changes (e.g. tunnel auto-detection)
  useEffect(() => {
    if (!connected && !isConnecting) setUrlInput(wsUrl);
  }, [wsUrl]);

  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    const apply = () => setIsDark(
      themeMode === 'auto'
        ? window.matchMedia('(prefers-color-scheme: dark)').matches
        : themeMode === 'dark'
    );
    apply();
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [themeMode]);

  function formatConnectError(error, url, source = 'network') {
    const message    = String(error?.message || error || 'Unknown error');
    const eventType  = error?.type;
    const readyState = error?.target?.readyState;
    const stateLabel = readyState === undefined
      ? 'n/a'
      : ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'][readyState] || String(readyState);
    const debugParts = [
      `url=${url || 'n/a'}`,
      `eventType=${eventType || 'n/a'}`,
      `readyState=${stateLabel}`,
      `message=${message}`,
    ];
    if (source === 'url')     return `Connection failed [url]: Invalid WebSocket URL. ${debugParts.join(', ')}. Use ws:// or wss://.`;
    if (source === 'loading') return `Connection failed [loading]: Failed to load ROS client library. ${debugParts.join(', ')}`;
    return `Connection failed [network]: Could not open WebSocket. ${debugParts.join(', ')}`;
  }

  async function handleConnect() {
    if (isConnecting) return;
    if (connected) {
      disconnectROS(); setConnected(false); addLog(LOG_TAGS.SYS, 'Disconnected from ROS');
    } else {
      try {
        const parsed = new URL(urlInput);
        if (!['ws:', 'wss:'].includes(parsed.protocol)) throw new Error('URL protocol must be ws:// or wss://');
        setIsConnecting(true);
        setConnected(false);
        stopDemo();
        await connectROS(urlInput, {
          onConnect: () => { setConnected(true);  setIsConnecting(false); addLog(LOG_TAGS.SYS, `Connected → ${urlInput}`); },
          onError:   e  => { setConnected(false); setIsConnecting(false); addLog(LOG_TAGS.ERROR, formatConnectError(e, urlInput, 'network')); },
          onClose:   () => { setConnected(false); setIsConnecting(false); addLog(LOG_TAGS.SYS, 'Connection closed'); },
        });
        setWsUrl(urlInput);
      } catch (e) {
        const source = e instanceof TypeError || e.message?.includes('protocol') ? 'url' : 'loading';
        setConnected(false); setIsConnecting(false);
        addLog(LOG_TAGS.ERROR, formatConnectError(e, urlInput, source));
      }
    }
  }

  function handleDemo() {
    if (isDemoMode) stopDemo();
    else { disconnectROS(); setConnected(false); startDemo(); }
  }

  const LogoText = isDark ? DashLogoTextDark : DashLogoText;

  function handleOpenDeployPanel() {
    const deployLeaf = findLeaf(PANEL_TREE, 'sys-deploy');
    if (!deployLeaf || deployLeaf.placeholder) return;
    openPanel(deployLeaf);
    setActiveMainView('workspace');
  }

  return (
    <header className="hdr">
      {/* Text logo — visible when sidebar is closed, fades out when sidebar opens */}
      <button
        className={`hdr-logo ${sidebarExpanded ? 'hdr-logo--hidden' : ''}`}
        onClick={onLogoClick}
        aria-label="DORI Dashboard home"
        tabIndex={sidebarExpanded ? -1 : 0}
      >
        <LogoText className="hdr-logo-svg" aria-hidden="true" />
      </button>

      <div className="hdr-spacer" />

      <button
        className="hdr-status-chip"
        onClick={handleOpenDeployPanel}
        title={deployDetail}
        aria-label="Open system deploy status panel"
      >
        <span className={`hdr-status-dot ${isOnline ? 'online' : ''}`} />
        <span className="hdr-status-text">{isOnline ? 'Connected' : 'Offline'}</span>
        <span className="hdr-status-sep" />
        <span className="hdr-deploy-text" title={deployChipTitle}>
          {deployChipLabel}
        </span>
      </button>
      <button
        className="hdr-status-info"
        onClick={() => setShowDeployDetail(true)}
        title="Deploy detail"
        aria-label="Show full deploy details"
      >
        i
      </button>

      <div className="hdr-conn">
        {/* URL input — synced with Settings tab but kept here for quick access */}
        <input
          className="hdr-url"
          value={urlInput}
          onChange={e => setUrlInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleConnect()}
          disabled={connected || isDemoMode || isConnecting}
          spellCheck={false}
        />
        <button
          className={`hdr-btn ${connected ? 'connected' : ''}`}
          onClick={handleConnect}
          disabled={isDemoMode || isConnecting}
        >
          {isConnecting
            ? t('header.connecting')
            : connected
              ? t('header.disconnect')
              : t('header.connect')}
        </button>
        <button
          className={`hdr-btn demo ${isDemoMode ? 'active' : ''}`}
          onClick={handleDemo}
        >
          {isDemoMode ? t('header.demo.stop') : t('header.demo.start')}
        </button>
      </div>

      {showDeployDetail && (
        <div className="hdr-detail-modal-backdrop" onClick={() => setShowDeployDetail(false)}>
          <div className="hdr-detail-modal" onClick={(e) => e.stopPropagation()}>
            <div className="hdr-detail-title">Deploy Details</div>
            <pre className="hdr-detail-body">{deployDetail}</pre>
            <button className="hdr-btn" onClick={() => setShowDeployDetail(false)}>Close</button>
          </div>
        </div>
      )}
    </header>
  );
}
