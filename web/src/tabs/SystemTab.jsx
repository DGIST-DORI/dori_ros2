/** Legacy compatibility layer: use panels/system/* directly for new code. */
import { TopicDiagnosticsPanel } from '../panels/system/TopicDiagnosticsPanel';
import { ConnectionInfoPanel } from '../panels/system/ConnectionInfoPanel';
import { MetricsPanel } from '../panels/system/MetricsPanel';
import TopicPublisherPanel from '../panels/system/TopicPublisherPanel';

export default function SystemTab() {
  return <div><ConnectionInfoPanel /><TopicDiagnosticsPanel /><MetricsPanel /><TopicPublisherPanel /></div>;
}

export { TopicDiagnosticsPanel, ConnectionInfoPanel, MetricsPanel, TopicPublisherPanel };
