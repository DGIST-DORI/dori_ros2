import { useState } from 'react';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';

function pub(topic, msgType, data) {
  try {
    publishROS(topic, msgType, data);
    return true;
  } catch (e) {
    console.error('[pub] failed:', topic, e);
    return false;
  }
}

function SectionLabel({ children }) {
  return <div className="panel-section-label">{children}</div>;
}

function TTSInjectPanel() {
  const connected = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const addLog = useStore(s => s.addLog);
  const lastTts = useStore(s => s.lastTtsText);
  const canPublish = connected || isDemoMode;

  const [ttsText, setTtsText] = useState('');

  function handleTTS() {
    if (!ttsText.trim()) return;

    pub('/dori/tts/text', 'std_msgs/msg/String', { data: ttsText.trim() });
    addLog(LOG_TAGS.TTS, `[inject] "${ttsText.trim()}"`);
    setTtsText('');
  }

  return (
    <div className="panel-body">
      <SectionLabel>TTS Direct → /dori/tts/text</SectionLabel>
      <textarea
        className="input-text"
        rows={3}
        placeholder="로봇이 말할 텍스트 (예: 안녕하세요, 도리입니다.)"
        value={ttsText}
        onChange={e => setTtsText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleTTS(); } }}
      />
      <button className="btn btn-sm btn-primary" disabled={!canPublish || !ttsText.trim()} onClick={handleTTS}>
        Speak
      </button>
      {lastTts && (
        <div className="result-row">
          <span className="result-label">Last TTS</span>
          <span className="result-value">"{lastTts}"</span>
        </div>
      )}
    </div>
  );
}

export default TTSInjectPanel;
export { TTSInjectPanel };
