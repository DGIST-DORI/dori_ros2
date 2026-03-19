import { useState } from 'react';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';
import './LLMTTSPanel.css';

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

// Section divider label
function SectionLabel({ children }) {
  return <div className="panel-section-label">{children}</div>;
}

// ── LLM / TTS Panel ───────────────────────────────────────────────────────────

function LLMTTSPanel() {
  const connected   = useStore(s => s.connected);
  const isDemoMode  = useStore(s => s.isDemoMode);
  const addLog      = useStore(s => s.addLog);
  const canPublish  = connected || isDemoMode;
  const lastLlmResp = useStore(s => s.lastLlmResponse);
  const lastTts     = useStore(s => s.lastTtsText);

  const [llmQuery,  setLlmQuery]  = useState('');
  const [ttsText,   setTtsText]   = useState('');
  const [locCtx,    setLocCtx]    = useState('');
  const [mode,      setMode]      = useState('llm'); // 'llm' | 'tts'

  function handleLLM() {
    if (!llmQuery.trim()) return;
    const payload = {
      user_text:        llmQuery.trim(),
      location_context: locCtx.trim(),
      hri_state:        'RESPONDING',
      timestamp:        Date.now() / 1000,
      source:           'dashboard_inject',
    };
    pub('/dori/llm/query', 'std_msgs/msg/String', { data: JSON.stringify(payload) });
    addLog(LOG_TAGS.LLM, `[inject] "${llmQuery.trim()}"`);
    setLlmQuery('');
  }

  function handleTTS() {
    if (!ttsText.trim()) return;
    pub('/dori/tts/text', 'std_msgs/msg/String', { data: ttsText.trim() });
    addLog(LOG_TAGS.TTS, `[inject] "${ttsText.trim()}"`);
    setTtsText('');
  }

  return (
    <div className="panel-body">
      <div className="hri-tab-row">
        <button className={`hri-tab-btn ${mode === 'llm' ? 'active' : ''}`} onClick={() => setMode('llm')}>LLM Query</button>
        <button className={`hri-tab-btn ${mode === 'tts' ? 'active' : ''}`} onClick={() => setMode('tts')}>TTS Direct</button>
      </div>

      {mode === 'llm' && (
        <>
          <SectionLabel>LLM Query → /dori/llm/query</SectionLabel>
          <textarea
            className="input-text"
            rows={2}
            placeholder="질문 (예: 학생식당 어디에 있어요?)"
            value={llmQuery}
            onChange={e => setLlmQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleLLM(); } }}
          />
          <div className="field field-full">
            <label className="field-label">Location context (optional)</label>
            <input
              className="input input-full"
              type="text"
              placeholder="예: E7 건물 앞"
              value={locCtx}
              onChange={e => setLocCtx(e.target.value)}
            />
          </div>
          <button className="btn btn-sm btn-primary" disabled={!canPublish || !llmQuery.trim()} onClick={handleLLM}>
            Send to LLM
          </button>
          {lastLlmResp && (
            <div className="result-row result-row-col">
              <span className="result-label">LLM response</span>
              <span className="result-value">{typeof lastLlmResp === 'string' ? lastLlmResp : JSON.stringify(lastLlmResp)}</span>
            </div>
          )}
        </>
      )}

      {mode === 'tts' && (
        <>
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
        </>
      )}
    </div>
  );
}

export default LLMTTSPanel;
export { LLMTTSPanel };
