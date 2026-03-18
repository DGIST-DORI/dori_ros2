import { useStore } from '../../core/store';
import { useState, useEffect } from 'react';
import './EmotionPalettePanel.css';
import { Zap, Radio, RefreshCw, Circle } from 'lucide-react';

// ── Emotion configuration ─────────────────────────────────────────────────────
// Numeric fields are lerp-interpolated during transitions.
// Non-numeric fields (type, blink, scan, drift, cheeks, showMouth) snap at 50% of transition.
const EMOTION_CONFIG = {
  CALM: {
    label: 'Calm',
    leftEye:  { type: 'roundedRect', width: 102, height: 78, cornerRadius: 24, tilt: -2, upperLid: 0.9, lowerLid: 1.0, pupilScale: 1, offsetY: 0 },
    rightEye: { type: 'roundedRect', width: 102, height: 78, cornerRadius: 24, tilt: 2, upperLid: 0.9, lowerLid: 1.0, pupilScale: 1, offsetY: 0 },
    mouth: { type: 'curve', halfW: 38, startY: 0, endY: 0, curveY: 10 },
    showMouth: false,
    blink: true,
    blinkInterval: 4000,
    blinkProfile: 'CALM',
    drift: true,
    scan: false,
    motionProfile: {
      x: [{ amp: 3.8, speed: 0.95 }, { amp: 1.9, speed: 1.74 }],
      y: [{ amp: 2.6, speed: 0.72 }, { amp: 1.2, speed: 1.28 }],
    },
    cheeks: false,
  },
  ATTENTIVE: {
    label: 'Attentive',
    leftEye:  { type: 'roundedRect', width: 114, height: 90, cornerRadius: 28, tilt: -1, upperLid: 1, lowerLid: 1, pupilScale: 1.1, offsetY: -8 },
    rightEye: { type: 'roundedRect', width: 114, height: 90, cornerRadius: 28, tilt: 1, upperLid: 1, lowerLid: 1, pupilScale: 1.1, offsetY: -8 },
    mouth: { type: 'curve', halfW: 32, startY: 2, endY: 2, curveY: 6 },
    showMouth: false,
    blink: true,
    blinkInterval: 6000,
    blinkProfile: 'ATTENTIVE',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.8, speed: 1.34 }, { amp: 0.45, speed: 2.18 }],
      y: [{ amp: 0.65, speed: 1.02 }, { amp: 0.3, speed: 1.87 }],
    },
    cheeks: false,
  },
  THINKING: {
    label: 'Thinking',
    leftEye:  { type: 'roundedRect', width: 102, height: 78, cornerRadius: 24, tilt: -3, upperLid: 0.94, lowerLid: 0.98, pupilScale: 0.96, offsetY: 0 },
    rightEye: { type: 'roundedRect', width: 102, height: 78, cornerRadius: 24, tilt: 3, upperLid: 0.94, lowerLid: 0.98, pupilScale: 0.96, offsetY: 0 },
    mouth: { type: 'flat', halfW: 30, startY: 4, endY: 4, curveY: 0 },
    showMouth: false,
    blink: false,
    blinkInterval: 0,
    blinkProfile: 'ATTENTIVE',
    drift: true,
    scan: true,
    motionProfile: {
      x: [{ amp: 12.5, speed: 1.18 }, { amp: 3.6, speed: 2.04 }],
      y: [{ amp: 0.75, speed: 1.12 }, { amp: 0.35, speed: 2.43 }],
    },
    cheeks: false,
  },
  HAPPY: {
    label: 'Happy',
    leftEye:  { type: 'roundedRect', width: 108, height: 84, cornerRadius: 30, tilt: -2, upperLid: 1, lowerLid: 1, pupilScale: 1.04, offsetY: -2 },
    rightEye: { type: 'roundedRect', width: 108, height: 84, cornerRadius: 30, tilt: 2, upperLid: 1, lowerLid: 1, pupilScale: 1.04, offsetY: -2 },
    mouth: { type: 'smile', halfW: 50, startY: 0, endY: 0, curveY: 26 },
    showMouth: false,
    blink: true,
    blinkInterval: 3000,
    blinkProfile: 'HAPPY',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 1.4, speed: 1.42 }, { amp: 0.9, speed: 2.36 }],
      y: [{ amp: 1.1, speed: 0.96 }, { amp: 0.65, speed: 1.68 }],
    },
    transitionEasing: 'overshoot',
    cheeks: true,
  },

  CURIOUS: {
    label: 'Curious',
    leftEye:  { type: 'roundedRect', width: 110, height: 86, cornerRadius: 28, tilt: -4, upperLid: 1, lowerLid: 0.96, pupilScale: 1.08, offsetY: -4 },
    rightEye: { type: 'roundedRect', width: 110, height: 86, cornerRadius: 28, tilt: 4, upperLid: 1, lowerLid: 0.96, pupilScale: 1.08, offsetY: -4 },
    mouth: { type: 'curve', halfW: 36, startY: 1, endY: -1, curveY: 7 },
    showMouth: false,
    blink: true,
    blinkInterval: 5200,
    blinkProfile: 'ATTENTIVE',
    drift: true,
    scan: true,
    motionProfile: {
      x: [{ amp: 7.8, speed: 1.15 }, { amp: 2.4, speed: 2.1 }],
      y: [{ amp: 1.1, speed: 1.0 }, { amp: 0.45, speed: 1.9 }],
    },
    cheeks: false,
  },
  SHY: {
    label: 'Shy',
    leftEye:  { type: 'roundedRect', width: 96, height: 72, cornerRadius: 24, tilt: -1, upperLid: 0.86, lowerLid: 1, pupilScale: 0.92, offsetY: 5 },
    rightEye: { type: 'roundedRect', width: 96, height: 72, cornerRadius: 24, tilt: 1, upperLid: 0.86, lowerLid: 1, pupilScale: 0.92, offsetY: 5 },
    mouth: { type: 'curve', halfW: 26, startY: 5, endY: 5, curveY: 4 },
    showMouth: false,
    blink: true,
    blinkInterval: 3200,
    blinkProfile: 'CALM',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.9, speed: 0.92 }, { amp: 0.5, speed: 1.55 }],
      y: [{ amp: 0.8, speed: 0.86 }, { amp: 0.42, speed: 1.34 }],
    },
    cheeks: true,
  },
  SURPRISED: {
    label: 'Surprised',
    leftEye:  { type: 'roundedRect', width: 118, height: 96, cornerRadius: 30, tilt: 0, upperLid: 1, lowerLid: 1, pupilScale: 1.14, offsetY: -10 },
    rightEye: { type: 'roundedRect', width: 118, height: 96, cornerRadius: 30, tilt: 0, upperLid: 1, lowerLid: 1, pupilScale: 1.14, offsetY: -10 },
    mouth: { type: 'wave', halfW: 68, startY: 7, endY: 7, curveY: 7 },
    showMouth: false,
    blink: false,
    blinkInterval: 0,
    blinkProfile: 'ATTENTIVE',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.55, speed: 1.35 }, { amp: 0.32, speed: 2.2 }],
      y: [{ amp: 0.45, speed: 1.04 }, { amp: 0.24, speed: 1.76 }],
    },
    cheeks: false,
  },
  BUMPED: {
    label: 'Bumped',
    leftEye:  { type: 'chevronLeft', width: 80, height: 64, cornerRadius: 18, tilt: -4, upperLid: 1, lowerLid: 1, pupilScale: 1, offsetY: -2 },
    rightEye: { type: 'chevronRight', width: 80, height: 64, cornerRadius: 18, tilt: 4, upperLid: 1, lowerLid: 1, pupilScale: 1, offsetY: -2 },
    mouth: { type: 'zigzag', halfW: 56, startY: 9, endY: 9, curveY: 10 },
    showMouth: true,
    blink: false,
    blinkInterval: 0,
    blinkProfile: 'ATTENTIVE',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.9, speed: 1.8 }, { amp: 0.35, speed: 3.0 }],
      y: [{ amp: 0.6, speed: 1.2 }, { amp: 0.25, speed: 2.1 }],
    },
    cheeks: false,
  },
  RELIEVED: {
    label: 'Relieved',
    leftEye:  { type: 'roundedRect', width: 104, height: 80, cornerRadius: 28, tilt: -2, upperLid: 0.9, lowerLid: 1, pupilScale: 0.98, offsetY: 1 },
    rightEye: { type: 'roundedRect', width: 104, height: 80, cornerRadius: 28, tilt: 2, upperLid: 0.9, lowerLid: 1, pupilScale: 0.98, offsetY: 1 },
    mouth: { type: 'smile', halfW: 42, startY: 2, endY: 2, curveY: 14 },
    showMouth: false,
    blink: true,
    blinkInterval: 4300,
    blinkProfile: 'CALM',
    drift: true,
    scan: false,
    motionProfile: {
      x: [{ amp: 2.6, speed: 1.06 }, { amp: 1.4, speed: 1.82 }],
      y: [{ amp: 1.4, speed: 0.8 }, { amp: 0.62, speed: 1.24 }],
    },
    cheeks: false,
  },
  SLEEPY: {
    label: 'Sleepy',
    leftEye:  { type: 'roundedRect', width: 108, height: 62, cornerRadius: 26, tilt: -3, upperLid: 0.66, lowerLid: 0.95, pupilScale: 0.86, offsetY: 8 },
    rightEye: { type: 'roundedRect', width: 108, height: 62, cornerRadius: 26, tilt: 3, upperLid: 0.66, lowerLid: 0.95, pupilScale: 0.86, offsetY: 8 },
    mouth: { type: 'flat', halfW: 26, startY: 6, endY: 6, curveY: 0 },
    showMouth: false,
    blink: true,
    blinkInterval: 2500,
    blinkProfile: 'CALM',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.7, speed: 0.58 }, { amp: 0.25, speed: 0.9 }],
      y: [{ amp: 0.55, speed: 0.5 }, { amp: 0.2, speed: 0.82 }],
    },
    cheeks: false,
  },
};

const STATUS_SECTION_H = 118;

function EmotionPalettePanel() {
  const emotion       = useStore(s => s.emotion);
  const emotionSource = useStore(s => s.emotionSource);
  const hriState      = useStore(s => s.hriState);
 
  const [statusOpen, setStatusOpen] = useState(emotionSource === 'override');
  const [search, setSearch]         = useState('');
 
  // Auto-open status when override becomes active
  useEffect(() => {
    if (emotionSource === 'override') setStatusOpen(true);
  }, [emotionSource]);
 
  const filteredEmotions = Object.entries(EMOTION_CONFIG).filter(([key, ecfg]) =>
    !search.trim() ||
    ecfg.label.toLowerCase().includes(search.trim().toLowerCase()) ||
    key.toLowerCase().includes(search.trim().toLowerCase())
  );
 
  const sourceIcon =
    emotionSource === 'override' ? <Zap size={10} strokeWidth={2} /> :
    emotionSource === 'ros'      ? <Radio size={10} strokeWidth={2} /> :
                                   <RefreshCw size={10} strokeWidth={2} />;
 
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
 
      {/* Search */}
      <div style={{ padding: '6px 8px', flexShrink: 0 }}>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search emotions..."
          style={{
            width: '100%',
            boxSizing: 'border-box',
            background: 'var(--bg-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            color: 'var(--text-0)',
            fontSize: '11px',
            padding: '4px 8px',
            outline: 'none',
            fontFamily: 'var(--font-sans)',
          }}
          onFocus={e => e.target.style.borderColor = 'var(--border-bright)'}
          onBlur={e  => e.target.style.borderColor = 'var(--border)'}
        />
      </div>
 
      {/* Palette — scrollable, fills remaining space */}
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        <div className="face-palette">
          {filteredEmotions.length === 0 ? (
            <div style={{ fontSize: '11px', color: 'var(--text-2)', padding: '12px', textAlign: 'center' }}>
              No results
            </div>
          ) : filteredEmotions.map(([key, ecfg]) => (
            <button
              key={key}
              className={`face-palette-btn ${emotion === key ? 'active' : ''}`}
              onClick={() => useStore.getState().setEmotionOverride(key)}
            >
              <span className="face-palette-dot" />
              <span className="face-palette-name">{ecfg.label}</span>
              {emotion === key && (
                <span className="face-palette-active-mark">
                  <Circle size={6} fill="currentColor" strokeWidth={0} />
                </span>
              )}
            </button>
          ))}
        </div>
      </div>
 
      {/* Status — collapsible via max-height, no position change */}
      <div style={{ borderTop: '1px solid var(--border)', flexShrink: 0 }}>
        <button
          onClick={() => setStatusOpen(o => !o)}
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '6px 10px',
            background: 'transparent',
            border: 'none',
            color: emotionSource === 'override' ? 'var(--yellow)' : 'var(--text-2)',
            fontSize: '9px',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.8px',
            cursor: 'pointer',
          }}
        >
          <span>Status</span>
          <span style={{ fontSize: '10px' }}>{statusOpen ? '▾' : '▸'}</span>
        </button>
 
        <div style={{
          overflow: 'hidden',
          maxHeight: statusOpen ? '200px' : '0',
          transition: 'max-height 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
        }}>
          <div className="face-status-list">
            <div className="face-status-row">
              <span className="face-status-key">Emotion</span>
              <span className="face-status-val">{emotion}</span>
            </div>
            <div className="face-status-row">
              <span className="face-status-key">Source</span>
              <span className={`face-status-val face-source-${emotionSource} face-source-icon`}>
                {sourceIcon} {emotionSource}
              </span>
            </div>
            <div className="face-status-row">
              <span className="face-status-key">HRI State</span>
              <span className="face-status-val">{hriState}</span>
            </div>
            {emotionSource === 'override' && (
              <button
                className="face-clear-override"
                onClick={() => useStore.getState().clearEmotionOverride()}
              >
                Clear Override
              </button>
            )}
          </div>
        </div>
      </div>
 
    </div>
  );
}
 
export default EmotionPalettePanel;
export { EmotionPalettePanel };
