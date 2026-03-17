/**
 * panelTree.jsx — Panel tree config (replaces flat TABS array)
 *
 * Structure:
 *   category    { id, label, icon, children: [ subcategory ] }
 *   subcategory { id, label, icon, children: [ leaf ] }
 *   leaf        { id, label, component }
 *
 * icon on subcategory: optional. Add svg file to assets/icons/ and import below.
 * Sidebar reads this tree recursively.
 * App.jsx resolves the active component by leaf id.
 */

import FaceTab         from './tabs/FaceTab';
import HRITab          from './tabs/HRITab';
import ConversationTab from './tabs/ConversationTab';
import CubeTab         from './tabs/CubeTab';
import KnowledgeTab    from './tabs/KnowledgeTab';
import SystemTab       from './tabs/SystemTab';

// ── Category icons ────────────────────────────────────────────────────────────
import HriIcon        from './assets/icons/icon-hri.svg?react';
import CubeIcon       from './assets/icons/icon-cube.svg?react';
import SystemIcon     from './assets/icons/icon-system.svg?react';
import NavigationIcon from './assets/icons/icon-navigation.svg?react';
import PerceptionIcon from './assets/icons/icon-perception.svg?react';

// ── Subcategory icons ─────────────────────────────────────────────────────────
// Add svg to assets/icons/ and uncomment the import when ready.
import FaceIcon      from './assets/icons/icon-face.svg?react';
import KnowledgeIcon from './assets/icons/icon-knowledge.svg?react';
// import VoiceIcon         from './assets/icons/icon-voice.svg?react';
// import StateIcon         from './assets/icons/icon-state.svg?react';
// import ConversationIcon  from './assets/icons/icon-conversation.svg?react';
// import MapIcon           from './assets/icons/icon-map.svg?react';
// import CtrlCubeIcon      from './assets/icons/icon-ctrl-cube.svg?react';
// import VisionIcon        from './assets/icons/icon-vision.svg?react';
// import LLMIcon           from './assets/icons/icon-llm.svg?react';

// ── Tree ─────────────────────────────────────────────────────────────────────

export const PANEL_TREE = [
  {
    id: 'hri',
    label: 'HRI',
    icon: <HriIcon />,
    children: [
      {
        id: 'hri-voice',
        label: 'Voice',
        // icon: <VoiceIcon />,
        children: [
          { id: 'stt',      label: 'STT Test',   component: HRITab },
          { id: 'wakeword', label: 'Wake Word',   component: HRITab },
          { id: 'tts',      label: 'TTS Inject',  component: HRITab },
        ],
      },
      {
        id: 'hri-state',
        label: 'State',
        // icon: <StateIcon />,
        children: [
          { id: 'state-monitor', label: 'State Monitor', component: HRITab },
          { id: 'event-log',     label: 'Event Log',     component: HRITab },
        ],
      },
      {
        id: 'hri-conversation',
        label: 'Conversation',
        // icon: <ConversationIcon />,
        children: [
          { id: 'conversation', label: 'Session List', component: ConversationTab },
          { id: 'timeline',     label: 'Timeline',     component: ConversationTab },
        ],
      },
      {
        id: 'hri-face',
        label: 'Face',
        icon: <FaceIcon />,
        children: [
          { id: 'face-display', label: 'Face Display',   component: FaceTab },
          { id: 'face-palette', label: 'Emotion Palette', component: FaceTab },
        ],
      },
    ],
  },
  {
    id: 'navigation',
    label: 'Navigation',
    icon: <NavigationIcon />,
    children: [
      {
        id: 'nav-map',
        label: 'Map',
        // icon: <MapIcon />,
        children: [
          { id: 'campus-map', label: 'Campus Map', placeholder: true },
        ],
      },
    ],
  },
  {
    id: 'control',
    label: 'Control',
    icon: <CubeIcon />,
    children: [
      {
        id: 'ctrl-cube',
        label: 'Cube',
        // icon: <CtrlCubeIcon />,
        children: [
          { id: 'cube-3d',       label: '3D View',          component: CubeTab },
          { id: 'cube-rotation', label: 'Rotation Control', component: CubeTab },
          { id: 'cube-pieces',   label: 'Piece Table',      component: CubeTab },
        ],
      },
    ],
  },
  {
    id: 'perception',
    label: 'Perception & Intelligence',
    icon: <PerceptionIcon />,
    children: [
      {
        id: 'perc-vision',
        label: 'Vision',
        // icon: <VisionIcon />,
        children: [
          { id: 'vision-test', label: 'Vision Test', component: HRITab },
        ],
      },
      {
        id: 'perc-llm',
        label: 'LLM',
        // icon: <LLMIcon />,
        children: [
          { id: 'llm-inject', label: 'LLM Inject', component: HRITab },
        ],
      },
      {
        id: 'perc-knowledge',
        label: 'Knowledge',
        icon: <KnowledgeIcon />,
        children: [
          { id: 'knowledge-docs',     label: 'Document Browser', component: KnowledgeTab },
          { id: 'knowledge-building', label: 'Building Editor',  component: KnowledgeTab },
        ],
      },
    ],
  },
  {
    id: 'system',
    label: 'System',
    icon: <SystemIcon />,
    children: [
      {
        id: 'sys-flat',
        label: null,  // flat — no visible subcategory header
        children: [
          { id: 'sys-connection', label: 'Connection',        component: SystemTab },
          { id: 'sys-topics',     label: 'Topic Diagnostics', component: SystemTab },
          { id: 'sys-metrics',    label: 'Metrics',           component: SystemTab },
        ],
      },
    ],
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Flatten tree → array of leaf nodes */
export function flattenLeaves(tree) {
  const leaves = [];
  function walk(nodes) {
    for (const node of nodes) {
      if (node.component || node.placeholder) {
        leaves.push(node);
      } else if (node.children) {
        walk(node.children);
      }
    }
  }
  walk(tree);
  return leaves;
}

/** Find leaf node by id */
export function findLeaf(tree, id) {
  return flattenLeaves(tree).find(l => l.id === id) ?? null;
}

/**
 * Filter tree by search query.
 * Returns a new tree with only matching branches.
 * A category/subcategory is kept if any of its leaf descendants match.
 */
export function filterTree(tree, query) {
  if (!query.trim()) return tree;
  const q = query.trim().toLowerCase();

  function filterNodes(nodes) {
    const result = [];
    for (const node of nodes) {
      if (node.component || node.placeholder) {
        // Leaf: keep if label matches
        if (node.label.toLowerCase().includes(q)) result.push(node);
      } else if (node.children) {
        // Branch: keep if any descendant matches
        const filteredChildren = filterNodes(node.children);
        if (filteredChildren.length > 0) {
          result.push({ ...node, children: filteredChildren });
        }
      }
    }
    return result;
  }

  return filterNodes(tree);
}
