/**
 * components/FloatingPanel.jsx — Draggable, resizable floating window
 *
 * Renders a single open panel entry from the floatingPanels store.
 * Title bar: drag handle | label | minimize | close
 * Body: the leaf's component, rendered inside a scrollable container
 * Resize: native CSS resize handle (bottom-right corner)
 */

import { useEffect, useRef } from 'react';
import { useStore } from '../core/store';
import { useDraggable } from '../hooks/useDraggable';
import './FloatingPanel.css';

export default function FloatingPanel({ panel }) {
  const { id, label, component: Component, x, y, w, h, minimized, zIndex } = panel;

  const closePanel    = useStore(s => s.closePanel);
  const minimizePanel = useStore(s => s.minimizePanel);
  const focusPanel    = useStore(s => s.focusPanel);
  const movePanelTo   = useStore(s => s.movePanelTo);
  const resizePanel   = useStore(s => s.resizePanel);

  const windowRef = useRef(null);

  const { onDragStart } = useDraggable({
    x, y,
    onMove:  (nx, ny) => movePanelTo(id, nx, ny),
    onFocus: ()       => focusPanel(id),
  });

  // ResizeObserver — syncs w/h to store whenever the window element is resized
  // (works with CSS resize: both on fp-window)
  useEffect(() => {
    const el = windowRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      resizePanel(id, Math.round(width), Math.round(height));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [id, resizePanel]);

  return (
    <div
      ref={windowRef}
      className={`fp-window ${minimized ? 'minimized' : ''}`}
      style={{ left: x, top: y, width: w, height: minimized ? 'auto' : h, zIndex }}
      onMouseDown={() => focusPanel(id)}
    >
      {/* ── Title bar ── */}
      <div
        className="fp-titlebar"
        onMouseDown={onDragStart}
        onTouchStart={onDragStart}
      >
        <span className="fp-title">{label}</span>
        <div className="fp-controls">
          <button
            className="fp-btn fp-btn-minimize"
            onMouseDown={e => e.stopPropagation()}
            onClick={() => minimizePanel(id)}
            title={minimized ? 'Restore' : 'Minimize'}
          >
            {minimized ? '▲' : '▼'}
          </button>
          <button
            className="fp-btn fp-btn-close"
            onMouseDown={e => e.stopPropagation()}
            onClick={() => closePanel(id)}
            title="Close"
          >
            ×
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      {!minimized && (
        <div className="fp-body">
          <Component />
        </div>
      )}
    </div>
  );
}
