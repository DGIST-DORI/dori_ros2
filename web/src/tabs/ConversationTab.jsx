/** Legacy compatibility layer: use panels/conversation/* directly for new code. */
import { SessionListPanel } from '../panels/conversation/SessionListPanel';
import { TimelinePanel } from '../panels/conversation/TimelinePanel';

export default function ConversationTab() {
  return <div><SessionListPanel /><TimelinePanel /></div>;
}

export { SessionListPanel, TimelinePanel };
