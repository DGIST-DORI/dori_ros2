# DORI Dashboard Frontend (`web`)

This directory contains the Vite/React frontend for the DORI dashboard.

## Build (Required before first launch)

Build frontend assets before launching the dashboard.

```bash
cd web
npm ci   # or: npm install
npm run build
```

After the build completes, continue from the ROS workspace root:

```bash
cd ..
colcon build --symlink-install
source install/setup.bash
```

## Launch
 
The dashboard is launched as part of the main robot stack via the `enable_dashboard` flag:
 
```bash
ros2 launch bringup robot.launch.py enable_dashboard:=true
```
 
If you need to run the dashboard standalone (without the full robot stack):
 
```bash
ros2 launch dashboard_pkg dashboard.launch.py
```
 
## Access

- Dashboard: `http://[Robot IP]:3000` (`knowledge_api.py` serves port 3000)
- ROS WebSocket bridge: `ws://[Robot IP]:9090`

If dashboard startup fails, check whether runtime dependencies are installed in the ROS/Python environment: `fastapi`, `uvicorn`, `python-multipart`.

```text
# Same machine (robot/local)
http://localhost:3000
ws://localhost:9090

# Another device on same network (remote)
http://[Robot IP]:3000
ws://[Robot IP]:9090
```

For broader project context, see the root README: `../README.md`.

## Style system

공유 스타일은 `web/src/styles/` 아래 세 파일로 관리한다.

```
web/src/styles/
  tokens.css      ← 색상·폰트·간격 토큰
  layout.css      ← 그리드 레이아웃 클래스
  components.css  ← 버튼·배지·입력창 등 재사용 UI
```

`index.css`가 세 파일을 전역 import하므로, 패널 CSS에서는 필요한 파일만 `@import`한다.
디자인 규약 전체는 `CODING_RULES.md`를 참조한다.

## Panel structure convention

패널 구현은 `web/src/panels/<domain>/` 아래에만 둔다. 각 패널은 **1파일 1컴포넌트** 원칙을 따른다 (예: `web/src/panels/system/EventLogPanel.jsx`, `web/src/panels/hri/STTPanel.jsx`).

- 예시 도메인 폴더: `hri/`, `cube/`, `knowledge/`, `conversation/`, `face/`, `system/`
- `web/src/panelTree.jsx`는 패널 컴포넌트를 `web/src/panels/...`에서만 import한다.
- `web/src/tabs/`는 신규 구현 위치가 아니며, 기존 코드 호환을 위한 **legacy compatibility layer**로만 유지한다.
- 신규/이관 스타일은 반드시 패널 인접 CSS(`web/src/panels/<domain>/<PanelName>.css`)에 둔다. 여러 패널이 공유하는 레이아웃·컴포넌트 스타일은 `web/src/styles/` 아래 세 파일에 둔다.

### 새 패널 추가 절차

1. `web/src/panels/<domain>/`에 새 패널 파일을 추가한다 (한 파일에 한 패널 컴포넌트).
2. 패널 컴포넌트를 named export로 노출한다.
3. `web/src/panelTree.jsx`에 해당 패널 import를 추가한다.
4. `PANEL_TREE`의 적절한 leaf 노드에 `component: <YourPanelComponent>`를 등록한다.
5. `web/src/core/floatingPanels.js`의 `PANEL_SIZES`에 기본 창 크기를 추가한다.
6. 필요 시에만 `web/src/tabs/`의 레거시 진입점에 re-export를 추가한다.

- System 패널에는 `Event Log`와 `Topic Publisher`가 포함되며 경로는 각각 `web/src/panels/system/EventLogPanel.jsx`, `web/src/panels/system/TopicPublisherPanel.jsx`이다.

### Header ownership rule

- Floating workspace (`FloatingPanel`) and mobile stack (`MobileStack`) own the window title + minimize/close controls. Panels opened there must render content-only roots and must not recreate an internal `Panel` header.
- Sidebar or fixed tab layouts may still use `web/src/components/Panel.jsx` when they need a local card header/body shell.
- When moving a panel between layouts, keep header responsibility in exactly one layer and move any padding, overflow, or badge UI into the panel-specific root/CSS.
