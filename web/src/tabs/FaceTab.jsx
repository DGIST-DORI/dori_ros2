/** Legacy compatibility layer: use panels/hri/* directly for new code. */
import { FaceDisplayPanel } from '../panels/hri/FaceDisplayPanel';
import { EmotionPalettePanel } from '../panels/hri/EmotionPalettePanel';

export default function FaceTab() {
  return <div><FaceDisplayPanel /><EmotionPalettePanel /></div>;
}

export { FaceDisplayPanel, EmotionPalettePanel };
