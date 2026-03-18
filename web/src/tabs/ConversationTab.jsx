/** Legacy compatibility layer: use panels/hri/* directly for new code. */
import { SessionListPanel } from '../panels/hri/SessionListPanel';
import { TimelinePanel } from '../panels/hri/TimelinePanel';

export default function ConversationTab() {
  return <div><SessionListPanel /><TimelinePanel /></div>;
}

export { SessionListPanel, TimelinePanel };
