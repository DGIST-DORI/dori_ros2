# Contributing guidelines

## Project Overview
- Robot name: DORI (a campus guide robot in the shape of a Rubik's cube / sphere)

## General Rules
- All logger messages and code comments must be written in English.

---

## Web Dashboard Design Conventions

### Shared Style File Structure

When writing a new panel or modifying an existing one, use the three files below.
`styles/shared/` is the deleted legacy folder and must no longer be used.

```
web/src/styles/
  tokens.css      ← color, font, and spacing tokens (edit here to propagate globally)
  layout.css      ← grid layout classes
  components.css  ← reusable UI: buttons, badges, inputs, log panes, etc.
```

`index.css` globally imports all three, so each panel CSS only needs to import what it uses.

```css
/* Panel that only needs layout */
@import "../../styles/layout.css";

/* Panel that only needs components (buttons, badges, etc.) */
@import "../../styles/components.css";

/* Panel that needs both */
@import "../../styles/layout.css";
@import "../../styles/components.css";
```

---

### Color Token Rules

Never reference raw color variables (`--green`, `--red`, `--accent`, etc.) directly inside
panel files. Always use semantic tokens instead.

| Situation | Token to use |
|---|---|
| OK · connected · success | `--color-ok` / `--color-ok-bg` |
| Warning · caution | `--color-warn` / `--color-warn-bg` |
| Error · failure · danger | `--color-error` / `--color-error-bg` |
| Info · emphasis · interactive | `--color-info` / `--color-info-bg` |
| Background layers | `--surface-base` / `--surface-panel` / `--surface-raised` / `--surface-overlay` |
| Text hierarchy | `--text-primary` / `--text-secondary` / `--text-muted` |
| Borders | `--border-default` / `--border-bright` |

```css
/* Correct */
color: var(--color-ok);
background: var(--color-error-bg);

/* Wrong — raw variable or hard-coded value */
color: var(--green);
background: rgba(255, 77, 106, 0.1);
```

---

### Spacing and Font Size Tokens

Use tokens instead of hard-coded px values.

**Spacing**

| Token | Value | Primary use |
|---|---|---|
| `--space-1` | 4px | Icon-to-text gap, minimum gap |
| `--space-2` | 8px | Component inner gap, panel padding |
| `--space-3` | 12px | Section spacing, panel body padding |
| `--space-4` | 16px | Large section padding |
| `--space-6` | 24px | Page-level margin |

**Font sizes**

| Token | Value | Primary use |
|---|---|---|
| `--font-size-xs` | 9px | Badge labels, uppercase meta text |
| `--font-size-sm` | 10px | Secondary UI text, table cells |
| `--font-size-md` | 11px | Primary body / panel text (default) |
| `--font-size-lg` | 13px | Section titles, emphasized values |
| `--font-size-xl` | 15px | Header logo, large numeric displays |

---

### Font Usage Rules

| Font | Use |
|---|---|
| `var(--font-mono)` — IBM Plex Mono | All UI chrome: buttons, labels, inputs, code, logs |
| `var(--font-sans)` — IBM Plex Sans KR | Long Korean body text, search inputs |

---

### Layout Class Reference

| Class | Use |
|---|---|
| `.layout-main-aside` | Main content + fixed-width aside (default 280px) |
| `.layout-main-aside.aside-300` | Aside 300px variant |
| `.layout-3col` | Three-column layout (HRI panels) |
| `.layout-2col` | Two-column equal layout (Knowledge panels) |
| `.layout-conversation` | Session list + chat area |
| `.layout-panel-body` | Single-column scrollable panel (System panels) |
| `.slot-main` / `.slot-aside` | Slots inside `.layout-main-aside` |
| `.slot-col` / `.slot-col-right` | Slots inside `.layout-3col` |
| `.slot-fill` | Fills remaining height and scrolls |
| `.slot-shrink` | Fixed height, pinned to bottom |

---

### Component Class Reference

#### Panel structure

```jsx
<div className="panel-body">           {/* scrollable panel body */}
  <div className="panel-section-label">Section Title</div>
  ...
</div>
```

#### Buttons

```jsx
<button className="btn">Default</button>
<button className="btn btn-primary">Blue / info</button>
<button className="btn btn-ok">Green / success</button>
<button className="btn btn-danger">Red / error</button>
<button className="btn btn-warn">Yellow / warning</button>
<button className="btn btn-sm">Small size</button>
<button className="btn btn-sm btn-primary btn-icon">
  <SomeIcon /> With icon
</button>
```

#### Badges

```jsx
<span className="badge">Default (gray)</span>
<span className="badge badge-ok">OK</span>
<span className="badge badge-warn">Warning</span>
<span className="badge badge-error">Error</span>
<span className="badge badge-info">Info</span>
<span className="badge badge-running">Running — pulsing animation</span>
```

#### Inputs and fields

```jsx
<div className="field">
  <span className="field-label">Label</span>
  <input className="input" />            {/* default 80px width */}
  <input className="input input-full" /> {/* 100% width */}
</div>

<textarea className="input-text" />      {/* multiline */}
<input className="input-search" />       {/* search bar, uses font-sans */}
<input className="input-km" />           {/* Knowledge panel inputs */}
<textarea className="input-km textarea" />{/* Knowledge panel multiline */}
```

#### Row (horizontal flex)

```jsx
<div className="row">...</div>           {/* flex, nowrap */}
<div className="row row-wrap">...</div>  {/* flex, wrap */}
```

#### Log pane

```jsx
<div className="log-pane">
  <span className="log-pane-empty">No output yet.</span>
  <div className="log-pane-line">{line}</div>
</div>
```

#### Result rows

```jsx
<div className="result-row">
  <span className="result-label">Label</span>
  <span className="result-value">Value</span>
</div>
<div className="result-row result-row-col"> {/* vertical variant */}
  ...
</div>
```

#### Feedback text

```jsx
<div className="error-text">Error message</div>
<p className="hint-text">Hint with <code>inline code</code>.</p>
<span className="hint-inline">Short inline hint</span>
```

#### Miscellaneous

```jsx
<span className="recording-dot" />           {/* red pulsing dot while recording */}
<div className="actions">...</div>           {/* button group row */}
<div className="empty-state">No items</div>
<div className="empty-state empty-state-center">Centered empty state</div>
```

---

### New Panel Checklist

1. Create `web/src/panels/<domain>/PanelName.jsx` + `PanelName.css`
2. Import only the shared style files the panel actually needs
3. Use semantic tokens — **never** raw color variables (`--green`, `--red`, `--accent`, etc.)
4. Use `--space-*` tokens — **never** hard-coded px spacing values
5. Register the component in `panelTree.jsx`
6. Add default window dimensions to `PANEL_SIZES` in `floatingPanels.js`

### Rules When Modifying Existing Panels

- Panel-specific styles (classes prefixed with the panel name) stay in the panel's own CSS file
- If a UI pattern appears in 3 or more panels, move it into `components.css` and share it
- To change colors or spacing globally, edit only the token files — changes propagate automatically

---

### Logo Conventions

#### File locations

```
web/public/logo/
  favicon.svg          ← browser tab icon (SVG, all modern browsers)
  favicon.ico          ← legacy fallback (generate from favicon.svg when needed)

web/src/assets/logo/
  logo-icon.svg        ← icon only  — square 1000×1000
  logo-full.svg        ← icon + text — light mode  (text: #36454f)
  logo-full-dark.svg   ← icon + text — dark mode   (text: #e2eaf2)
  logo-text.svg        ← text only  — light mode
  logo-text-dark.svg   ← text only  — dark mode
```

All files under `web/src/assets/logo/` are imported as React components via `vite-plugin-svgr`:

```js
import DoriLogoIcon from '../assets/logo/logo-icon.svg?react';
```

Files under `web/public/logo/` are served as static assets and referenced by URL path.

#### When to use each variant

| Variant | Use |
|---|---|
| `logo-icon.svg` | Sidebar collapsed state, app icon, any square context |
| `logo-full.svg` / `logo-full-dark.svg` | Sidebar expanded state, header (auto-selects by theme) |
| `logo-text.svg` / `logo-text-dark.svg` | Standalone text lockup without the icon mark |
| `favicon.svg` | Browser tab — referenced from `index.html` |

#### Theme-aware rendering

Always render the correct variant based on the active theme.
Do **not** hard-code one variant for both modes.

```jsx
// Resolve once at component level
const LogoComponent = isDark ? DoriLogoFullDark : DoriLogoFull;
return <LogoComponent className="my-logo" />;
```

The `isDark` value should be derived from:
1. `localStorage.getItem('theme-mode')` if it is `'dark'` or `'light'`
2. `window.matchMedia('(prefers-color-scheme: dark)').matches` if the value is `'auto'`

#### Sizing

Never set an explicit `width` on the logo SVG. Set only `height` and let `width: auto` maintain
the natural aspect ratio.

```css
.my-logo-svg {
  height: 24px;   /* choose height to fit the containing row */
  width: auto;
  display: block;
}
```

Standard heights in use:

| Context | Height |
|---|---|
| Header (`hdr-logo-svg`) | 24px |
| Sidebar expanded (`sb-logo-svg`) | 22px |
| Sidebar collapsed (`sb-icon-svg`) | 24px (square icon) |

#### Do not modify the logo SVG source

- Do not change fill colors inside the SVG files — use the correct light/dark variant instead.
- Do not add CSS filters (`brightness`, `invert`, etc.) to the logo element.
- Do not scale the logo below 16px height — the mark becomes illegible.
- The gradient in the icon mark is fixed and intentional; do not override it with `currentColor`.

#### Generating favicon.ico (when needed)

SVG favicons are supported in all modern browsers. A `.ico` fallback is only needed for
legacy environments. Generate it from `favicon.svg`:

```bash
# Using Inkscape (recommended)
inkscape favicon.svg --export-filename=favicon-32.png --export-width=32
inkscape favicon.svg --export-filename=favicon-16.png --export-width=16
convert favicon-16.png favicon-32.png favicon.ico

# Using ImageMagick only (lower quality SVG rendering)
convert -background none -resize 32x32 favicon.svg favicon-32.png
convert favicon-16.png favicon-32.png favicon.ico
```

Place the resulting `favicon.ico` in `web/public/logo/` and add a second `<link>` tag
in `index.html`:

```html
<link rel="icon" type="image/svg+xml" href="/logo/favicon.svg" />
<link rel="icon" type="image/x-icon"  href="/logo/favicon.ico" />
```
