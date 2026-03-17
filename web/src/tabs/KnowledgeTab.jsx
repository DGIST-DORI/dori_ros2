/** Legacy compatibility layer: use panels/perception/* directly for new code. */
import { DocumentBrowserPanel } from '../panels/perception/DocumentBrowserPanel';
import { BuildingEditorPanel } from '../panels/perception/BuildingEditorPanel';

export default function KnowledgeTab() {
  return <div><DocumentBrowserPanel /><BuildingEditorPanel /></div>;
}

export { DocumentBrowserPanel, BuildingEditorPanel };
