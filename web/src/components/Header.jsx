import { useState, useEffect } from 'react';
import { LOG_TAGS, useStore } from '../core/store';
import { connectROS, disconnectROS } from '../core/ros';
import { startDemo, stopDemo } from '../core/demo';
import './Header.css';

export default function Header({ onLogoClick, themeMode, onThemeModeChange }) {
  const connected    = useStore(s => s.connected);
  const isDemoMode   = useStore(s => s.isDemoMode);
  const wsUrl        = useStore(s => s.wsUrl);
  const setConnected = useStore(s => s.setConnected);
  const setWsUrl     = useStore(s => s.setWsUrl);
  const addLog       = useStore(s => s.addLog);

  const [urlInput, setUrlInput] = useState(wsUrl);
  const [isConnecting, setIsConnecting] = useState(false);

  // 터널 URL 폴링이 완료되면 wsUrl store 가 업데이트됨 → 입력창도 동기화
  // 단, 사용자가 직접 입력 중이거나 연결된 상태면 덮어쓰지 않음
  useEffect(() => {
    if (!connected && !isConnecting) {
      setUrlInput(wsUrl);
    }
  }, [wsUrl]);

  function formatConnectError(error, url, source = 'network') {
    const message = String(error?.message || error || 'Unknown error');
    const eventType = error?.type;
    const target = error?.target;
    const readyState = target?.readyState;
    const stateLabel = readyState === undefined
      ? 'n/a'
      : ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'][readyState] || String(readyState);
    const debugParts = [
      `url=${url || 'n/a'}`,
      `eventType=${eventType || 'n/a'}`,
      `readyState=${stateLabel}`,
      `message=${message}`,
    ];

    if (source === 'url') {
      return `Connection failed [url]: Invalid WebSocket URL. ${debugParts.join(', ')}. Use ws:// or wss://.`;
    }
    if (source === 'loading' || message.includes('ROSLIB is unavailable') || message.includes('Failed to fetch')) {
      return `Connection failed [loading]: Failed to load ROS client library. ${debugParts.join(', ')}`;
    }
    return `Connection failed [network]: Could not open WebSocket. ${debugParts.join(', ')}`;
  }

  async function handleConnect() {
    if (isConnecting) return;

    if (connected) {
      disconnectROS(); setConnected(false); addLog(LOG_TAGS.SYS, 'Disconnected from ROS');
    } else {
      try {
        // quick URL sanity check for clearer user-facing errors
        const parsed = new URL(urlInput);
        if (!['ws:', 'wss:'].includes(parsed.protocol)) {
          throw new Error('URL protocol must be ws:// or wss://');
        }

        setIsConnecting(true);
        setConnected(false);
        stopDemo();
        await connectROS(urlInput, {
          onConnect: () => {
            setConnected(true);
            setIsConnecting(false);
            addLog(LOG_TAGS.SYS, `Connected → ${urlInput}`);
          },
          onError: (e) => {
            setConnected(false);
            setIsConnecting(false);
            addLog(LOG_TAGS.ERROR, formatConnectError(e, urlInput, 'network'));
          },
          onClose: () => {
            setConnected(false);
            setIsConnecting(false);
            addLog(LOG_TAGS.SYS, 'Connection closed');
          },
        });
        setWsUrl(urlInput);
      } catch (e) {
        const source = e instanceof TypeError || e.message?.includes('protocol') ? 'url' : 'loading';
        setConnected(false);
        setIsConnecting(false);
        addLog(LOG_TAGS.ERROR, formatConnectError(e, urlInput, source));
      }
    }
  }

  function handleDemo() {
    if (isDemoMode) stopDemo();
    else { disconnectROS(); setConnected(false); startDemo(); }
  }

  return (
    <header className="hdr">
      {/* Logo — click to go Home */}
      <button className="hdr-logo" onClick={onLogoClick}>
        <span className="hdr-logo-dori">DORI</span>
        <span className="hdr-logo-sep">/</span>
        <span className="hdr-logo-sub">dashboard</span>
      </button>

      <div className="hdr-spacer" />

      <div className="hdr-conn">
        <label className="hdr-theme-wrap">
          <span className="hdr-theme-label">theme</span>
          <select
            className="hdr-theme"
            value={themeMode}
            onChange={e => onThemeModeChange(e.target.value)}
          >
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
          {isConnecting ? 'connecting...' : (connected ? '⏏ disconnect' : '⏎ connect')}
        </button>
        <button className={`hdr-btn demo ${isDemoMode ? 'active' : ''}`} onClick={handleDemo}>
          {isDemoMode ? '■ stop demo' : '▶ demo'}
        </button>
      </div>
    </header>
  );
}
