import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../core/store';
import { filterTree } from '../panelTree';
import DoriLogoIcon from '../assets/logo/logo-icon.svg?react';
import DoriLogoFull from '../assets/logo/logo-full.svg?react';
import DoriLogoFullDark from '../assets/logo/logo-full-dark.svg?react';
import CloseIcon    from '../assets/icons/icon-close.svg?react';
import SearchIcon   from '../assets/icons/icon-search.svg?react';
import './Sidebar.css';

// ── Sub-components ────────────────────────────────────────────────────────────

function LeafItem({ node, onSelect, expanded }) {
  const [flashing, setFlashing] = useState(false);

  function handleClick() {
    if (node.placeholder) return;
    setFlashing(true);
    setTimeout(() => setFlashing(false), 220);
    onSelect(node.id);
  }

  return (
    <button
      className={`sb-leaf ${node.placeholder ? 'placeholder' : ''} ${flashing ? 'flash' : ''}`}
      onClick={handleClick}
      title={!expanded ? node.label : undefined}
      disabled={node.placeholder}
    >
      {expanded && (
        <span className="sb-leaf-label">
          {node.label}
          {node.placeholder && <span className="sb-placeholder-tag">soon</span>}
        </span>
      )}
      {!expanded && <span className="sb-tooltip">{node.label}{node.placeholder ? ' (soon)' : ''}</span>}
    </button>
  );
}

function SubcategoryBlock({ node, onSelect, expanded, searchActive }) {
  const [open, setOpen] = useState(false);
  const isOpen = searchActive ? true : open;

  if (!node.label) {
    return (
      <div className="sb-flat-group">
        {node.children.map(leaf => (
          <LeafItem key={leaf.id} node={leaf} onSelect={onSelect} expanded={expanded} />
        ))}
      </div>
    );
  }

  return (
    <div className={`sb-subcategory ${isOpen ? 'open' : ''}`}>
      {expanded && (
        <button className="sb-subcat-header" onClick={() => !searchActive && setOpen(o => !o)}>
          {node.icon && <span className="sb-subcat-icon">{node.icon}</span>}
          <span className="sb-subcat-label">{node.label}</span>
          <span className="sb-subcat-chevron">▾</span>
        </button>
      )}
      <div className="sb-subcat-leaves">
        <div className="sb-subcat-leaves-inner">
          {node.children.map(leaf => (
            <LeafItem key={leaf.id} node={leaf} onSelect={onSelect} expanded={expanded} />
          ))}
        </div>
      </div>
    </div>
  );
}

function CategoryBlock({ node, onSelect, expanded, searchActive, onExpandSidebar }) {
  const [open, setOpen] = useState(false);
  const isOpen = searchActive ? true : open;

  function handleHeaderClick() {
    if (!expanded) { onExpandSidebar(); setOpen(true); }
    else if (!searchActive) setOpen(o => !o);
  }

  return (
    <div className={`sb-category ${isOpen ? 'open' : ''}`}>
      <button
        className="sb-cat-header"
        onClick={handleHeaderClick}
        title={!expanded ? node.label : undefined}
      >
        {node.icon && <span className="sb-cat-icon">{node.icon}</span>}
        {expanded && (
          <>
            <span className="sb-cat-label">{node.label}</span>
            <span className="sb-cat-chevron">▾</span>
          </>
        )}
        {!expanded && <span className="sb-tooltip">{node.label}</span>}
      </button>

      {expanded && (
        <div className="sb-cat-body">
          <div className="sb-cat-body-inner">
            {node.children.map(sub => (
              <SubcategoryBlock
                key={sub.id}
                node={sub}
                onSelect={onSelect}
                expanded={expanded}
                searchActive={searchActive}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Sidebar ──────────────────────────────────────────────────────────────

export default function Sidebar({ expanded, onExpand, onCollapse, activeId, onSelect, tree }) {
  const connected   = useStore(s => s.connected);
  const isDemoMode  = useStore(s => s.isDemoMode);
  const themeMode   = typeof window !== 'undefined'
    ? (localStorage.getItem('theme-mode') || 'auto')
    : 'auto';

  const statusLabel = connected ? 'LIVE' : isDemoMode ? 'DEMO' : 'OFF';
  const statusClass = connected ? 'connected' : isDemoMode ? 'demo' : '';

  // Resolve dark/light for logo variant
  const [isDark, setIsDark] = useState(() => {
    if (themeMode === 'dark') return true;
    if (themeMode === 'light') return false;
    return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  useEffect(() => {
    const stored = localStorage.getItem('theme-mode') || 'auto';
    if (stored !== 'auto') { setIsDark(stored === 'dark'); return; }
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = e => setIsDark(e.matches);
    setIsDark(mq.matches);
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  const [query,        setQuery]        = useState('');
  const [pendingFocus, setPendingFocus] = useState(false);
  const searchInputRef = useRef(null);
  const searchActive   = query.trim().length > 0;

  const visibleTree = useMemo(() => filterTree(tree, query), [tree, query]);

  useEffect(() => {
    if (expanded && pendingFocus) {
      searchInputRef.current?.focus();
      setPendingFocus(false);
    }
  }, [expanded, pendingFocus]);

  const FullLogo = isDark ? DoriLogoFullDark : DoriLogoFull;

  return (
    <aside
      className={`sidebar ${expanded ? 'expanded' : 'collapsed'}`}
      onClick={() => !expanded && onExpand()}
    >
      {/* ── Top: logo / toggle ── */}
      <div className="sb-top">
        {expanded ? (
          <>
            <div className="sb-logo">
              <FullLogo className="sb-logo-svg" aria-label="DORI" />
            </div>
            <button
              className="sb-close"
              onClick={e => { e.stopPropagation(); onCollapse(); }}
              title="Close sidebar"
            >
              <CloseIcon />
            </button>
          </>
        ) : (
          <button
            className="sb-open"
            onClick={e => { e.stopPropagation(); onExpand(); }}
          >
            <DoriLogoIcon className="sb-icon-svg" />
            <span className="sb-tooltip">Open sidebar</span>
          </button>
        )}
      </div>

      {/* ── Search ── */}
      <div className="sb-search-cell" onClick={e => e.stopPropagation()}>
        {expanded ? (
          <div className="sb-search-wrap">
            <SearchIcon className="sb-search-icon" />
            <input
              ref={searchInputRef}
              className="sb-search-input"
              type="text"
              placeholder="Search panels..."
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
            {searchActive && (
              <button className="sb-search-clear" onClick={() => setQuery('')}>×</button>
            )}
          </div>
        ) : (
          <button
            className="sb-search-btn"
            onClick={() => { onExpand(); setPendingFocus(true); }}
            title="Search panels"
          >
            <SearchIcon className="sb-search-btn-icon" />
            <span className="sb-tooltip">Search panels</span>
          </button>
        )}
      </div>

      {/* ── Nav tree ── */}
      <nav className="sb-nav" onClick={e => e.stopPropagation()}>
        {visibleTree.length === 0 && expanded && (
          <div className="sb-empty">No panels found</div>
        )}
        {visibleTree.map(category => (
          <CategoryBlock
            key={category.id}
            node={category}
            activeId={activeId}
            onSelect={id => onSelect(id)}
            expanded={expanded}
            searchActive={searchActive}
            onExpandSidebar={onExpand}
          />
        ))}
      </nav>

      {/* ── Bottom: connection status ── */}
      <div className="sb-bottom">
        <div className={`sb-status ${statusClass}`}>
          <div className="sb-status-dot" />
          {expanded  && <span className="sb-status-label">{statusLabel}</span>}
          {!expanded && <span className="sb-tooltip sb-tooltip-status">{statusLabel}</span>}
        </div>
      </div>
    </aside>
  );
}
