/**
 * components/FloatingWorkspace.jsx
 *
 * Desktop: absolute-positioned container that fills app-main.
 *          Renders all open FloatingPanel windows.
 * Mobile:  stacked layout — panels rendered in open order, no dragging.
 */

import { useStore } from '../core/store';
import FloatingPanel from './FloatingPanel';
import MobileStack   from './MobileStack';
import './FloatingWorkspace.css';

export default function FloatingWorkspace({ isMobile }) {
  const openPanels = useStore(s => s.openPanels);

  if (openPanels.length === 0) {
    return (
      <div className="fw-empty">
        <span className="fw-empty-hint">← 사이드바에서 패널을 선택하세요</span>
      </div>
    );
  }

  if (isMobile) {
    return <MobileStack panels={openPanels} />;
  }

  return (
    <div className="fw-workspace">
      {openPanels.map(panel => (
        <FloatingPanel key={panel.id} panel={panel} />
      ))}
    </div>
  );
}
