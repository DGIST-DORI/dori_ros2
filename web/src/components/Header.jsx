import { useState, useEffect } from 'react';
import { LOG_TAGS, useStore } from '../core/store';
import { connectROS, disconnectROS } from '../core/ros';
import { startDemo, stopDemo } from '../core/demo';
import DoriLogoFull     from '../assets/logo/logo-full.svg?react';
import DoriLogoFullDark from '../assets/logo/logo-full-dark.svg?react';
import './Header.css';

export default function Header({ onLogoClick, themeMode, onThemeModeChange }) {
  const connected    = useStore(s => s.connected);
  const isDemoMode   = useStore(s => s.isDemoMode);
  const wsUrl        = useStore(s => s.wsUrl);
  const setConnected = useStore(s => s.setConnected);
  const setWsUrl     = useStore(s => s.setWsUrl);
  const addLog       = useStore(s => s.addLog);

  const [urlInput,     setUrlInput]     = useState(wsUrl);
  const [isConnecting, setIsConnecting] = useState(false);

  // Sync URL input when wsUrl store updates externally (tunnel detection)
  useEffect(() => {
    if (!connected && !isConnecting) setUrlInput(wsUrl);
  }, [wsUrl]);

  // Resolve which logo variant to render based on active theme
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    const apply = () => {
      if (themeMode === 'auto') {
        setIsDark(window.matchMedia('(prefers-color-scheme: dark)').matches);
      } else {
        setIsDark(themeMode === 'dark');
      }
    };
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

  const LogoComponent = isDark ? DoriLogoFullDark : DoriLogoFull;

  return (
    <header className="hdr">
      <button className="hdr-logo" onClick={onLogoClick} aria-label="DORI Dashboard home">
        <LogoComponent className="hdr-logo-svg" aria-hidden="true" />
      </button>

      <div className="hdr-spacer" />

      <div className="hdr-conn">
        <label className="hdr-theme-wrap">
          <span className="hdr-theme-label">theme</span>
          <select className="hdr-theme" value={themeMode} onChange={e => onThemeModeChange(e.target.value)}>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
            <option value="auto">Automatic</option>
          </select>
        </label>

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
          {isConnecting ? 'connecting...' : connected ? '⏏ disconnect' : '⏎ connect'}
        </button>
        <button className={`hdr-btn demo ${isDemoMode ? 'active' : ''}`} onClick={handleDemo}>
          {isDemoMode ? '■ stop demo' : '▶ demo'}
        </button>
      </div>
    </header>
  );
}
