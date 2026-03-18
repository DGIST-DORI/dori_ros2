import { Volume2, VolumeX } from 'lucide-react';
import { useStore } from '../../core/store';
import '../../tabs/HRITab.css';

// ── State Monitor Panel ───────────────────────────────────────────────────────

function StateMonitorPanel() {
  const hriState      = useStore(s => s.hriState);
  const hriElapsed    = useStore(s => s.hriStateElapsed);
  const lastStt       = useStore(s => s.lastSttText);
  const lastLlm       = useStore(s => s.lastLlmResponse);
  const lastTts       = useStore(s => s.lastTtsText);
  const ttsActive     = useStore(s => s.ttsActive);
  const gesture       = useStore(s => s.gesture);
  const expression    = useStore(s => s.expression);
  const trackState    = useStore(s => s.trackingState);

  const STATE_COLOR = {
    IDLE:       'var(--text-2)',
    LISTENING:  'var(--accent)',
    RESPONDING: 'var(--yellow)',
    NAVIGATING: 'var(--green)',
  };

  function Row({ label, value, color, icon }) {
    return (
      <div className="hri-monitor-row">
        <span className="hri-monitor-key">{label}</span>
        <span className="hri-monitor-val" style={color ? { color } : {}}>
          {icon && <span className="hri-monitor-icon">{icon}</span>}
          {value || '—'}
        </span>
      </div>
    );
  }

  return (
    <div className="hri-monitor-panel">
      {/* HRI State — big indicator */}
      <div className="hri-state-indicator" style={{ borderColor: STATE_COLOR[hriState] || 'var(--border)' }}>
        <span className="hri-state-indicator-label">HRI STATE</span>
        <span className="hri-state-indicator-value" style={{ color: STATE_COLOR[hriState] || 'var(--text-0)' }}>
          {hriState}
        </span>
        <span className="hri-state-indicator-elapsed">{hriElapsed?.toFixed(1)}s</span>
      </div>

      <Row label="STT result"   value={lastStt} />
      <Row label="LLM response" value={typeof lastLlm === 'string' ? lastLlm.slice(0, 80) + (lastLlm.length > 80 ? '…' : '') : ''} />
      <Row label="TTS text"     value={lastTts} color={ttsActive ? 'var(--orange)' : undefined} />
      <Row label="TTS active"   value={ttsActive ? 'speaking' : 'silent'}
           icon={ttsActive ? <Volume2 size={10} /> : <VolumeX size={10} />}
           color={ttsActive ? 'var(--orange)' : 'var(--text-2)'} />
      <Row label="Gesture"      value={gesture} />
      <Row label="Expression"   value={expression} />
      <Row label="Tracking"     value={trackState ? `${trackState.state} (target: ${trackState.target_id ?? '—'}, ${trackState.last_distance_m ?? '?'}m)` : '—'} />
    </div>
  );
}

export default StateMonitorPanel;
export { StateMonitorPanel };
