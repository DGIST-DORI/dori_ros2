<br>
<p align="center">
  <img
    src="https://raw.githubusercontent.com/DGIST-DORI/dori/master/assets/icon/dori_text.svg"
    alt="dori logo"
    width="300">
</p>
<br>

[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-v2.0%20adopted-hotpink.svg)](CODE_OF_CONDUCT.md)
[![CodeQL Advanced](https://github.com/DGIST-DORI/dori/actions/workflows/codeql.yml/badge.svg)](https://github.com/DGIST-DORI/dori/actions/workflows/codeql.yml)

# DORI

[DORI](https://dgist-dori.xyz) (Dual-shell Omnidirectional Robot for Interaction, stylized as *Dori*) is a spherical campus guide robot capable of navigating diverse campus environments while providing LLM-powered voice interaction.

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

Install all dependencies for the core voice interface packages (`stt_pkg`, `tts_pkg`, `llm_pkg`, `hri_pkg`, `dashboard_pkg`, `system_monitor_pkg`) in a single step below.

```bash
pip3 install -r requirements.txt
```

The root `requirements.txt` refers to the following files:

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

---

## License

This project is developed as part of the DGIST UGRP (Undergraduate Group Research Program).
