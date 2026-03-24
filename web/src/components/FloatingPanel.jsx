/**
 * components/FloatingPanel.jsx — Draggable, resizable floating window
 *
 * Resize is implemented via a custom se-resize handle (not CSS resize: both)
 * for consistent cross-browser behavior including Safari.
 */

import { Suspense, useRef } from 'react';
import { useStore } from '../core/store';
import { useDraggable } from '../hooks/useDraggable';
import './FloatingPanel.css';

const MIN_W = 240;
const MIN_H = 80;

function useResizable({ w, h, onResize }) {
  const origin = useRef(null);

  function onResizeStart(e) {
    e.preventDefault();
    e.stopPropagation();

    const startX = e.touches ? e.touches[0].clientX : e.clientX;
    const startY = e.touches ? e.touches[0].clientY : e.clientY;
    origin.current = { startX, startY, startW: w, startH: h };

    function onMove(ev) {
      if (!origin.current) return;
      const cx = ev.touches ? ev.touches[0].clientX : ev.clientX;
      const cy = ev.touches ? ev.touches[0].clientY : ev.clientY;
      const newW = Math.max(MIN_W, origin.current.startW + (cx - origin.current.startX));
      const newH = Math.max(MIN_H, origin.current.startH + (cy - origin.current.startY));
      onResize(Math.round(newW), Math.round(newH));
    }

    function onUp() {
      origin.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup',   onUp);
      window.removeEventListener('touchmove', onMove);
      window.removeEventListener('touchend',  onUp);
    }

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup',   onUp);
    window.addEventListener('touchmove', onMove, { passive: false });
    window.addEventListener('touchend',  onUp);
  }

  return { onResizeStart };
}

export default function FloatingPanel({ panel }) {
  const { id, label, component: Component, x, y, w, h, minimized, zIndex } = panel;

  const closePanel    = useStore(s => s.closePanel);
  const minimizePanel = useStore(s => s.minimizePanel);
  const focusPanel    = useStore(s => s.focusPanel);
  const movePanelTo   = useStore(s => s.movePanelTo);
  const resizePanel   = useStore(s => s.resizePanel);

  const { onDragStart } = useDraggable({
    x, y,
    onMove:  (nx, ny) => movePanelTo(id, nx, ny),
    onFocus: ()       => focusPanel(id),
  });

  const { onResizeStart } = useResizable({
    w, h,
    onResize: (nw, nh) => resizePanel(id, nw, nh),
  });

  // Snapshot height before minimizing so restore returns to user's resized size
  const heightBeforeMinimize = useRef(h);
  function handleMinimize() {
    if (!minimized) heightBeforeMinimize.current = h;
    minimizePanel(id);
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
            onClick={handleMinimize}
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
          <Suspense fallback={<div className="fp-loading">Loading panel…</div>}>
            <Component />
          </Suspense>
        </div>
      )}

      {/* ── Resize handle ── */}
      {!minimized && (
        <div
          className="fp-resize-handle"
          onMouseDown={onResizeStart}
          onTouchStart={onResizeStart}
        />
      )}
    </div>
  );
}
