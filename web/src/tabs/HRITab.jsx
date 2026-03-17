/** Legacy compatibility layer: use panels/hri/* directly for new code. */
import { STTPanel } from '../panels/hri/STTPanel';
import { WakeWordPanel } from '../panels/hri/WakeWordPanel';
import { VisionPanel } from '../panels/hri/VisionPanel';
import { LLMTTSPanel } from '../panels/hri/LLMTTSPanel';
import { StateMonitorPanel } from '../panels/hri/StateMonitorPanel';
import { EventLogPanel } from '../panels/hri/EventLogPanel';

export default function HRITab() {
  return (
    <div>
      <STTPanel /><WakeWordPanel /><VisionPanel /><LLMTTSPanel /><StateMonitorPanel /><EventLogPanel />
    </div>
  );
}

export { STTPanel, WakeWordPanel, VisionPanel, LLMTTSPanel, StateMonitorPanel, EventLogPanel };
