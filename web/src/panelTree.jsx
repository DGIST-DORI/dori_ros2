/**
 * panelTree.jsx — Panel tree config
 *
 * Team rule (Option A): panel implementation files follow sidebar categories.
 * Keep `Control / Perception & Intelligence / System` leaves under matching folders.
 */

import STTPanel from './panels/hri/STTPanel';
import WakeWordPanel from './panels/hri/WakeWordPanel';
import StateMonitorPanel from './panels/hri/StateMonitorPanel';
import EventLogPanel from './panels/system/EventLogPanel';
import './panels/system/EventLogPanel.css';

import FaceDisplayPanel from './panels/hri/FaceDisplayPanel';
import EmotionPalettePanel from './panels/hri/EmotionPalettePanel';
import ConversationPanel from './panels/hri/ConversationPanel';

import CubeViewerPanel from './panels/control/CubeViewerPanel';
import PieceStatePanel from './panels/control/PieceStatePanel';
import RotationControlPanel from './panels/control/RotationControlPanel';

import VisionPanel from './panels/perception/VisionPanel';
import LLMTTSPanel from './panels/perception/LLMTTSPanel';
import MenuParserPanel from './panels/perception/MenuParserPanel';
import IndexBuilderPanel from './panels/perception/IndexBuilderPanel';
import DocumentBrowserPanel from './panels/perception/DocumentBrowserPanel';
import BuildingEditorPanel from './panels/perception/BuildingEditorPanel';

import TopicDiagnosticsPanel from './panels/system/TopicDiagnosticsPanel';
import ConnectionInfoPanel from './panels/system/ConnectionInfoPanel';
import MetricsPanel from './panels/system/MetricsPanel';
import TopicPublisherPanel from './panels/system/TopicPublisherPanel';

import HriIcon        from './assets/icons/icon-hri.svg?react';
import ControlIcon    from './assets/icons/icon-control.svg?react';
import SystemIcon     from './assets/icons/icon-system.svg?react';
import NavigationIcon from './assets/icons/icon-navigation.svg?react';
import PerceptionIcon from './assets/icons/icon-perception.svg?react';
import FaceIcon         from './assets/icons/icon-face.svg?react';
import KnowledgeIcon    from './assets/icons/icon-knowledge.svg?react';
import VoiceIcon        from './assets/icons/icon-voice.svg?react';
import StateIcon        from './assets/icons/icon-state.svg?react';
import ConversationIcon from './assets/icons/icon-conversation.svg?react';
import MapIcon          from './assets/icons/icon-map.svg?react';
import CubeIcon         from './assets/icons/icon-cube.svg?react';
import VisionIcon       from './assets/icons/icon-vision.svg?react';
import LLMIcon          from './assets/icons/icon-llm.svg?react';

export const PANEL_TREE = [
  {
    id: 'hri', label: 'HRI', icon: <HriIcon />,
    children: [
      {
        id: 'hri-voice', label: 'Voice', icon: <VoiceIcon />,
        children: [
          { id: 'stt',      label: 'STT Test',   component: STTPanel },
          { id: 'wakeword', label: 'Wake Word',   component: WakeWordPanel },
          { id: 'tts',      label: 'TTS Inject',  component: LLMTTSPanel },
        ],
      },
      {
        id: 'hri-state', label: 'State', icon: <StateIcon />,
        children: [
          { id: 'state-monitor', label: 'State Monitor', component: StateMonitorPanel },
        ],
      },
      {
        id: 'hri-conversation', label: 'Conversation', icon: <ConversationIcon />,
        children: [
          { id: 'conversation', label: 'Conversation', component: ConversationPanel },
        ],
      },
      {
        id: 'hri-face', label: 'Face', icon: <FaceIcon />,
        children: [
          { id: 'face-display', label: 'Face Display',    component: FaceDisplayPanel },
          { id: 'face-palette', label: 'Emotion Palette', component: EmotionPalettePanel },
        ],
      },
    ],
  },
  {
    id: 'navigation', label: 'Navigation', icon: <NavigationIcon />,
    children: [
      {
        id: 'nav-map', label: 'Map', icon: <MapIcon />,
        children: [
          { id: 'campus-map', label: 'Campus Map', placeholder: true },
        ],
      },
    ],
  },
  {
    id: 'control', label: 'Control', icon: <ControlIcon />,
    children: [
      {
        id: 'ctrl-cube', label: 'Cube', icon: <CubeIcon />,
        children: [
          { id: 'cube-3d',       label: '3D View',          component: CubeViewerPanel },
          { id: 'cube-rotation', label: 'Rotation Control', component: RotationControlPanel },
          { id: 'cube-pieces',   label: 'Piece Table',      component: PieceStatePanel },
        ],
      },
    ],
  },
  {
    id: 'perception', label: 'Perception & Intelligence', icon: <PerceptionIcon />,
    children: [
      {
        id: 'perc-vision', label: 'Vision', icon: <VisionIcon />,
        children: [
          { id: 'vision-test', label: 'Vision Test', component: VisionPanel },
        ],
      },
      {
        id: 'perc-llm', label: 'LLM', icon: <LLMIcon />,
        children: [
          { id: 'llm-inject', label: 'LLM Inject', component: LLMTTSPanel },
        ],
      },
      {
        id: 'perc-knowledge', label: 'Knowledge', icon: <KnowledgeIcon />,
        children: [
          { id: 'menu-parser', label: 'Menu Parser',     component: MenuParserPanel },
          { id: 'index-builder', label: 'Index Builder',   component: IndexBuilderPanel },
          { id: 'knowledge-docs',     label: 'Document Browser', component: DocumentBrowserPanel },
          { id: 'knowledge-building', label: 'Building Editor',  component: BuildingEditorPanel },
        ],
      },
    ],
  },
  {
    id: 'system', label: 'System', icon: <SystemIcon />,
    children: [
      {
        id: 'sys-flat', label: null,
        children: [
          { id: 'sys-connection', label: 'Connection',        component: ConnectionInfoPanel },
          { id: 'sys-topics',     label: 'Topic Diagnostics', component: TopicDiagnosticsPanel },
          { id: 'sys-metrics',    label: 'Metrics',           component: MetricsPanel },
          { id: 'event-log',      label: 'Event Log',         component: EventLogPanel },
          { id: 'sys-topic-publisher', label: 'Topic Publisher', component: TopicPublisherPanel },
        ],
      },
    ],
  },
];

export function flattenLeaves(tree) {
  const leaves = [];
  function walk(nodes) {
    for (const node of nodes) {
      if (node.component || node.placeholder) leaves.push(node);
      else if (node.children) walk(node.children);
    }
  }
  walk(tree);
  return leaves;
}

export function findLeaf(tree, id) {
  return flattenLeaves(tree).find(l => l.id === id) ?? null;
}

export function filterTree(tree, query) {
  if (!query.trim()) return tree;
  const q = query.trim().toLowerCase();
  function filterNodes(nodes) {
    const result = [];
    for (const node of nodes) {
      if (node.component || node.placeholder) {
        if (node.label.toLowerCase().includes(q)) result.push(node);
      } else if (node.children) {
        const fc = filterNodes(node.children);
        if (fc.length > 0) result.push({ ...node, children: fc });
      }
    }
    return result;
  }
  return filterNodes(tree);
}
