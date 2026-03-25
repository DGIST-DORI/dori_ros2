"""
Voice interface + HRI Manager.

Nodes started:
  hri_manager_node   (interaction_pkg)  - central HRI state machine
  stt_node           (stt_pkg)  - wake word + speech transcription
  llm_node           (llm_pkg)  - intent classification + RAG + LLM
  tts_node           (tts_pkg)  - text-to-speech playback

Topic flow:
  microphone
    → stt_node → /dori/stt/wake_word_detected → hri_manager_node
    → stt_node → /dori/stt/result             → hri_manager_node
    → hri_manager_node → /dori/llm/query      → llm_node
    → llm_node  → /dori/llm/response          → tts_node
    → hri_manager_node → /dori/tts/text       → tts_node  (direct speech)
    → tts_node  → /dori/tts/speaking          → stt_node  (mute while speaking)
    → tts_node  → /dori/tts/done              → hri_manager_node
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _resolve_path(share_relative: str, pkg_name: str, data_relative: str) -> str:
    """
    Resolve an asset path at launch time.
    Tries the installed share directory first, then walks up to the repo root.

    Args:
        share_relative: path relative to package share dir, e.g. 'config/foo.json'
        pkg_name:       package that owns the asset in share
        data_relative:  path relative to repo root, e.g. 'data/campus/indexed/foo.json'

    Returns:
        Absolute path string, or empty string if neither location exists.
    """
    import pathlib

    # Priority 1: ROS2 share directory (installed)
    try:
        share_path = pathlib.Path(get_package_share_directory(pkg_name)) / share_relative
        if share_path.exists():
            return str(share_path)
    except Exception:
        pass

    # Priority 2: repo root (development)
    this_file = pathlib.Path(__file__).resolve()
    for parent in this_file.parents:
        if (parent / 'src').is_dir() and (parent / 'README.md').exists():
            candidate = parent / data_relative
            if candidate.exists():
                return str(candidate)
            break

    return ''


def generate_launch_description():

    # Resolve paths at launch time (not at import time)
    knowledge_file_path = _resolve_path(
        share_relative='config/campus_knowledge.json',
        pkg_name='llm_pkg',
        data_relative='data/campus/indexed/campus_knowledge.json',
    )

    rag_index_dir_path = _resolve_path(
        share_relative='indexed',  # llm_pkg doesn't install the index; dev only
        pkg_name='llm_pkg',
        data_relative='data/campus/indexed',
    )

    wake_word_model_path = _resolve_path(
        share_relative='models/doridori_ko_linux_v4_0_0.ppn',
        pkg_name='stt_pkg',
        data_relative='src/stt_pkg/models/doridori_ko_linux_v4_0_0.ppn',
    )

    # Arguments
    args = [
        DeclareLaunchArgument('use_external_llm',
            default_value='false',
            description='Use external LLM API (OpenAI / Anthropic / Gemini)'),
        DeclareLaunchArgument('knowledge_file',
            default_value=knowledge_file_path,
            description='Path to campus_knowledge.json'),
        DeclareLaunchArgument('rag_index_dir',
            default_value=rag_index_dir_path,
            description='Path to FAISS index directory (data/campus/indexed)'),
        DeclareLaunchArgument('whisper_model',
            default_value='small',
            description='Whisper model size: tiny / base / small / medium / large'),
        DeclareLaunchArgument('wake_word',
            default_value='porcupine',
            description='Porcupine wake word keyword'),
        DeclareLaunchArgument('wake_word_paths',
            default_value=wake_word_model_path,
            description='Path to custom Porcupine wake word .ppn file'),
        DeclareLaunchArgument('tts_engine',
            default_value='gtts',
            description='TTS engine: gtts (online) or pyttsx3 (offline)'),
        DeclareLaunchArgument('tts_language',
            default_value='ko',
            description='TTS output language'),
        DeclareLaunchArgument('idle_timeout_sec',
            default_value='10.0',
            description='Seconds to wait for STT input before returning to IDLE'),
        DeclareLaunchArgument('llm_model',
            default_value='gemini-2.0-flash',
            description='External LLM model name'),
        DeclareLaunchArgument('rag_top_k',
            default_value='3',
            description='Number of RAG chunks to retrieve per query'),
    ]

    # HRI Manager Node
    hri_manager_node = Node(
        package='interaction_pkg',
        executable='hri_manager_node',
        name='hri_manager_node',
        output='screen',
        parameters=[{
            'idle_timeout_sec': LaunchConfiguration('idle_timeout_sec'),
            'greeting_text':    '안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?',
        }],
    )

    # STT Node
    stt_node = Node(
        package='stt_pkg',
        executable='stt_node',
        name='stt_node',
        output='screen',
        parameters=[{
            'wake_word':        LaunchConfiguration('wake_word'),
            'wake_word_paths':  LaunchConfiguration('wake_word_paths'),
            'whisper_model':    LaunchConfiguration('whisper_model'),
            'whisper_device':   'cpu',
            'vad_threshold':    0.5,
            'silence_duration': 1.2,
        }],
    )

    # LLM Node
    llm_node = Node(
        package='llm_pkg',
        executable='llm_node',
        name='llm_node',
        output='screen',
        parameters=[{
            'knowledge_file':   LaunchConfiguration('knowledge_file'),
            'rag_index_dir':    LaunchConfiguration('rag_index_dir'),
            'use_external_llm': LaunchConfiguration('use_external_llm'),
            'model_name':       LaunchConfiguration('llm_model'),
            'rag_top_k':        LaunchConfiguration('rag_top_k'),
        }],
    )

    # TTS Node
    tts_node = Node(
        package='tts_pkg',
        executable='tts_node',
        name='tts_node',
        output='screen',
        parameters=[{
            'tts_engine':  LaunchConfiguration('tts_engine'),
            'language':    LaunchConfiguration('tts_language'),
            'speech_rate': 150,
            'volume':      0.9,
        }],
    )

    return LaunchDescription([
        *args,
        hri_manager_node,
        stt_node,
        llm_node,
        tts_node,
    ])
