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

### ROS2 Topic Map (Actual Nodes)

#### Topic Map source of truth

- Source file: `docs/ros/topic_map.yaml`.
- This section is generated/synchronized from the YAML file via `python3 tools/topic_map/topic_map_lint.py --sync-architecture`.
- CI runs `python3 tools/topic_map/topic_map_lint.py --check` and emits warnings if drift is detected.

<!-- TOPIC_MAP:START -->
#### In-scope application topics

| Topic | Msg type | Publisher(s) | Subscriber(s) | Description |
|---|---|---|---|---|
| `/dori/camera/color/image_raw` | `sensor_msgs/msg/Image` | depth_camera_node | person_detection_node, gesture_recognition_node, facial_expression_node, landmark_detection_node | RGB camera stream used by all perception pipelines. |
| `/dori/camera/depth/image_raw` | `sensor_msgs/msg/Image` | depth_camera_node | person_detection_node, landmark_detection_node | Raw depth frame for distance estimation and landmark range filtering. |
| `/dori/camera/depth/image_colormap` | `sensor_msgs/msg/Image` | depth_camera_node | - | Colorized depth visualization stream. |
| `/dori/camera/color/camera_info` | `sensor_msgs/msg/CameraInfo` | depth_camera_node | landmark_detection_node | RGB intrinsics for pixel-to-direction / localization math. |
| `/dori/camera/depth/camera_info` | `sensor_msgs/msg/CameraInfo` | depth_camera_node | - | Depth intrinsics metadata stream. |
| `/dori/camera/depth_scale` | `std_msgs/msg/Float32` | - | person_detection_node | Optional depth meter-per-unit scale expected by person detection. |
| `/dori/hri/persons` | `std_msgs/msg/String` | person_detection_node | - | JSON list of detected persons/tracks. |
| `/dori/hri/interaction_trigger` | `std_msgs/msg/Bool` | person_detection_node | gesture_recognition_node, facial_expression_node | Enables gesture/expression inference only during interaction. |
| `/dori/hri/tracking_state` | `std_msgs/msg/String` | person_detection_node | hri_manager_node | JSON tracking state (`idle/tracking/lost`) for session/nav control. |
| `/dori/follow/target_offset` | `geometry_msgs/msg/Point` | person_detection_node | - | Relative target offset for follow-control consumers. |
| `/dori/hri/annotated_image` | `sensor_msgs/msg/Image` | person_detection_node | - | Person detection debug overlay image. |
| `/dori/hri/gesture` | `std_msgs/msg/String` | gesture_recognition_node | - | Gesture detection JSON payload. |
| `/dori/hri/gesture_command` | `std_msgs/msg/String` | gesture_recognition_node | hri_manager_node | Mapped high-level gesture command (`STOP`, `CALL`, etc.). |
| `/dori/stt/wake_word_detected` | `std_msgs/msg/Bool` | gesture_recognition_node (WAVE trigger), external STT node | hri_manager_node | Wake event that starts HRI listening flow. |
| `/dori/hri/annotated_gesture` | `sensor_msgs/msg/Image` | gesture_recognition_node | - | Gesture visualization/debug image. |
| `/dori/hri/expression` | `std_msgs/msg/String` | facial_expression_node | - | Expression inference JSON payload. |
| `/dori/hri/expression_command` | `std_msgs/msg/String` | facial_expression_node | hri_manager_node | HRI action hint from expression state. |
| `/dori/hri/annotated_expression` | `sensor_msgs/msg/Image` | facial_expression_node | - | Facial expression visualization/debug image. |
| `/dori/landmark/detections` | `std_msgs/msg/String` | landmark_detection_node | - | Raw landmark/candidate detections as JSON. |
| `/dori/landmark/localization` | `std_msgs/msg/String` | landmark_detection_node | - | Landmark-based localization estimate JSON. |
| `/dori/landmark/context` | `std_msgs/msg/String` | landmark_detection_node | hri_manager_node | Current location/context text used in LLM query payload. |
| `/dori/hri/annotated_landmark` | `sensor_msgs/msg/Image` | landmark_detection_node | - | Landmark detection visualization/debug image. |
| `/dori/stt/result` | `std_msgs/msg/String` | external STT node | hri_manager_node | User transcription JSON/text from speech recognizer. |
| `/dori/tts/done` | `std_msgs/msg/Bool` | tts_node | hri_manager_node | Playback completion event for HRI state transitions. |
| `/dori/hri/set_follow_mode` | `std_msgs/msg/Bool` | hri_manager_node | person_detection_node | Enable/disable person target registration and follow behavior. |
| `/dori/hri/manager_state` | `std_msgs/msg/String` | hri_manager_node | - | Current HRI state heartbeat (`IDLE`, `LISTENING`, etc.). |
| `/dori/llm/query` | `std_msgs/msg/String` | hri_manager_node | llm_node | JSON request containing user text + contextual fields. |
| `/dori/tts/text` | `std_msgs/msg/String` | hri_manager_node | tts_node | Direct TTS text (bypass LLM for prompts/system messages). |
| `/dori/nav/command` | `std_msgs/msg/String` | hri_manager_node | - | High-level navigation command channel. |
| `/dori/llm/response` | `std_msgs/msg/String` | llm_node | tts_node | Generated natural-language response text. |
| `/dori/nav/destination` | `geometry_msgs/msg/PoseStamped` | llm_node | navigator_node | Navigation goal pose extracted from navigation intent. |
| `/dori/tts/speaking` | `std_msgs/msg/Bool` | tts_node | - | True while TTS is actively speaking (used for mic mute by external STT). |
| `/dori/nav/global_path` | `nav_msgs/msg/Path` | navigator_node | - | Planned global path visualization/output. |
| `/dori/nav/local_path` | `nav_msgs/msg/Path` | navigator_node | - | Local path / short-horizon trajectory visualization. |
| `/dori/nav/status` | `std_msgs/msg/String` | navigator_node | - | Human-readable navigation status updates. |
| `/dori/nav/cancel` | `std_msgs/msg/Bool` | external/nav client node | navigator_node | Cancel signal for current navigation task. |
| `/dori/system/metrics` | `std_msgs/msg/String` | system_monitor_node | - | Periodic system metrics JSON (CPU/RAM/Disk/GPU). |

#### Out of documentation scope (base platform topics)

| Topic | Msg type | Publisher(s) | Subscriber(s) | Description |
|---|---|---|---|---|
| `/odom` | `nav_msgs/msg/Odometry` | Base controller / localization stack | navigator_node | Robot odometry pose/velocity input. |
| `/scan` | `sensor_msgs/msg/LaserScan` | LiDAR driver | navigator_node | Laser range scan for obstacle detection/avoidance. |
| `/map` | `nav_msgs/msg/OccupancyGrid` | SLAM / map server | navigator_node | Occupancy map used for global path planning. |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | navigator_node | Base controller / motor interface | Velocity command output to robot base. |
<!-- TOPIC_MAP:END -->


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

---

## Node Reference

### `hri_manager_node` (`interaction_pkg`)
Central coordinator. Manages the state machine and routes messages between all HRI subsystems.

### `person_detection_node` (`perception_pkg`)
YOLOv8 + ByteTrack full-body person detection with depth-based distance estimation. Publishes tracking state and follow offset for navigation.

### `gesture_recognition_node` (`perception_pkg`)
MediaPipe Hands — classifies STOP / POINT / WAVE / THUMBS_UP from 21-point hand landmarks. CPU-only; activates only after interaction trigger.

### `facial_expression_node` (`perception_pkg`)
MediaPipe Face Mesh — classifies SATISFIED / CONFUSED / NEUTRAL from 468-point face landmarks. Activates only after interaction trigger.

### `landmark_detection_node` (`perception_pkg`)
YOLOv8 landmark detection for SLAM drift correction and LLM location context. Fine-tunable on campus-specific dataset.

### `stt_node`
Always-on Porcupine wake word detection. On trigger, activates Whisper transcription with Silero VAD for speech-end detection. Mutes itself while TTS is playing.

### `llm_node`
Intent classification (navigation / information / greeting / general) + lightweight RAG over campus knowledge base (locations + FAQs). Supports local inference or external API (OpenAI / Anthropic).

### `tts_node`
Korean TTS with `gtts` (online) or `pyttsx3` (offline). Publishes `/dori/tts/speaking` to mute the microphone during playback.
