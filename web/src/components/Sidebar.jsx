/**
 * components/Sidebar.jsx — Tree-structured panel navigator
 *
 * Collapsed: icon-only rail (48px), tooltip on hover
 * Expanded:  search bar + 2-level collapsible tree
 *
 * Tree depth: category → subcategory → leaf (max 2 visible levels)
 * Subcategories with label=null are rendered flat (no header row).
 */

import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { useStore } from '../core/store';
import { filterTree } from '../panelTree';
import SidebarIcon from '../assets/icons/icon-sidebar.svg?react';
import CloseIcon   from '../assets/icons/icon-close.svg?react';
import './Sidebar.css';

// ── Sub-components ────────────────────────────────────────────────────────────

/** Single leaf row — brief click flash only, no persistent highlight */
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
      {node.icon && <span className="sb-leaf-icon">{node.icon}</span>}
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

/** Subcategory block (label may be null → flat) */
function SubcategoryBlock({ node, onSelect, expanded }) {
  const [open, setOpen] = useState(false);  // default: closed

  if (!node.label) {
    // Flat — render leaves directly without a header
    return (
      <div className="sb-flat-group">
        {node.children.map(leaf => (
          <LeafItem key={leaf.id} node={leaf} onSelect={onSelect} expanded={expanded} />
        ))}
      </div>
    );
  }

  return (
    <div className="sb-subcategory">
      {expanded && (
        <button className="sb-subcat-header" onClick={() => setOpen(o => !o)}>
          <span className="sb-subcat-chevron">{open ? '▾' : '▸'}</span>
          <span className="sb-subcat-label">{node.label}</span>
        </button>
      )}
      {(open || !expanded) && (
        <div className="sb-subcat-leaves">
          {node.children.map(leaf => (
            <LeafItem key={leaf.id} node={leaf} onSelect={onSelect} expanded={expanded} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Top-level category block */
function CategoryBlock({ node, onSelect, expanded }) {
  const [open, setOpen] = useState(false);  // default: closed

  return (
    <div className={`sb-category ${open ? 'open' : ''}`}>
      <button
        className="sb-cat-header"
        onClick={() => expanded && setOpen(o => !o)}
        title={!expanded ? node.label : undefined}
      >
        {node.icon && <span className="sb-cat-icon">{node.icon}</span>}
        {expanded && (
          <>
            <span className="sb-cat-label">{node.label}</span>
            <span className="sb-cat-chevron">{open ? '▾' : '▸'}</span>
          </>
        )}
        {!expanded && <span className="sb-tooltip">{node.label}</span>}
      </button>

      {open && expanded && (
        <div className="sb-cat-body">
          {node.children.map(sub => (
            <SubcategoryBlock
              key={sub.id}
              node={sub}
              onSelect={onSelect}
              expanded={expanded}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main Sidebar ──────────────────────────────────────────────────────────────

export default function Sidebar({
  expanded,
  onExpand,
  onCollapse,
  activeId,
  onSelect,
  tree,
}) {
  const connected   = useStore(s => s.connected);
  const isDemoMode  = useStore(s => s.isDemoMode);
  const statusLabel = connected ? 'LIVE' : isDemoMode ? 'DEMO' : 'OFF';
  const statusClass = connected ? 'connected' : isDemoMode ? 'demo' : '';

  const [query, setQuery] = useState('');
  const searchActive = query.trim().length > 0;

  const visibleTree = useMemo(
    () => filterTree(tree, query),
    [tree, query],
  );

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
              <span className="sb-logo-mark">◎</span>
              <span className="sb-logo-text">DORI</span>
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
            <SidebarIcon />
            <span className="sb-tooltip">Open sidebar</span>
          </button>
        )}
      </div>

      {/* ── Search (expanded only) ── */}
      {expanded && (
        <div className="sb-search-wrap">
          <Search size={12} className="sb-search-icon" />
          <input
            className="sb-search-input"
            type="text"
            placeholder="Search panels..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            onClick={e => e.stopPropagation()}
          />
          {searchActive && (
            <button className="sb-search-clear" onClick={() => setQuery('')}>×</button>
          )}
        </div>
      )}

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
            onSelect={id => { onSelect(id); }}
            expanded={expanded}
            searchActive={searchActive}
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
