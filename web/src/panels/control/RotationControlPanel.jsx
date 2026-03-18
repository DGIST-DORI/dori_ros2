import { useState } from 'react';
import { ArrowUp, Copy, RotateCcw } from 'lucide-react';
import { useStore } from '../../core/store';
import './RotationControlPanel.css';

// ── Constants ──────────────────────────────────────────────────────────────────

const VALID_MOVES = new Set(['U', "U'", 'R', "R'", 'L', "L'", 'B', "B'"]);

const MOVE_BUTTONS  = [['U',"U'"],['R',"R'"],['L',"L'"],['B',"B'"]];

// ── Rotation Control ───────────────────────────────────────────────────────────
function RotationControlPanel() {
  const rotateCube      = useStore((s) => s.rotateCube);
  const resetCube       = useStore((s) => s.resetCube);
  const cubeMoveHistory = useStore((s) => s.cubeMoveHistory);

  const [seqInput,  setSeqInput]  = useState('');
  const [copyFlash, setCopyFlash] = useState(false);

  const applySequence = () => {
    seqInput.trim().split(/\s+/).filter(t => VALID_MOVES.has(t)).forEach(m => rotateCube(m));
    setSeqInput('');
  };

  const copyHistory = () => {
    if (!cubeMoveHistory.length) return;
    navigator.clipboard.writeText(cubeMoveHistory.join(' ')).then(() => {
      setCopyFlash(true);
      setTimeout(() => setCopyFlash(false), 1200);
    });
  };

  return (
    <div className="rotation-control-panel">
      <div className="rotation-pairs">
        {MOVE_BUTTONS.map(([cw, ccw]) => (
          <div key={cw} className="rotation-pair">
            <button className="rot-btn cw"  onClick={() => rotateCube(cw)}>{cw}</button>
            <button className="rot-btn ccw" onClick={() => rotateCube(ccw)}>{ccw}</button>
          </div>
        ))}
      </div>

      <div className="rot-seq-row">
        <input className="rot-seq-input" placeholder="U R' L B …"
          value={seqInput} onChange={e => setSeqInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && applySequence()} />
        <button className="rot-seq-run" onClick={applySequence} title="시퀀스 실행">▶</button>
      </div>

      <div className="rot-history-row">
        <div className="rot-history-text" title={cubeMoveHistory.join(' ')}>
          {cubeMoveHistory.length
            ? cubeMoveHistory.slice(-12).join(' ')
            : <span className="dim">No moves yet</span>}
        </div>
        <button className="rot-history-btn"
          onClick={() => setSeqInput(cubeMoveHistory.join(' '))}
          title="히스토리 불러오기" disabled={!cubeMoveHistory.length}>
          <ArrowUp size={11} strokeWidth={2} />
        </button>
        <button className={`rot-history-btn ${copyFlash ? 'flash' : ''}`}
          onClick={copyHistory} title="히스토리 복사" disabled={!cubeMoveHistory.length}>
          <Copy size={11} strokeWidth={2} />
        </button>
      </div>

      <button className="rotation-reset rotation-reset-icon" onClick={resetCube}>
        <RotateCcw size={11} strokeWidth={2} /> Reset
      </button>
    </div>
  );
}

export default RotationControlPanel;
export { RotationControlPanel };
