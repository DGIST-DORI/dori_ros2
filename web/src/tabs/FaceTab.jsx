/** Legacy compatibility layer: use panels/face/* directly for new code. */
import { FaceDisplayPanel } from '../panels/face/FaceDisplayPanel';
import { EmotionPalettePanel } from '../panels/face/EmotionPalettePanel';

export default function FaceTab() {
  return <div><FaceDisplayPanel /><EmotionPalettePanel /></div>;
}

export { FaceDisplayPanel, EmotionPalettePanel };
