/** Legacy compatibility layer: use panels/knowledge/* directly for new code. */
import { DocumentBrowserPanel } from '../panels/knowledge/DocumentBrowserPanel';
import { BuildingEditorPanel } from '../panels/knowledge/BuildingEditorPanel';

export default function KnowledgeTab() {
  return <div><DocumentBrowserPanel /><BuildingEditorPanel /></div>;
}

export { DocumentBrowserPanel, BuildingEditorPanel };
