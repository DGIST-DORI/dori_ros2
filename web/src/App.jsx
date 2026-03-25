import { useState, useEffect } from 'react';
import Header             from './components/Header';
import Sidebar            from './components/Sidebar';
import FloatingWorkspace  from './components/FloatingWorkspace';
import { useStore, TOPIC_META } from './core/store';
import { fetchTopicDiagnostics, subscribeROS } from './core/ros';
import { PANEL_TREE, findLeaf } from './panelTree';

import './index.css';
import './App.css';

const MOBILE_BP = 768;

export default function App() {
  const [sidebarExpanded,  setSidebarExpanded]  = useState(false);
  const [isOverlaySidebar, setIsOverlaySidebar] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia(`(max-width: ${MOBILE_BP}px)`).matches
  );
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia(`(max-width: ${MOBILE_BP}px)`).matches
  );
  const [themeMode, setThemeMode] = useState(
    () => localStorage.getItem('theme-mode') || 'auto'
  );

  const connected        = useStore(s => s.connected);
  const handleROSMessage = useStore(s => s.handleROSMessage);
  const setTopicMeta     = useStore(s => s.setTopicMeta);
  const openPanel        = useStore(s => s.openPanel);

  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    fetchTopicDiagnostics(Object.keys(TOPIC_META))
      .then(metaMap => {
        if (cancelled) return;
        Object.entries(metaMap).forEach(([topic, meta]) => setTopicMeta(topic, meta));
      })
      .catch(() => {});
    const unsubs = Object.keys(TOPIC_META).map(topic =>
      subscribeROS(topic, undefined, (_, rawMsg) => handleROSMessage(topic, rawMsg))
    );
    return () => { cancelled = true; unsubs.forEach(fn => fn()); };
  }, [connected, handleROSMessage, setTopicMeta]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => {
      document.documentElement.dataset.theme =
        themeMode === 'auto' ? (mq.matches ? 'dark' : 'light') : themeMode;
    };
    apply();
    localStorage.setItem('theme-mode', themeMode);
    if (themeMode !== 'auto') return;
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [themeMode]);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_BP}px)`);
    const apply = (e) => {
      const mobile = typeof e?.matches === 'boolean' ? e.matches : mq.matches;
      setIsOverlaySidebar(mobile);
      setIsMobile(mobile);
    };
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  function handlePanelSelect(id) {
    const leaf = findLeaf(PANEL_TREE, id);
    if (!leaf || leaf.placeholder) return;
    // Settings panel receives themeMode + setter via openPanel component prop injection
    openPanel(leaf);
    if (isOverlaySidebar) setSidebarExpanded(false);
  }

  function handleSettingsOpen() {
    // Find and open the settings leaf, injecting themeMode props
    const leaf = findLeaf(PANEL_TREE, 'settings');
    if (!leaf) return;
    // We pass themeMode down via a wrapper component stored in the leaf
    openPanel({
      ...leaf,
      // The SettingsPanel reads themeMode from the leaf's extraProps
      _themeMode: themeMode,
      _onThemeModeChange: setThemeMode,
    });
    if (isOverlaySidebar) setSidebarExpanded(false);
  }

  return (
    <div className={`app ${sidebarExpanded ? 'sb-expanded' : ''} ${isOverlaySidebar ? 'sb-overlay' : ''}`}>
      <div className="app-sidebar">
        <Sidebar
          themeMode={themeMode}
          onThemeModeChange={setThemeMode}
          expanded={sidebarExpanded}
          onExpand={() => setSidebarExpanded(true)}
          onCollapse={() => setSidebarExpanded(false)}
          onSelect={handlePanelSelect}
          onSettingsOpen={handleSettingsOpen}
          tree={PANEL_TREE}
        />
      </div>

      {isOverlaySidebar && sidebarExpanded && (
        <button
          className="app-sidebar-backdrop"
          type="button"
          aria-label="Close sidebar"
          onClick={() => setSidebarExpanded(false)}
        />
      )}

      <div className="app-header">
        <Header
          themeMode={themeMode}
          onThemeModeChange={setThemeMode}
          sidebarExpanded={sidebarExpanded}
        />
      </div>

      <main className="app-main">
        <FloatingWorkspace isMobile={isMobile} themeMode={themeMode} onThemeModeChange={setThemeMode} />
      </main>
    </div>
  );
}
