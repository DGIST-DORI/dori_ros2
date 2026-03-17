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

/** Single leaf row */
function LeafItem({ node, activeId, onSelect, expanded }) {
  const isActive = activeId === node.id;
  const icon = isActive && node.iconActive ? node.iconActive : node.icon;

  return (
    <button
      className={`sb-leaf ${isActive ? 'active' : ''} ${node.placeholder ? 'placeholder' : ''}`}
      onClick={() => !node.placeholder && onSelect(node.id)}
      title={!expanded ? node.label : undefined}
      disabled={node.placeholder}
    >
      {icon && <span className="sb-leaf-icon">{icon}</span>}
      {expanded && (
        <span className="sb-leaf-label">
          {node.label}
          {node.placeholder && <span className="sb-placeholder-tag">soon</span>}
        </span>
      )}
      {!expanded && <span className="sb-tooltip">{node.label}{node.placeholder ? ' (soon)' : ''}</span>}
      {isActive && <span className="sb-active-bar" />}
    </button>
  );
}

/** Subcategory block (label may be null → flat) */
function SubcategoryBlock({ node, activeId, onSelect, expanded, forceOpen }) {
  const [open, setOpen] = useState(true);

  // When search is active, respect forceOpen
  const isOpen = forceOpen !== undefined ? forceOpen : open;

  if (!node.label) {
    // Flat — render leaves directly without a header
    return (
      <div className="sb-flat-group">
        {node.children.map(leaf => (
          <LeafItem key={leaf.id} node={leaf} activeId={activeId} onSelect={onSelect} expanded={expanded} />
        ))}
      </div>
    );
  }

  return (
    <div className="sb-subcategory">
      {expanded && (
        <button
          className="sb-subcat-header"
          onClick={() => setOpen(o => !o)}
        >
          <span className="sb-subcat-chevron">{isOpen ? '▾' : '▸'}</span>
          <span className="sb-subcat-label">{node.label}</span>
        </button>
      )}
      {(isOpen || !expanded) && (
        <div className="sb-subcat-leaves">
          {node.children.map(leaf => (
            <LeafItem key={leaf.id} node={leaf} activeId={activeId} onSelect={onSelect} expanded={expanded} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Top-level category block */
function CategoryBlock({ node, activeId, onSelect, expanded, searchActive }) {
  // Check if category contains the active leaf — auto-open in that case
  const containsActive = useMemo(() => {
    function check(nodes) {
      return nodes.some(n => n.id === activeId || (n.children && check(n.children)));
    }
    return check(node.children);
  }, [node, activeId]);

  const [open, setOpen] = useState(containsActive || node.id === 'hri');

  const isOpen = searchActive ? true : open;

  return (
    <div className={`sb-category ${isOpen ? 'open' : ''}`}>
      {/* Category header */}
      <button
        className="sb-cat-header"
        onClick={() => expanded && setOpen(o => !o)}
        title={!expanded ? node.label : undefined}
      >
        {node.icon && <span className="sb-cat-icon">{node.icon}</span>}
        {expanded && (
          <>
            <span className="sb-cat-label">{node.label}</span>
            <span className="sb-cat-chevron">{isOpen ? '▾' : '▸'}</span>
          </>
        )}
        {!expanded && <span className="sb-tooltip">{node.label}</span>}
      </button>

      {/* Children — only render when open and expanded */}
      {isOpen && expanded && (
        <div className="sb-cat-body">
          {node.children.map(sub => (
            <SubcategoryBlock
              key={sub.id}
              node={sub}
              activeId={activeId}
              onSelect={onSelect}
              expanded={expanded}
              forceOpen={searchActive ? true : undefined}
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
