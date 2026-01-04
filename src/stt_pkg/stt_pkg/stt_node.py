import rclpy
from rclpy.node import Node

from std_msgs.msg import String, Bool

import sounddevice as sd
import numpy as np
import queue
import struct
import time

import pvporcupine
from faster_whisper import WhisperModel
from faster_whisper.vad import Vad


SAMPLE_RATE = 16000
FRAME_LENGTH = 512 # Porcupine
CHANNELS = 1

MAX_BUFFER_SEC = 10.0 
VAD_SILENCE_SEC = 0.8

FRAME_DURATION = 30  # ms
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION / 1000)
MAX_SPEECH_SECONDS = 8
MAX_FRAMES = int(MAX_SPEECH_SECONDS * 1000 / FRAME_DURATION)
MIN_SPEECH_FRAMES = int(0.5 * 1000 / FRAME_DURATION)


class STTNode(Node):
    def __init__(self):
        super().__init__('stt_node')

        # ROS
        self.text_pub = self.create_publisher(String, '/stt/text', 10)

        self.speaking_sub = self.create_subscription(
            Bool,
            '/robot/speaking',
            self.speaking_callback,
            10
        )

        # State var
        self.state = "IDLE"              # IDLE | LISTENING
        self.robot_speaking = False

        self.audio_queue = queue.Queue()
        self.buffer = []

        self.listen_start_time = None
        self.last_voice_time = None

        # Wake word
        self.porcupine = pvporcupine.create(
            keywords=["hey robot"]  # TODO
        )
        
        # VAD
        self.vad = Vad(
            sample_rate=SAMPLE_RATE,
            threshold=0.5
        )

        # Whisper
        self.get_logger().info("Loading Whisper model...")
        self.model = WhisperModel(
            "small", # tiny base small medium large
            device="cpu", # GPU: "cuda"
            compute_type="int8"
        )

        # Audio stream
        self.stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=FRAME_LENGTH,
            dtype="int16",
            channels=CHANNELS,
            callback=self.audio_callback
        )

        self.stream.start()

        # Timer
        self.timer = self.create_timer(0.1, self.process_audio)

        self.get_logger().info("STT node started.")

    # ROS callbacks
    def speaking_callback(self, msg: Bool):
        self.robot_speaking = msg.data

        if self.robot_speaking:
            self.get_logger().info("STT muted since Robot speaking")
            self.state = "IDLE"
            self.buffer.clear()
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()

    def audio_callback(self, indata, frames, time_info, status):
        if self.robot_speaking:
            return
        
        pcm = struct.unpack_from("h" * frames, indata)

        if self.state == "IDLE":
            keyword_index = self.porcupine.process(pcm)
            if keyword_index >= 0:
                self.get_logger().info("Wake word detected")
                self.state = "LISTENING"
                self.listen_start_time = time.time()
                self.last_voice_time = time.time()
                self.buffer.clear()

        elif self.state == "LISTENING":
            self.audio_queue.put(indata.copy())

    def process_audio(self):
        if self.robot_speaking:
            return

        if self.state != "LISTENING":
            return

        while not self.audio_queue.empty():
            chunk = self.audio_queue.get()
            audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            self.buffer.append(audio)

            # VAD
            if self.vad(audio):
                self.last_voice_time = time.time()

        now = time.time()

        if self.last_voice_time and (now - self.last_voice_time) > VAD_SILENCE_SEC:
            self.get_logger().info("Speech end detected.")
            self.transcribe_buffer()
            self.state = "IDLE"
            self.buffer.clear()

        if self.listen_start_time and (now - self.listen_start_time) > MAX_BUFFER_SEC:
            self.get_logger().warn("Max buffer exceeded, force transcribe.")
            self.transcribe_buffer()
            self.state = "IDLE"
            self.buffer.clear()

    def transcribe_buffer(self):
        if len(self.buffer) == 0:
            return
        
        if len(self.buffer) < MIN_SPEECH_FRAMES:
            self.get_logger().info("Too short, skip")
            return

        audio = np.concatenate(self.buffer, axis=0)

        self.get_logger().info(f"Transcribing {len(audio) / SAMPLE_RATE:.2f} s audio")

        segments, info = self.model.transcribe(
            audio,
            language=None,            # 자동 감지 (KO + EN 혼합)
            vad_filter=False,
            beam_size=5
        )

        text = "".join([seg.text for seg in segments]).strip()

        if text:
            self.get_logger().info(f"[{info.language}] {text}")
            self.text_pub.publish(String(data=text))
        else:
            self.get_logger().info("Empty transcription")

def main():
    rclpy.init()
    node = STTNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stream.stop()
        node.stream.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
