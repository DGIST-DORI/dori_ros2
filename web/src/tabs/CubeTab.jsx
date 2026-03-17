/** Legacy compatibility layer: use panels/cube/* directly for new code. */
import { CubeViewerPanel } from '../panels/cube/CubeViewerPanel';
import { PieceStatePanel } from '../panels/cube/PieceStatePanel';
import { RotationControlPanel } from '../panels/cube/RotationControlPanel';

export default function CubeTab() {
  return <div><CubeViewerPanel /><RotationControlPanel /><PieceStatePanel /></div>;
}

export { CubeViewerPanel, PieceStatePanel, RotationControlPanel };
