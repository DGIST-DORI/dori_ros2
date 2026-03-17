/**
 * core/floatingPanels.js — Zustand slice for floating panel workspace
 *
 * State shape:
 *   openPanels: Array<{
 *     id,          // leaf id from PANEL_TREE
 *     label,       // display title
 *     component,   // React component
 *     x, y,        // position (px from workspace top-left)
 *     w, h,        // size (px)
 *     minimized,   // bool — collapsed to title bar only
 *     zIndex,      // stacking order
 *   }>
 *
 * Rules:
 *   - Opening an already-open panel focuses it (brings to front) instead of duplicating
 *   - zIndex is managed as a monotonically increasing counter
 *   - Default spawn position staggers by open count to avoid full overlap
 */

const DEFAULT_W = 480;
const DEFAULT_H = 360;
const STAGGER   = 28;   // px offset per panel

let zCounter = 10;

function nextZ() { return ++zCounter; }

function defaultPosition(count) {
  const base = 60;
  const offset = (count % 8) * STAGGER;
  return { x: base + offset, y: base + offset };
}

export const floatingPanelsSlice = (set, get) => ({
  openPanels: [],

  // Open a panel by leaf node — focus if already open
  openPanel: (leaf) => {
    const panels = get().openPanels;
    const existing = panels.find(p => p.id === leaf.id);

    if (existing) {
      // Already open — just bring to front and un-minimize
      set({
        openPanels: panels.map(p =>
          p.id === leaf.id
            ? { ...p, minimized: false, zIndex: nextZ() }
            : p
        ),
      });
      return;
    }

    const { x, y } = defaultPosition(panels.length);
    set({
      openPanels: [
        ...panels,
        {
          id:        leaf.id,
          label:     leaf.label,
          component: leaf.component,
          x, y,
          w: DEFAULT_W,
          h: DEFAULT_H,
          minimized: false,
          zIndex:    nextZ(),
        },
      ],
    });
  },

  // Close a panel by id
  closePanel: (id) => {
    set({ openPanels: get().openPanels.filter(p => p.id !== id) });
  },

  // Toggle minimize
  minimizePanel: (id) => {
    set({
      openPanels: get().openPanels.map(p =>
        p.id === id ? { ...p, minimized: !p.minimized, zIndex: nextZ() } : p
      ),
    });
  },

  // Bring panel to front
  focusPanel: (id) => {
    set({
      openPanels: get().openPanels.map(p =>
        p.id === id ? { ...p, zIndex: nextZ() } : p
      ),
    });
  },

  // Update position after drag
  movePanelTo: (id, x, y) => {
    set({
      openPanels: get().openPanels.map(p =>
        p.id === id ? { ...p, x, y } : p
      ),
    });
  },

  // Update size after resize
  resizePanel: (id, w, h) => {
    set({
      openPanels: get().openPanels.map(p =>
        p.id === id ? { ...p, w, h } : p
      ),
    });
  },
});
