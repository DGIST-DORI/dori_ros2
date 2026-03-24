<p align="center">
  <img
    src="https://raw.githubusercontent.com/DGIST-DORI/dori/master/assets/icon/dori_text.svg"
    alt="dori logo"
    width="300">
</p>

[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-v2.0%20adopted-hotpink.svg)](CODE_OF_CONDUCT.md)
[![CodeQL Advanced](https://github.com/DGIST-DORI/dori/actions/workflows/codeql.yml/badge.svg)](https://github.com/DGIST-DORI/dori/actions/workflows/codeql.yml)

# DORI

[DORI](https://dgist-dori.xyz) is a spherical campus guide robot capable of navigating diverse campus environments while providing LLM-powered voice interaction.

> UGRP 2026 — DGIST

## Installation

### Prerequisites

- JetPack 6
- Ubuntu 22.04
- ROS2 Humble
- Python 3.10+
- CUDA 11+ (for Jetson or GPU workstation)

### 1. Install System Dependencies

```bash
sudo apt update
sudo apt install -y \
  portaudio19-dev python3-pyaudio ffmpeg libsndfile1 mpg123 \
  ros-humble-rosbridge-server ros-humble-realsense2-camera
```

### 2. Clone Repository

```bash
git clone https://github.com/DGIST-DORI/dori
cd dori
```

### 3. Install Python Dependencies

#### Required (Common)

Install all dependencies for the core voice interface packages (`stt_pkg`, `tts_pkg`, `llm_pkg`) in a single step below.

```bash
pip3 install -r requirements.txt
```

The root `requirements.txt` refers to the following files:

- `src/stt_pkg/requirements.txt`
- `src/tts_pkg/requirements.txt`
- `src/llm_pkg/requirements.txt`

#### Optional (Additional installations per package)

Please install the following additionally for each feature.

- `hri_pkg` (Camera/Vision Function):

  ```bash
  pip3 install opencv-python mediapipe ultralytics pyrealsense2
  ```

- `llm_pkg` When using external model APIs: API key setup required (`OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.)
- `stt_pkg` When using Silero VAD: `torch` installation recommended

### 4. Set API Keys

```bash
# Porcupine wake word (required)
echo 'export PORCUPINE_ACCESS_KEY="your_key_here"' >> ~/.bashrc

# Optional: external LLM providers
echo 'export OPENAI_API_KEY="your_key_here"' >> ~/.bashrc
echo 'export GEMINI_API_KEY="your_key_here"' >> ~/.bashrc

source ~/.bashrc
```

Get your Porcupine key for free at [Picovoice Console](https://console.picovoice.ai/).

### 5. Build

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

---

## Usage

### Full Robot

```bash
ros2 launch bringup robot.launch.py
```

### Full Robot (with Dashboard)
 
Launches the full robot stack together with the web dashboard (rosbridge + HTTP server + knowledge API).
The dashboard frontend must be built before the first run.
 
```bash
# First time only — build the frontend assets
cd web && npm ci && npm run build && cd ..
colcon build --symlink-install
source install/setup.bash
 
# Launch
ros2 launch bringup robot.launch.py enable_dashboard:=true
```
 
Dashboard access:
 
```text
# Same machine
http://localhost:3000
 
# Remote (another device on the same network)
http://[Robot IP]:3000
```

> Note: Port `3000` is now served directly by `knowledge_api.py` (unified frontend + API server).
> If dashboard launch fails on startup, first verify runtime dependencies are installed (`fastapi`, `uvicorn`, `python-multipart`).

### Common Launch Options

```bash
# Use external LLM instead of local model
ros2 launch bringup robot.launch.py use_external_llm:=true

# SW development without navigation hardware
ros2 launch bringup robot.launch.py enable_navigation:=false

# Change Whisper model size (tiny / base / small / medium)
ros2 launch bringup robot.launch.py whisper_model:=base

# Change TTS language
ros2 launch bringup robot.launch.py tts_language:=ko
```

### Sub-system Launch (Development)

```bash
# HRI perception only (cameras + detection nodes)
ros2 launch bringup hri.launch.py visualize:=true

# Voice pipeline only (no cameras needed)
ros2 launch bringup voice_interface.launch.py
```

### Testing Without Hardware

Perception and voice nodes can be tested independently using manual topic injection:

```bash
# Terminal 1: start HRI manager
ros2 run hri_pkg hri_manager_node

# Terminal 2: simulate wake word
ros2 topic pub /dori/stt/wake_word_detected std_msgs/msg/Bool "data: true" --once

# Terminal 3: simulate STT result
ros2 topic pub /dori/stt/result std_msgs/msg/String \
  'data: "{\"text\": \"도서관 어디야\", \"language\": \"ko\", \"confidence\": 0.95}"' --once

# Monitor state
ros2 topic echo /dori/hri/manager_state
ros2 topic echo /dori/tts/text
```

---

## Interaction Flow

DORI wakes on the keyword **"porcupine"** (temporary; to be replaced with custom keyword (Dori)).

```
User: "porcupine"           → IDLE → LISTENING
User: "도서관 어디야?"        → STT transcription
DORI: "도서관으로 안내할게요." → LLM response → TTS playback → NAVIGATING
```

Alternatively, a **WAVE** gesture activates the same wake-word handler for users who prefer not to speak.

### Supported Gestures

| Gesture | Action |
|---|---|
| WAVE | Activate DORI (same as wake word) |
| STOP | Pause navigation |
| POINT | Provide directional hint |
| THUMBS_UP | Positive confirmation |

---

## Dashboard

A browser-based debug dashboard is available, serving both an HRI monitor and a 3×3 cube simulator.

```bash
# 1) Build the frontend assets first (required)
cd web
npm ci   # or: npm install
npm run build

# 2) Return to ROS workspace root
cd ..

# 3) Build workspace and source overlay
colcon build --symlink-install
source install/setup.bash

# 4) Start dashboard backend (rosbridge + HTTP server)
ros2 launch dashboard_pkg dashboard.launch.py
```

Dashboard access endpoints:

- Dashboard URL: `http://[Robot IP]:3000`
- ROS WebSocket URL: `ws://[Robot IP]:9090`

Connection examples:

```text
# Local access on robot host
http://localhost:3000
ws://localhost:9090

# Remote access from another device on the same network
http://[Robot IP]:3000
ws://[Robot IP]:9090
```

The dashboard displays real-time topic values, HRI state, person tracking, gesture/expression state, and event log through the ROS WebSocket bridge.

---

## Development Notes

### Resource Management (Jetson Orin Nano)

- **Camera FPS:** 15 Hz (two D435s at 30 Hz saturates USB 3.0 bandwidth)
- **YOLOv8:** TensorRT inference on GPU (~5 ms/frame); infers every 2–3 frames
- **MediaPipe gesture/expression:** activates only after wake word (Tier 3 resource)
- **LLM:** offload to external server recommended for 7B+ models
- **SLAM:** 

### Coordinate System (Cube Robot)

```
Origin: cube center (0, 0, 0)
  x: right = +1,  left  = -1
  y: up    = +1,  down  = -1
  z: front = +1,  back  = -1

Robot axes (rotatable): U, R, L, B
Internal axes (fixed):  F, D
```

### Adding Campus Knowledge

Edit `/data/campus/indexed/campus_knowledge.json`:

```json
"E8": {
      "bldg_no": "E8",
      "class": "E",
      "name_ko": "학술정보관",
      "name_en": "Central Library",
      "description_ko": "학술정보관입니다. 열람실과 스터디룸이 있습니다.",
      "description_en": "",
      "coordinates": [0.0, 0.0],
      "floor": 6,
      "keywords": ["도서관", "책", "공부", "열람실", "library", "study"],
      "hours": "09:00-24:00",
      "facilities": ["열람실", "그룹스터디룸", "북카페"],
      "url": "https://library.dgist.ac.kr/main.do"
    },
```

### Training a Custom Landmark Model

```bash
# Prepare dataset (YOLO format) and edit config/data.yaml
ros2 run hri_pkg train_landmark \
  --data config/data.yaml \
  --model yolov8n.pt \
  --epochs 100
```

---

## License

This project is developed as part of the DGIST UGRP (Undergraduate Group Research Program).
