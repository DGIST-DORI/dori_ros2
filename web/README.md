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

## Panel structure convention

패널 구현은 `web/src/panels/<domain>/` 아래에만 둡니다. 각 패널은 **1파일 1컴포넌트** 원칙을 따릅니다 (예: `web/src/panels/system/EventLogPanel.jsx`, `web/src/panels/hri/STTPanel.jsx`).

- 예시 도메인 폴더: `hri/`, `cube/`, `knowledge/`, `conversation/`, `face/`, `system/`
- `web/src/panelTree.jsx`는 패널 컴포넌트를 `web/src/panels/...`에서만 import 합니다.
- `web/src/tabs/`는 신규 구현 위치가 아니며, 기존 코드 호환을 위한 **legacy compatibility layer**로만 유지합니다.
- 신규/이관 스타일은 반드시 패널 인접 CSS(`web/src/panels/<domain>/<PanelName>.css`)에 둡니다. 여러 패널이 공유하는 레이아웃/토큰성 스타일은 `web/src/styles/shared/`에 둡니다.

### 새 패널 추가 절차

1. `web/src/panels/<domain>/`에 새 패널 파일을 추가합니다 (한 파일에 한 패널 컴포넌트).
2. 패널 컴포넌트를 named export로 노출합니다.
3. `web/src/panelTree.jsx`에 해당 패널 import를 추가합니다.
4. `PANEL_TREE`의 적절한 leaf 노드에 `component: <YourPanelComponent>`를 등록합니다.
5. 필요 시에만 `web/src/tabs/`의 레거시 진입점에 re-export를 추가합니다.


- System 패널에는 `Event Log`와 `Topic Publisher`가 포함되며 경로는 각각 `web/src/panels/system/EventLogPanel.jsx`, `web/src/panels/system/TopicPublisherPanel.jsx`입니다.

### Header ownership rule

- Floating workspace (`FloatingPanel`) and mobile stack (`MobileStack`) own the window title + minimize/close controls. Panels opened there must render content-only roots and must not recreate an internal `Panel` header.
- Sidebar or fixed tab layouts may still use `web/src/components/Panel.jsx` when they need a local card header/body shell.
- When moving a panel between layouts, keep header responsibility in exactly one layer and move any padding, overflow, or badge UI into the panel-specific root/CSS.
