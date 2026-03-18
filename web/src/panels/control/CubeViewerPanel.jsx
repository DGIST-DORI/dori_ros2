import { useCallback, useState } from 'react';
import { useStore } from '../../core/store';
import '../../tabs/CubeTab.css';

// ── Constants ──────────────────────────────────────────────────────────────────

const FACE_ORDER  = ['U', 'R', 'F', 'D', 'L', 'B'];

const STICKER_CLASS = { W:'sticker-white', Y:'sticker-yellow', G:'sticker-green', B:'sticker-blue', R:'sticker-red', O:'sticker-orange' };

// ── Axis indicator (3D gizmo, orbit-synced) ───────────────────────────────────
function AxisIndicator({ orbitX, orbitY }) {
  const transform = `rotateX(${orbitX}deg) rotateY(${orbitY}deg)`;
  const labelTransform = `rotateY(${-orbitY}deg) rotateX(${-orbitX}deg)`;

  return (
    <div className="axis-gizmo-wrap">
      <div className="axis-gizmo" style={{ transform }}>
        <div className="axis-arm axis-arm-x"><span className="axis-label" style={{ transform: `${labelTransform} translateY(-50%)` }}>X</span></div>
        <div className="axis-arm axis-arm-y"><span className="axis-label" style={{ transform: `${labelTransform} translateY(-50%)` }}>Y</span></div>
        <div className="axis-arm axis-arm-z"><span className="axis-label" style={{ transform: `${labelTransform} translateY(-50%)` }}>Z</span></div>
        <span className="axis-origin" />
      </div>
    </div>
  );
}

// ── Viewer ─────────────────────────────────────────────────────────────────────
function CubeViewerPanel() {
  const cubeState = useStore((s) => s.cubeState);

  const [orbit,      setOrbit]      = useState({ x: -24, y: -32 });
  const [drag,       setDrag]       = useState(null);
  const [zoom,       setZoom]       = useState(1.0);
  const [showLabels, setShowLabels] = useState(false);
  const [showAxes,   setShowAxes]   = useState(false);

  const transform  = `scale(${zoom}) rotateX(${orbit.x}deg) rotateY(${orbit.y}deg)`;
  const clampZoom  = (z) => Math.max(0.4, Math.min(2.2, z));
  const zoomPct    = Math.round(zoom * 100);
  const zoomToSlider = (value) => {
    if (value <= 1) return ((value - 0.4) / 0.6) * 50;
    return 50 + ((value - 1) / 1.2) * 50;
  };
  const sliderToZoom = (value) => {
    if (value <= 50) return 0.4 + (value / 50) * 0.6;
    return 1 + ((value - 50) / 50) * 1.2;
  };
  const sliderValue = Math.round(zoomToSlider(zoom));

  const onPointerDown = (e) => {
    setDrag({ x: e.clientX, y: e.clientY, ox: orbit.x, oy: orbit.y });
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!drag) return;
    setOrbit({
      x: Math.max(-75, Math.min(75, drag.ox - (e.clientY - drag.y) * 0.35)),
      y: drag.oy + (e.clientX - drag.x) * 0.45,
    });
  };
  const onPointerUp = () => setDrag(null);

  const onWheel = useCallback((e) => {
    e.preventDefault();
    setZoom(z => clampZoom(z - e.deltaY * 0.001));
  }, []);

  const viewportRefCb = useCallback((el) => {
    if (!el) return;
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  return (
    <div className="cube-viewer-panel">
      <div
        ref={viewportRefCb}
        className="cube-viewport"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        role="presentation"
      >
        {/* 큐브 */}
        <div className="cube-3d" style={{ transform }}>
          {FACE_ORDER.map((face) => (
            <div key={face} className={`cube-face cube-face-${face}`}>
              {cubeState[face].map((sticker, i) => (
                <span key={`${face}-${i}`}
                  className={`cube-sticker ${STICKER_CLASS[sticker] || ''}`}
                  title={`${face}${i + 1}: ${sticker}`}
                />
              ))}
              {showLabels && <div className="cube-face-label">{face}</div>}
            </div>
          ))}
        </div>

        {/* 우측 상단 — 레이블 / 축 토글 버튼 */}
        <div className="vp-controls-tr" onPointerDown={e => e.stopPropagation()}>
          <button
            className={`vp-icon-btn ${showLabels ? 'active' : ''}`}
            onClick={() => setShowLabels(v => !v)}
            title="면 레이블 표시/숨기기"
          >
            <span className="vp-icon-text">LBL</span>
          </button>
          <button
            className={`vp-icon-btn ${showAxes ? 'active' : ''}`}
            onClick={() => setShowAxes(v => !v)}
            title="좌표축 표시/숨기기"
          >
            <span className="vp-icon-text">AXIS</span>
          </button>
        </div>

        {/* 좌측 하단 — 좌표축 인디케이터 */}
        {showAxes && (
          <div className="vp-axis-indicator" onPointerDown={e => e.stopPropagation()}>
            <AxisIndicator orbitX={orbit.x} orbitY={orbit.y} />
          </div>
        )}

        {/* 우측 하단 — 줌 컨트롤 바 */}
        <div className="vp-zoom-controls" onPointerDown={e => e.stopPropagation()}>
          <button className="vp-zoom-btn" onClick={() => setZoom(z => clampZoom(z + 0.15))} title="확대">＋</button>
          <div className="vp-zoom-track">
            <div className="vp-zoom-marker" title="100% 기준점" />
            <input
              type="range"
              className="vp-zoom-slider"
              min={0} max={100} step={1}
              value={sliderValue}
              onChange={e => setZoom(clampZoom(sliderToZoom(Number(e.target.value))))}
              title={`${zoomPct}%`}
            />
          </div>
          <button className="vp-zoom-btn" onClick={() => setZoom(z => clampZoom(z - 0.15))} title="축소">－</button>
          <button className="vp-zoom-reset" onClick={() => setZoom(1.0)} title="줌 리셋">{zoomPct}%</button>
        </div>
      </div>

      <div className="cube-viewer-help">드래그 orbit · 스크롤 zoom</div>
    </div>
  );
}

export default CubeViewerPanel;
export { CubeViewerPanel };
