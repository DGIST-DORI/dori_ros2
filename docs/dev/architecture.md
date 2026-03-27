# Architecture

## System Architecture

### Hardware

#### Component

Based on: https://www.notion.so/2f869a97d828815ea997c18536e5388d?v=2f869a97d8288142962f000c1662184d

Last updated: March 10, 2026.

**Total Estimated Cost:** ₩4,387,816  
**Total Weight (major components):** ~2,632 g
<details>
    <summary>Component list</summary>
    
| Component | Spec | Weight (g) | Power (W) | Voltage (V) | Price (₩) | Stock | Notes |
|---|---|---|---|---|---|---|---|
| Compute | NVIDIA Jetson Orin Nano Super | 176 | 7–25 | 9–20 (19V nominal) | 480,000 | 1 | Main onboard computer |
| Camera | Intel RealSense D435i | 72 | 2 | USB-C | 526,000 | 2 | RGB-D camera |
| Motor 1–2 | CubeMars AK45-10 KV75 | 260 | 50.4 / 120 | 24 | 240,900 | 2 | Ordered |
| Motor 3–4 | ROBOTIS Dynamixel XH430-V350-R | 82 | 1.44 / 16.8 | 24 | 387,200 | 2 | Ordered |
| Link Component | CubeMars Rubik Link | – | – | – | 64,300 | 1 | Ordered |
| Interface | ROBOTIS U2D2 | – | – | – | 39,300 | 1 | Ordered |
| Interface | ROBOTIS U2D2 Hub | – | – | – | 24,780 | 1 | Ordered |
| CAN Adapter | Waveshare USB-CAN-A | – | – | USB | 52,700 | 1 | Ordered |
| Jetson Power | 24V→19V Step-down Converter (10A) | 270 | – | 24→19 | 28,500 | 1 | Jetson power regulation |
| IMU | - | - | - | - | 1 | - |
| Microphone | Hollyland Lark M2 | 15 / 87 | <1 | USB-C | 123,000 | 1 | Wireless mic |
| Speaker | Adafruit USB Powered Mini Speaker | 73.6 | 4 | 5 | 28,300 | 1 | USB powered |
| Ultrasonic Sensor | DFRobot Gravity URM09 (I2C) | – | – | – | – | 4 | Distance sensing |
| Battery | HRB LiPo 6S 8000mAh (22.2V) | 1155 | – | 22.2 | 225,782 | 2 | Main battery |
| Battery Monitor | LiPo Voltage Tester / Alarm | – | – | – | 3,100 | 1 | Battery safety |
| Charger | SKYRC B6 Neo Charger (200W / 20A) | – | – | – | 55,000 | 1 | LiPo charger |
| Power Cable | XT60 F → DC 5.5×2.1mm Cable | – | – | – | 7,600 | 1 | Jetson power input |
| Power Connector | XT60 Connector Socket | – | – | – | 1,300 | 30 | Power distribution |
| Power Cable | 14AWG 2P Power Cable | – | – | – | 1,600 | 10 | Wiring |
| USB Hub | NEXT-614U3 (4-port USB hub) | 34 | – | – | 9,020 | 1 | Peripheral expansion |
| Frame | Aluminum Pipe 16mm / 2T / 3000mm | – | – | – | 15,200 | 1 | Structural frame |
| Frame | Aluminum Pipe 10mm / 2T / 2500mm | – | – | – | 10,300 | 1 | Cut into 12×170mm |
| Frame | Aluminum Pipe 12mm / 1T / 500mm | – | – | – | 3,700 | 1 | Structural frame |
| Tool | Pipe Reamer | – | – | – | 39,270 | 1 | Assembly tool |
| Frame Part | Aluminum Flange (16mm inner diameter) | – | – | – | 10,100 | 9 | Pipe mounting |
| Bearing | 6" Lazy Susan Bearing | – | – | – | 8,530 | 5 | Rotation joint |
| Bearing | C-E6004ZZ Bearing | – | – | – | 1,903 | 8 | Mechanical support |
| Bearing | C-E6701ZZ Bearing | – | – | – | 1,276 | 8 | Mechanical support |
| Tool | Pipe Cutter | – | – | – | 17,500 | 1 | Assembly tool |

</details>

#### Robot Infomation
|||
|---|---|
| Robot form | Spherical, 540 mm diameter, dual-shell cube mechanism |
| Camera height | 270 mm |

### Software Packages

```
ros2_ws/src/
├── perception_pkg/       # Perception: camera, person detection, gesture, expression, landmark
├── interaction_pkg/      # Interaction coordinator (HRI manager state machine)
├── hri_pkg/              # HRI nodes
├── stt_pkg/              # Wake word (Porcupine) + transcription (Whisper)
├── llm_pkg/              # Intent classification + RAG + LLM response
├── tts_pkg/              # Text-to-speech playback
├── navigation_pkg/       # Navigation execution node
├── dashboard_pkg/        # ROS ↔ web dashboard bridge
└── bringup/              # Launch files
    ├── robot.launch.py           # Full robot (top-level)
    ├── perception.launch.py      # Perception only
    ├── interaction.launch.py     # HRI manager/state machine only
    └── voice.launch.py # Voice pipeline only
```

### ROS2 Topic List (Actual Nodes)

The detailed API reference for ROS2 topics is managed as a single source at [`topics.adoc`](docs/dev/topics.adoc).

- Topic source of truth: [`config/ros2_topics.yaml`](config/ros2_topics.yaml)
- Sync/check tool: `python3 tools/topic/topic_lint.py --sync-architecture`, `python3 tools/topic/topic_lint.py --check`
- Detailed documentation: [`docs/dev/topics.adoc`](docs/dev/topics.adoc)

#### Camera topic naming policy (Python/C++ depth camera parity)

- Canonical rule: depth camera nodes must publish to **relative topics** (e.g. `color/image_raw`, `depth/image_raw`) inside node code.
- Launch files own final routing by injecting `/dori` namespace/remapping to app-level canonical topics (e.g. `/dori/camera/color/image_raw`).
- Do not hardcode absolute `/dori/...` camera publish topics inside node implementations.
- This rule applies equally to:
  - `perception_pkg/perception_pkg/depth_camera_node.py` (Python)
  - `perception_camera_cpp/src/depth_camera_node.cpp` (C++)


---

## HRI State Machine

```
         wake word / WAVE gesture
IDLE ──────────────────────────────► LISTENING
  ▲                                      │
  │                                 STT result
  │ idle timeout (10 s)                  │
  │                                      ▼
  │                                 RESPONDING ──► LLM query
  │                                      │
  │                               TTS done / nav intent
  │                                      │
  └────────────── target lost ◄─── NAVIGATING
```
