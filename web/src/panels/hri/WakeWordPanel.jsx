import { useState } from 'react';
import { Zap } from 'lucide-react';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';
import '../../tabs/HRITab.css';

// ── Helpers ───────────────────────────────────────────────────────────────────

function pub(topic, msgType, data) {
  try {
    publishROS(topic, msgType, data);
    return true;
  } catch (e) {
    console.error('[pub] failed:', topic, e);
    return false;
  }
}

function ts() { return new Date().toLocaleTimeString(); }

// Section divider label
function SectionLabel({ children }) {
  return <div className="hri-section-label">{children}</div>;
}

// ── Wake Word Panel ───────────────────────────────────────────────────────────

function WakeWordPanel() {
  const connected  = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const hriState   = useStore(s => s.hriState);
  const addLog     = useStore(s => s.addLog);
  const canPublish = connected || isDemoMode;
  const [lastTs, setLastTs] = useState(null);

  function fire() {
    const ok = pub('/dori/stt/wake_word_detected', 'std_msgs/msg/Bool', { data: true });
    if (ok) {
      addLog(LOG_TAGS.WAKE, '[test] wake word triggered from dashboard');
      setLastTs(ts());
    } else {
      addLog(LOG_TAGS.ERROR, '[test] wake word publish failed — ROS not connected?');
    }
  }

  return (
    <div className="hri-test-panel">
      <SectionLabel>Wake Word → /dori/stt/wake_word_detected</SectionLabel>
      <div className="hri-state-row">
        <span className="hri-state-key">Current HRI state</span>
        <span className={`hri-state-val hri-state-${hriState}`}>{hriState}</span>
      </div>
      <div className="hri-row">
        <button className="hri-btn accent hri-btn-icon" disabled={!canPublish} onClick={fire}>
          <Zap size={12} /> Trigger Wake Word
        </button>
        {lastTs && <span className="hri-hint-inline">fired at {lastTs}</span>}
      </div>
      <p className="hri-hint">
        HRI Manager가 IDLE일 때만 반응합니다. LISTENING → RESPONDING → IDLE 사이클을 테스트할 수 있습니다.
      </p>
    </div>
  );
}

export default WakeWordPanel;
export { WakeWordPanel };
