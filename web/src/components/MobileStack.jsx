/**
 * components/MobileStack.jsx — Mobile panel layout
 *
 * Panels stack vertically in open order.
 * Each panel has a collapsible header (tap to toggle).
 * No dragging, no z-index management.
 */

import { useStore } from '../core/store';
import './MobileStack.css';

function MobilePanel({ panel }) {
  const { id, label, component: Component, minimized } = panel;
  const minimizePanel = useStore(s => s.minimizePanel);
  const closePanel    = useStore(s => s.closePanel);

  return (
    <div className={`ms-panel ${minimized ? 'minimized' : ''}`}>
      <div className="ms-titlebar">
        <span className="ms-title">{label}</span>
        <div className="ms-controls">
          <button
            className="ms-btn"
            onClick={() => minimizePanel(id)}
            title={minimized ? 'Expand' : 'Collapse'}
          >
            {minimized ? '▲' : '▼'}
          </button>
          <button
            className="ms-btn ms-btn-close"
            onClick={() => closePanel(id)}
            title="Close"
          >
            ×
          </button>
        </div>
      </div>
      {!minimized && (
        <div className="ms-body">
          <Component />
        </div>
      )}
    </div>
  );
}

export default function MobileStack({ panels }) {
  return (
    <div className="ms-stack">
      {panels.map(panel => (
        <MobilePanel key={panel.id} panel={panel} />
      ))}
    </div>
  );
}
