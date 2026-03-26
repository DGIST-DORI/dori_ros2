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
src/
├── perception_pkg/       # Perception: camera, person detection, gesture, expression, landmark
├── interaction_pkg/      # Interaction coordinator (HRI manager state machine)
├── hri_pkg/              # Legacy launch wrappers / auxiliary HRI nodes
├── stt_pkg/              # Wake word (Porcupine) + transcription (Whisper)
├── llm_pkg/              # Intent classification + RAG + LLM response
├── tts_pkg/              # Text-to-speech playback
├── navigation_pkg/       # Navigation execution node
├── dashboard_pkg/        # ROS ↔ web dashboard bridge
└── bringup/              # Launch files
    ├── robot.launch.py           # Full robot (top-level)
    ├── hri.launch.py             # HRI perception only
    └── voice.launch.py # Voice pipeline only
```

### ROS2 Topic Map

All topics are namespaced under `/dori/`.

```
/dori/
├── camera/
│   ├── color/image_raw
│   ├── depth/image_raw
│   └── rear/color/image_raw
├── stt/
│   ├── wake_word_detected  (Bool)    wake word trigger
│   └── result              (String)  JSON {text, language, confidence}
├── hri/
│   ├── manager_state       (String)  current HRI state
│   ├── persons             (String)  YOLO detection JSON
│   ├── tracking_state      (String)  ByteTrack state JSON
│   ├── gesture             (String)  MediaPipe gesture
│   └── expression          (String)  face expression
├── llm/
│   ├── query               (String)  user text + location context
│   └── response            (String)  generated response
├── tts/
│   ├── text                (String)  direct TTS bypass
│   ├── speaking            (Bool)    mutes STT while speaking
│   └── done                (Bool)    playback finished signal
├── follow/
│   └── target_offset       (Point)   person-following offset for nav
└── nav/
    ├── command             (String)  high-level nav command
    └── destination         (PoseStamped) goal pose from LLM
```

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
