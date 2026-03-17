/**
 * components/FloatingPanel.jsx — Draggable, resizable floating window
 *
 * Renders a single open panel entry from the floatingPanels store.
 * Title bar: drag handle | label | minimize | close
 * Body: the leaf's component, rendered inside a scrollable container
 * Resize: native CSS resize handle (bottom-right corner)
 */

import { useRef } from 'react';
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

  const bodyRef = useRef(null);

  const { onDragStart } = useDraggable({
    x, y,
    onMove:  (nx, ny) => movePanelTo(id, nx, ny),
    onFocus: ()       => focusPanel(id),
  });

  // Resize observer — sync w/h back to store after user drags the resize handle
  function onResizeMouseDown() {
    function onUp() {
      if (bodyRef.current) {
        const rect = bodyRef.current.closest('.fp-window').getBoundingClientRect();
        resizePanel(id, Math.round(rect.width), Math.round(rect.height));
      }
      window.removeEventListener('mouseup', onUp);
    }
    window.addEventListener('mouseup', onUp);
  }

  return (
    <div
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
        <div className="fp-body" ref={bodyRef}>
          <Component />
        </div>
      )}

      {/* ── Resize handle (bottom-right) ── */}
      {!minimized && (
        <div className="fp-resize-handle" onMouseDown={onResizeMouseDown} />
      )}
    </div>
  );
}
