import { useEffect, useRef, useState } from 'react';
import { Mic, MicOff } from 'lucide-react';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';
import '../../tabs/HRITab.css';

// ── Constants ─────────────────────────────────────────────────────────────────

const SAMPLE_RATE   = 16000;   // Whisper expects 16 kHz

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

// Status badge
function Badge({ ok, label }) {
  return (
    <span className={`hri-badge ${ok ? 'ok' : 'off'}`}>{label}</span>
  );
}

// Section divider label
function SectionLabel({ children }) {
  return <div className="hri-section-label">{children}</div>;
}

// ── STT Panel ─────────────────────────────────────────────────────────────────

function STTPanel() {
  const connected  = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const addLog     = useStore(s => s.addLog);
  const canPublish = connected || isDemoMode;

  const [text,          setText]          = useState('');
  const [lang,          setLang]          = useState('ko');
  const [conf,          setConf]          = useState('0.95');
  const [lastResult,    setLastResult]    = useState(null);

  // Mic state
  const [micAvail,      setMicAvail]      = useState(false);
  const [micActive,     setMicActive]     = useState(false);
  const [micError,      setMicError]      = useState('');
  const [micStatus,     setMicStatus]     = useState('idle'); // idle | requesting | recording | processing
  const mediaRecRef  = useRef(null);
  const streamRef    = useRef(null);
  const chunksRef    = useRef([]);

  // Check mic availability on mount
  useEffect(() => {
    navigator.mediaDevices?.getUserMedia({ audio: true })
      .then(s => { s.getTracks().forEach(t => t.stop()); setMicAvail(true); })
      .catch(() => setMicAvail(false));
  }, []);

  // Inject text manually
  function handleTextInject() {
    if (!text.trim()) return;
    const payload = {
      text:       text.trim(),
      language:   lang,
      confidence: parseFloat(conf) || 0.95,
      timestamp:  Date.now() / 1000,
      source:     'dashboard_inject',
    };
    pub('/dori/stt/result', 'std_msgs/msg/String', { data: JSON.stringify(payload) });
    addLog(LOG_TAGS.STT, `[inject] "${text.trim()}" (${lang}, conf=${conf})`);
    setLastResult(payload);
    setText('');
  }

  // Start mic recording
  async function handleMicStart() {
    if (micActive) return;
    setMicError('');
    setMicStatus('requesting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: SAMPLE_RATE, channelCount: 1, echoCancellation: true },
      });
      streamRef.current = stream;
      chunksRef.current = [];

      const rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      rec.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = () => handleMicStop();
      rec.start(200);
      mediaRecRef.current = rec;
      setMicActive(true);
      setMicStatus('recording');
    } catch (e) {
      setMicError(`마이크 접근 실패: ${e.message}`);
      setMicStatus('idle');
    }
  }

  function handleMicStopClick() {
    mediaRecRef.current?.stop();
    streamRef.current?.getTracks().forEach(t => t.stop());
    setMicActive(false);
    setMicStatus('processing');
  }

  // After recording stops: build a fake STT result from audio blob
  // (Actual transcription happens on Jetson. Here we publish a placeholder
  //  that tells the team mic input worked, with audio length info.)
  function handleMicStop() {
    const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
    const durationEstSec = (chunksRef.current.length * 200) / 1000;

    // Convert to base64 and publish as a custom diagnostic topic
    const reader = new FileReader();
    reader.onloadend = () => {
      const b64 = reader.result.split(',')[1];
      // Publish audio blob to a debug topic (ros-side can optionally pipe to Whisper)
      pub('/dori/debug/audio_blob', 'std_msgs/msg/String', {
        data: JSON.stringify({ audio_b64: b64, mime: 'audio/webm', duration_est_sec: durationEstSec }),
      });
      addLog(LOG_TAGS.STT, `[mic] audio captured ~${durationEstSec.toFixed(1)}s — published to /dori/debug/audio_blob`);
      setMicStatus('idle');
    };
    reader.readAsDataURL(blob);
    chunksRef.current = [];
  }

  return (
    <div className="hri-test-panel">
      <SectionLabel>Text Inject → /dori/stt/result</SectionLabel>

      <textarea
        className="hri-input-text"
        rows={2}
        placeholder="테스트할 발화를 입력하세요 (예: 도서관 어디야)"
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleTextInject(); } }}
      />

      <div className="hri-row hri-row-wrap">
        <div className="hri-field">
          <label>Language</label>
          <select value={lang} onChange={e => setLang(e.target.value)}>
            <option value="ko">ko</option>
            <option value="en">en</option>
            <option value="auto">auto</option>
          </select>
        </div>
        <div className="hri-field">
          <label>Confidence</label>
          <input type="number" min="0" max="1" step="0.01"
            value={conf} onChange={e => setConf(e.target.value)} />
        </div>
        <button
          className="hri-btn primary"
          disabled={!canPublish || !text.trim()}
          onClick={handleTextInject}
        >Inject STT</button>
      </div>

      {lastResult && (
        <div className="hri-result-row">
          <span className="hri-result-label">Last inject</span>
          <span className="hri-result-val">"{lastResult.text}"</span>
        </div>
      )}

      <SectionLabel>Microphone → /dori/debug/audio_blob</SectionLabel>

      <div className="hri-row">
        <Badge ok={micAvail} label={micAvail ? 'Mic available' : 'Mic unavailable'} />
        <Badge ok={micActive} label={micStatus} />
      </div>

      {micError && <div className="hri-error">{micError}</div>}

      <div className="hri-row">
        {!micActive ? (
          <button
            className="hri-btn accent hri-btn-icon"
            disabled={!micAvail || !canPublish}
            onClick={handleMicStart}
          >
            <Mic size={12} /> Start Recording
          </button>
        ) : (
          <button className="hri-btn danger hri-btn-icon" onClick={handleMicStopClick}>
            <MicOff size={12} /> Stop &amp; Send
          </button>
        )}
        {micActive && (
          <span className="hri-recording-dot" />
        )}
      </div>

      <p className="hri-hint">
        녹음된 오디오는 <code>/dori/debug/audio_blob</code>으로 publish됩니다.
        Jetson 측에서 이 토픽을 구독해 Whisper로 전달하면 실제 STT 테스트가 가능합니다.
      </p>
    </div>
  );
}

export default STTPanel;
export { STTPanel };
