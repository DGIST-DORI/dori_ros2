/**
 * tabs/CubeTab.jsx  —  Cube Simulator (improved)
 *
 * Changes from original:
 *  1. Rotation buttons redesigned to match dashboard design system
 *  2. Sequence text input + copy-to-clipboard for history
 *  3. Scroll-wheel zoom + +/- buttons in viewer
 *  4. Face direction labels overlay (toggleable)
 *  5. Piece State: face filter toggles, search, Face&Idx ↔ Coord mode
 */
import { useMemo, useState, useRef, useCallback } from 'react';
import Panel from '../components/Panel';
import { useStore } from '../core/store';
import './CubeTab.css';

// ── Constants ─────────────────────────────────────────────────────────────────

const FACE_ORDER = ['U', 'R', 'F', 'D', 'L', 'B'];

// Face → sticker index → [x, y, z] coordinate
// Mapping derived from solved cube layout (center = origin)
const FACE_COORD = {
  U: [ [-1,1,-1],[0,1,-1],[1,1,-1], [-1,1,0],[0,1,0],[1,1,0], [-1,1,1],[0,1,1],[1,1,1] ],
  D: [ [-1,-1,1],[0,-1,1],[1,-1,1], [-1,-1,0],[0,-1,0],[1,-1,0], [-1,-1,-1],[0,-1,-1],[1,-1,-1] ],
  F: [ [-1,1,1],[0,1,1],[1,1,1],  [-1,0,1],[0,0,1],[1,0,1],  [-1,-1,1],[0,-1,1],[1,-1,1] ],
  B: [ [1,1,-1],[0,1,-1],[-1,1,-1],[1,0,-1],[0,0,-1],[-1,0,-1],[1,-1,-1],[0,-1,-1],[-1,-1,-1] ],
  R: [ [1,1,1],[1,1,0],[1,1,-1],  [1,0,1],[1,0,0],[1,0,-1],  [1,-1,1],[1,-1,0],[1,-1,-1] ],
  L: [ [-1,1,-1],[-1,1,0],[-1,1,1],[-1,0,-1],[-1,0,0],[-1,0,1],[-1,-1,-1],[-1,-1,0],[-1,-1,1] ],
};

const STICKER_CLASS = {
  W: 'sticker-white',
  Y: 'sticker-yellow',
  G: 'sticker-green',
  B: 'sticker-blue',
  R: 'sticker-red',
  O: 'sticker-orange',
};

const COLOR_LABEL = { W:'White', Y:'Yellow', G:'Green', B:'Blue', R:'Red', O:'Orange' };

const MOVE_BUTTONS = [
  ['U', "U'"],
  ['R', "R'"],
  ['L', "L'"],
  ['B', "B'"],
];

// Face label positions in the 3D CSS cube (centred on each face)
const FACE_LABELS = [
  { face: 'U', cls: 'cube-face-U', label: 'U (top)' },
  { face: 'D', cls: 'cube-face-D', label: 'D (bot)' },
  { face: 'F', cls: 'cube-face-F', label: 'F (front)' },
  { face: 'B', cls: 'cube-face-B', label: 'B (back)' },
  { face: 'R', cls: 'cube-face-R', label: 'R (right)' },
  { face: 'L', cls: 'cube-face-L', label: 'L (left)' },
];

const VALID_MOVES = new Set(['U', "U'", 'R', "R'", 'L', "L'", 'B', "B'"]);

// ── Sub-components ────────────────────────────────────────────────────────────

function CubeViewerPanel() {
  const cubeState   = useStore((s) => s.cubeState);
  const [orbit,     setOrbit]     = useState({ x: -24, y: -32 });
  const [drag,      setDrag]      = useState(null);
  const [zoom,      setZoom]      = useState(1.0);
  const [showLabels,setShowLabels]= useState(true);
  const viewportRef = useRef(null);

  const transform = `scale(${zoom}) rotateX(${orbit.x}deg) rotateY(${orbit.y}deg)`;

  const clampZoom = (z) => Math.max(0.45, Math.min(2.0, z));

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

  // Attach wheel listener non-passively so preventDefault works
  const viewportRefCb = useCallback((el) => {
    if (!el) return;
    viewportRef.current = el;
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  return (
    <div className="cube-viewer-panel">
      {/* Zoom + label controls */}
      <div className="cube-viewer-toolbar">
        <div className="cube-zoom-controls">
          <button className="cube-toolbar-btn" onClick={() => setZoom(z => clampZoom(z + 0.15))} title="확대">＋</button>
          <span className="cube-zoom-label">{Math.round(zoom * 100)}%</span>
          <button className="cube-toolbar-btn" onClick={() => setZoom(z => clampZoom(z - 0.15))} title="축소">－</button>
          <button className="cube-toolbar-btn" onClick={() => setZoom(1.0)} title="리셋">⊙</button>
        </div>
        <button
          className={`cube-toolbar-btn label-toggle ${showLabels ? 'active' : ''}`}
          onClick={() => setShowLabels(v => !v)}
          title="방향 레이블 표시/숨기기"
        >
          {showLabels ? '🏷 labels on' : '🏷 labels off'}
        </button>
      </div>

      <div
        ref={viewportRefCb}
        className="cube-viewport"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        role="presentation"
      >
        <div className="cube-3d" style={{ transform }}>
          {FACE_ORDER.map((face) => (
            <div key={face} className={`cube-face cube-face-${face}`}>
              {cubeState[face].map((sticker, i) => (
                <span
                  key={`${face}-${i}`}
                  className={`cube-sticker ${STICKER_CLASS[sticker] || ''}`}
                  title={`${face}${i + 1}: ${sticker}`}
                />
              ))}
              {showLabels && (
                <div className="cube-face-label">{face}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="cube-viewer-help">드래그 orbit · 스크롤 zoom</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function PieceStatePanel() {
  const cubeState = useStore((s) => s.cubeState);

  const [activeFaces, setActiveFaces] = useState(new Set(FACE_ORDER));
  const [search,      setSearch]      = useState('');
  const [coordMode,   setCoordMode]   = useState(false); // false=Face&Idx, true=Coord

  const toggleFace = (face) => setActiveFaces(prev => {
    const next = new Set(prev);
    if (next.has(face)) { if (next.size > 1) next.delete(face); }
    else next.add(face);
    return next;
  });

  const rows = useMemo(() => {
    const q = search.trim().toUpperCase();
    return FACE_ORDER.flatMap((face) =>
      cubeState[face].map((color, idx) => ({
        face,
        index: idx + 1,
        color,
        coord: FACE_COORD[face][idx],
      }))
    ).filter(row =>
      activeFaces.has(row.face) &&
      (!q || row.face.includes(q) || COLOR_LABEL[row.color]?.toUpperCase().includes(q) || row.color.includes(q) ||
        String(row.index).includes(q) ||
        (coordMode && row.coord.join(',').includes(q))
      )
    );
  }, [cubeState, activeFaces, search, coordMode]);

  return (
    <div className="piece-state-panel">
      {/* Face filter toggles */}
      <div className="piece-filter-row">
        {FACE_ORDER.map(f => (
          <button
            key={f}
            className={`piece-face-btn ${activeFaces.has(f) ? 'active' : ''}`}
            onClick={() => toggleFace(f)}
            title={`${f} 면 필터`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Search + mode toggle */}
      <div className="piece-search-row">
        <input
          className="piece-search-input"
          placeholder="search…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <button
          className={`piece-mode-btn ${coordMode ? 'active' : ''}`}
          onClick={() => setCoordMode(v => !v)}
          title="Face&Idx / 좌표 전환"
        >
          {coordMode ? 'xyz' : 'F&I'}
        </button>
      </div>

      {/* Table */}
      <div className="piece-table-wrap">
        <table className="piece-table">
          <thead>
            <tr>
              {coordMode
                ? <><th>x,y,z</th><th>Face</th><th>Color</th></>
                : <><th>Face</th><th>Idx</th><th>Color</th></>
              }
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.face}-${row.index}`}>
                {coordMode
                  ? <>
                      <td className="coord-cell">{row.coord.join(',')}</td>
                      <td>{row.face}</td>
                    </>
                  : <>
                      <td>{row.face}</td>
                      <td>{row.index}</td>
                    </>
                }
                <td>
                  <span className={`piece-chip ${STICKER_CLASS[row.color] || ''}`} />
                  {row.color}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={3} className="piece-empty">결과 없음</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function RotationControlPanel() {
  const rotateCube      = useStore((s) => s.rotateCube);
  const resetCube       = useStore((s) => s.resetCube);
  const cubeMoveHistory = useStore((s) => s.cubeMoveHistory);

  const [seqInput,   setSeqInput]   = useState('');
  const [copyFlash,  setCopyFlash]  = useState(false);

  const applySequence = () => {
    const tokens = seqInput.trim().split(/\s+/).filter(t => VALID_MOVES.has(t));
    tokens.forEach(m => rotateCube(m));
    setSeqInput('');
  };

  const copyHistory = () => {
    if (!cubeMoveHistory.length) return;
    navigator.clipboard.writeText(cubeMoveHistory.join(' ')).then(() => {
      setCopyFlash(true);
      setTimeout(() => setCopyFlash(false), 1200);
    });
  };

  const loadHistory = () => {
    setSeqInput(cubeMoveHistory.join(' '));
  };

  return (
    <div className="rotation-control-panel">

      {/* Move buttons — paired CW / CCW */}
      <div className="rotation-pairs">
        {MOVE_BUTTONS.map(([cw, ccw]) => (
          <div key={cw} className="rotation-pair">
            <button className="rot-btn cw"  onClick={() => rotateCube(cw)}>{cw}</button>
            <button className="rot-btn ccw" onClick={() => rotateCube(ccw)}>{ccw}</button>
          </div>
        ))}
      </div>

      {/* Sequence input */}
      <div className="rot-seq-row">
        <input
          className="rot-seq-input"
          placeholder="U R' L B …"
          value={seqInput}
          onChange={e => setSeqInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && applySequence()}
        />
        <button className="rot-seq-run" onClick={applySequence} title="시퀀스 실행">▶</button>
      </div>

      {/* History row */}
      <div className="rot-history-row">
        <div className="rot-history-text" title={cubeMoveHistory.join(' ')}>
          {cubeMoveHistory.length
            ? cubeMoveHistory.slice(-12).join(' ')
            : <span className="dim">No moves yet</span>}
        </div>
        <button className="rot-history-btn" onClick={loadHistory} title="히스토리를 입력창에 불러오기" disabled={!cubeMoveHistory.length}>↑</button>
        <button className={`rot-history-btn ${copyFlash ? 'flash' : ''}`} onClick={copyHistory} title="히스토리 복사" disabled={!cubeMoveHistory.length}>⎘</button>
      </div>

      {/* Reset */}
      <button className="rotation-reset" onClick={resetCube}>↺ Reset</button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

export default function CubeTab() {
  return (
    <div className="cube-layout">
      <Panel title="3D Cube Viewer" className="cube-viewer">
        <CubeViewerPanel />
      </Panel>
      <div className="cube-side">
        <Panel title="Piece State" className="cube-side-panel">
          <PieceStatePanel />
        </Panel>
        <Panel title="Rotation Control" className="cube-side-panel">
          <RotationControlPanel />
        </Panel>
        <Panel title="Path Finder" className="cube-side-panel">
          <div className="cube-pathfinder-placeholder">미구현 (예정)</div>
        </Panel>
      </div>
    </div>
  );
}
