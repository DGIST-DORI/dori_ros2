/** Legacy compatibility layer: use panels/control/* directly for new code. */
import { CubeViewerPanel } from '../panels/control/CubeViewerPanel';
import { PieceStatePanel } from '../panels/control/PieceStatePanel';
import { RotationControlPanel } from '../panels/control/RotationControlPanel';

export default function CubeTab() {
  return <div><CubeViewerPanel /><RotationControlPanel /><PieceStatePanel /></div>;
}

export { CubeViewerPanel, PieceStatePanel, RotationControlPanel };
