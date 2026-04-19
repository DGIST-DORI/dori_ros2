#!/usr/bin/env python3
import argparse
import base64
import copy
import json
import math
import os
import sys
import textwrap
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, Union

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from openai import OpenAI
from pydantic import BaseModel, Field
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Imu


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from rgb_depth_bev_current import (  # noqa: E402
    BirdEyeNode,
    DEFAULT_CAMERA_INFO_TOPIC,
    DEFAULT_DEPTH_TOPIC,
    DEFAULT_RGB_TOPIC,
)


WINDOW_NAME = "openai_bev_autodrive"
HISTORY_WINDOW = 24
PREVIOUS_CONTEXT_WINDOW = 12
PREVIOUS_BEV_IMAGE_WINDOW = 6
PREVIOUS_RGB_IMAGE_WINDOW = 2
CMD_PUBLISH_HZ = 10.0
WALL_ROUTE_PLAN_HOLD_STEPS = 10
STARTUP_EXPLORE_HOLD_STEPS = 4


SYSTEM_PROMPT = """Robotics Control System Prompt

Role
- You are an advanced Autonomous Navigation AI.
- Perform local path planning for a mobile robot from RGB, depth, and BEV inputs.
- Your primary job is to choose the next safe local target point in robot coordinates, then suggest a smooth speed profile for tracking it.
- Return only the next waypoint update now, but reason over remembered obstacles and safe short detours before choosing it.

Visual interpretation
- RGB image: reference only for semantics and scene context when BEV is ambiguous.
- Depth image: reference only for near-vs-far support, but do not use it to override BEV obstacle geometry.
- BEV image:
  - Origin is the robot's current egocentric position.
  - Up is the robot's current forward heading.
  - +x is robot-right, +z is robot-forward.
  - Yellow lines are the camera horizontal field of view.
  - Red points are non-traversable obstacle candidates.
  - A cyan ego circle around the origin shows the robot body footprint in the BEV.
  - Filled or shadowed red regions behind red points should also be treated as blocked or unknown, not as free space.

Task rules
- Safety first. Avoid collisions and keep a safety buffer from obstacles.
- Prioritize the red-point BEV obstacle map over RGB and depth. If RGB/depth appear more permissive than the red BEV obstacle map, trust the BEV and stay conservative around red points.
- The robot is not a point. Treat it as a body with non-zero footprint. Runtime context will provide robot_radius_m. Keep the whole robot body plus safety buffer inside free space, not just the centerline.
- Runtime context may also provide an extra body_safety_buffer_m. Keep robot_radius_m plus that extra body buffer inside free space, not just the centerline.
- You may be driving without external SLAM odometry. In that case, treat the pose as IMU-guided local dead reckoning and keep plans locally consistent.
- Red points in the BEV are not pass-through objects. Never place a waypoint through red points just because space behind them looks free.
- Choose waypoints only through visible free space. Free space means the empty corridor between red points, not the area hidden behind them.
- Any waypoint whose straight path comes close to red points should be treated as invalid and must be rejected in favor of a wider detour or rotate-first action.
- A corridor is only usable if the robot body can actually fit through it with margin. Reject routes that are only valid for a point robot.
- If persistent obstacle memory is provided, treat those remembered red obstacles as still dangerous until a clearly safer corridor is observed.
- Do not assume a wall disappeared simply because the robot rotated and the wall left the current FOV.
- When feasible, keep about 1.0 m clearance from nearby obstacles while passing or detouring.
- Respect the provided safety caps. Do not exceed them.
- Treat the provided goal as the ultimate destination, not as the next local point that must be chased immediately.
- It is acceptable to temporarily move sideways, pause goal progress, or even move slightly away from the final goal if that keeps the robot in a safer corridor with better continuation.
- If the global goal is behind, do not enter a rigid rotate-only routine by default. Prefer short remembered detours and small scan turns that reveal a better continuation.
- When the global goal is strongly behind the robot, use short-term memory and gentle reorientation to recover a feasible corridor instead of forcing a hard heading-alignment mode.
- Return one immediate waypoint update now. New visual feedback will keep arriving while the robot follows the queued waypoint stream.
- If perception is stale, uncertain, or unsafe, choose a stop action.
- Use a full stop only as a last resort for imminent collision, unrecoverable blockage, persistent stale perception, or goal reached.
- Avoid stop-and-go behavior. If the scene is safe, prefer a smooth continuous command over stopping between steps.
- Prefer forward arcs and gentle steering over repeated stop-rotate-stop patterns when the goal is already in front.
- When safe, prefer sustained commands that keep the robot moving for multiple seconds instead of short micro-actions.
- First choose a short-horizon local waypoint in robot coordinates, then choose a smooth cmd_vel that tracks that waypoint.
- In waypoint mode, waypoint geometry is the source of truth. Put most of your planning effort into choosing the waypoint. Treat linear_mps/angular_radps as controller hints, not the main plan.
- Internally imagine a tiny 2-point route fragment: an immediate safe support point in free space, then a continuation point that keeps progress. Output only the first point.
- If direct goal progress narrows into a wall, do not chase the goal side. First place the waypoint into the safer open corridor center or escape side, then let the next update continue from there.
- If the runtime says direct_cmd_vel mode is active, treat linear_mps/angular_radps/duration_s as the real command to execute and waypoint_* as advisory context only.
- In direct_cmd_vel mode, prefer smooth continuous forward arcs over twitchy alternating turns. Keep consecutive commands consistent unless the red BEV obstacle layout clearly demands a change.
- In direct_cmd_vel mode, use waypoint_* only as a short lookahead sanity check. The real output should be a stable cmd_vel that keeps progress while staying away from walls.
- First choose nav_mode, agent_phase, observation_target, and plan_commit_steps. Then choose speed_band, turn_band, and duration_band, and finally make the numeric waypoint/cmd fields consistent with that short plan.
- Use the discrete bands to stay stable. Avoid inventing highly precise numeric commands that change abruptly without a clear corridor reason.
- When queued waypoints are provided, extend and refine that waypoint stream smoothly instead of resetting it every query.
- Prefer waypoint updates over abrupt spins, but do not be timid. When the route is open, move decisively and use a brisk sustained speed.
- Behave like a zero-shot local navigator: keep a coherent short route in memory, preserve a good corridor choice, and update it smoothly as new images arrive.
- Behave like an agentic driver: observe, choose the next intent, commit to a short plan, act, then review new evidence.
- Rotating or scanning is a valid action. Use scan_left or scan_right deliberately when a short turn is needed to reveal corridor continuation, wall edges, or hidden openings.
- Re-evaluate from the current RGB, depth, BEV, and current goal_local at every step.
- Use previous-step obstacle memory when provided. A close obstacle can leave the current FOV after the robot turns without actually becoming safe.
- Before choosing the next waypoint, compare multiple candidate paths such as direct, left-detour, and right-detour.
- Do not greedily choose the heading that points most directly toward the goal if a safer detour exists.
- The final goal is a long-horizon objective. Local behavior should optimize corridor safety and continuation first, and only then reduce goal distance.
- Prefer the candidate path with the best minimum clearance to red obstacles, even if it is longer than the most direct path.
- Think in terms of a short continuous route through free space, not a single greedy steering angle.
- Do not optimize only for immediate goal reduction. Prefer the waypoint that leaves a safer and more feasible continuation over the next 1 to 2 steps.
- Mentally compare short route fragments, not just single headings. A waypoint that slightly delays goal progress is better if it avoids a near-future dead end or wall trap.
- Choose waypoints that preserve future maneuvering room and keep the robot away from wall edges.
- Do not repeat a previous action out of inertia. Only turn or move if the current observation still justifies it.
- If the goal bearing changes after rotation, trust the updated current goal_local values instead of prior actions.
- Avoid unnecessary micro-actions, but do not keep rotating or moving just because the previous step did so.
- Do not immediately undo a recent obstacle detour just because the current frame looks clearer after that detour.
- If a wall blocks direct progress, keep a short-term around-wall plan in memory for multiple steps.
- Use recent BEV and recent RGB history as short-term exploration memory. A slight scan turn is allowed if it helps reveal the corridor continuation, but keep the resulting route graceful and coherent.
- Treat previous RGB images as short-term visual memory of corridor shape and openings so you can continue a coherent exploration plan across turns.
- Prefer a visually clean, corridor-centered detour over a twitchy sequence of locally greedy turns.
- Determine left vs right from goal_local_right, not from generic math angle conventions.
- If goal_local_right is positive, the goal is on robot-right and a right turn uses w < 0.
- If goal_local_right is negative, the goal is on robot-left and a left turn uses w > 0.
- If goal_local_forward is positive and the goal is already roughly ahead, prefer forward progress with only mild steering instead of in-place spinning.
- Do not keep rotating once the goal is already ahead unless a current obstacle clearly requires it.
- If front clearance is good and the robot is already making safe forward progress, prefer maintaining that forward motion.
- Use cautious rotation. Start with small angular corrections and increase turn rate only when the current images clearly justify it.
- When straight motion is safe, keep the waypoint near straight ahead and avoid unnecessary heading changes.
- When front clearance and side clearance are both comfortable, prefer the upper half of the allowed linear speed range instead of slow crawling.
- In a wide clear corridor, choose longer waypoint horizons and faster sustained commands. Do not waste time with unnecessarily small corrections.
- Slow down only when red BEV obstacles, narrow side clearance, or a strong turn clearly require it.
- If the direct path is partially blocked but one side is open, prefer a curved detour command that goes around the obstacle instead of stopping.
- If the robot can safely pass an obstacle while maintaining about 1.0 m clearance, prefer passing with a smooth arc.
- If the route ahead is blocked by an impassable wall and no safe direct waypoint exists, do not freeze. Explore by scanning or moving toward the more open side corridor to find a valid continuation.
- If the route ahead is blocked by a wall and the robot is boxed in near that wall, do not keep pressing forward or oscillating in place. Briefly reverse to recover space, then turn toward the safer side.
- Act like a short-horizon path planner, not a greedy target chaser. A longer but safer route is preferred over a shorter route that narrows toward obstacles.
- Avoid locally attractive but globally poor moves, such as hugging the goal side when it obviously narrows into walls.
- Prefer a waypoint sequence that keeps options open for the next turn, not a greedy shortcut that forces a stop or sharp reversal one step later.
- Avoid wall-hugging waypoints. Choose the waypoint through the safer middle of the visible free corridor when possible.
- Always prefer the center of open free space over the edge of free space.
- If a wall is close on one side, move the waypoint away from that wall even if the goal is geometrically closer to that side.
- Reject any waypoint whose path tube would pass too close to a wall for the full robot body. Near-wall paths are invalid even if the centerline barely fits.
- Prefer a point that slightly delays progress but lands in a wider pocket of free space over a more direct point that hugs a wall.
- If a wall becomes too close on one side, do not just slow down and skim it. Make a decisive escape arc away from that wall while keeping forward progress if the front is still safe.
- Prefer a slightly longer path with better wall clearance over a shortest path that skims along a wall.
- When the corridor ahead is clear, prefer a larger waypoint horizon around 1 to 2 meters so the robot can move briskly instead of dithering.
- If the corridor ahead is clearly open, prefer duration near the upper part of the allowed range rather than short hesitant commands.
- When the corridor ahead is clearly open, prefer a brisk but still smooth forward speed near the upper safety cap instead of timid crawling.

Output rules
- Fill the provided structured schema only.
- reasoning_summary must be brief and concrete.
- nav_mode is one of: progress, detour_left, detour_right, scan_left, scan_right, reverse_escape, explore.
- agent_phase is one of: advance, detour, scan, recover.
- observation_target is one of: front_corridor, left_opening, right_opening, wall_edge, goal_sector.
- plan_commit_steps is a short-horizon commitment from 1 to 6 steps.
- speed_band is one of: stop, crawl, cautious, steady, brisk.
- turn_band is one of: straight, slight_left, left, sharp_left, slight_right, right, sharp_right.
- duration_band is one of: short, medium, long.
- waypoint_right_m is the local waypoint on robot-right in meters.
- waypoint_forward_m is the local waypoint on robot-forward in meters.
- waypoint_speed_mps is the preferred calm forward speed while tracking the waypoint.
- linear_mps and angular_radps should be consistent with the waypoint, but in waypoint mode the controller will track the waypoint as the source of truth.
- action_text must end with: ACTION: [v, w, t]
- v is forward linear velocity in m/s.
- w is angular velocity in rad/s, positive is counter-clockwise/left.
- t is duration in seconds.
"""


@dataclass
class Pose2D:
    stamp: float
    x: float
    y: float
    yaw: float


@dataclass
class PerceptionSnapshot:
    capture_time: float
    step_index: int
    rgb_bgr: np.ndarray
    depth_vis: np.ndarray
    bev_img: np.ndarray
    pose: Pose2D
    goal_local_right: float
    goal_local_forward: float
    goal_distance: float
    goal_bearing_deg: float
    global_goal_right: float
    global_goal_forward: float
    global_goal_distance: float
    global_goal_bearing_deg: float
    goal_state: Dict[str, object]
    obstacle_metrics: Dict[str, object]
    map_memory_summary: Dict[str, object]
    planner_hint: Dict[str, object]
    route_plan: Dict[str, object]
    pose_diagnostics: Dict[str, object]
    history_summary: List[Dict[str, object]]
    stale_info: Dict[str, object]
    previous_step: Optional[Dict[str, object]]
    previous_steps: List[Dict[str, object]]


@dataclass
class ExecutionState:
    step_index: int
    requested: Dict[str, float]
    applied: Dict[str, float]
    waypoint: Dict[str, float]
    world_waypoint: Dict[str, float]
    reasoning_summary: str
    risk_level: str
    action_text: str
    raw_output_text: str
    raw_response: Dict[str, object]
    prompt_debug: Dict[str, object]
    snapshot: PerceptionSnapshot
    safety_override: str
    start_pose: Pose2D
    start_monotonic: float
    end_monotonic: float
    hold_until_monotonic: float
    status: str = "executing"


@dataclass
class BootstrapState:
    applied: Dict[str, float]
    reason: str
    start_monotonic: float
    end_monotonic: float
    cycle_index: int


@dataclass
class StopRampState:
    start_linear_mps: float
    start_angular_radps: float
    start_monotonic: float
    end_monotonic: float
    reason: str


class DriveCommand(BaseModel):
    reasoning_summary: str = Field(..., max_length=400)
    risk_level: Literal["low", "medium", "high"]
    target_bearing_deg: float
    target_distance_m: float
    nav_mode: Literal["progress", "detour_left", "detour_right", "scan_left", "scan_right", "reverse_escape", "explore"]
    agent_phase: Literal["advance", "detour", "scan", "recover"]
    observation_target: Literal["front_corridor", "left_opening", "right_opening", "wall_edge", "goal_sector"]
    plan_commit_steps: int = Field(..., ge=1, le=6)
    speed_band: Literal["stop", "crawl", "cautious", "steady", "brisk"]
    turn_band: Literal["straight", "slight_left", "left", "sharp_left", "slight_right", "right", "sharp_right"]
    duration_band: Literal["short", "medium", "long"]
    waypoint_right_m: float
    waypoint_forward_m: float
    waypoint_speed_mps: float
    linear_mps: float
    angular_radps: float
    duration_s: float
    action_text: str


def normalize_angle(angle_rad: float) -> float:
    while angle_rad > math.pi:
        angle_rad -= 2.0 * math.pi
    while angle_rad < -math.pi:
        angle_rad += 2.0 * math.pi
    return angle_rad


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def world_to_robot(delta_x: float, delta_y: float, yaw: float) -> Tuple[float, float]:
    robot_right = delta_x * math.sin(yaw) - delta_y * math.cos(yaw)
    robot_forward = delta_x * math.cos(yaw) + delta_y * math.sin(yaw)
    return robot_right, robot_forward


def robot_to_world(robot_right: float, robot_forward: float, yaw: float) -> Tuple[float, float]:
    delta_x = (robot_forward * math.cos(yaw)) + (robot_right * math.sin(yaw))
    delta_y = (robot_forward * math.sin(yaw)) - (robot_right * math.cos(yaw))
    return delta_x, delta_y


def pose_delta_local(start_pose: Pose2D, end_pose: Pose2D) -> Tuple[float, float, float]:
    dx = end_pose.x - start_pose.x
    dy = end_pose.y - start_pose.y
    right, forward = world_to_robot(dx, dy, start_pose.yaw)
    dyaw = normalize_angle(end_pose.yaw - start_pose.yaw)
    return right, forward, dyaw


def integrate_unicycle_pose(
    pose: Pose2D,
    linear_mps: float,
    angular_radps: float,
    dt: float,
    stamp: float,
) -> Pose2D:
    if dt <= 0.0:
        return Pose2D(stamp, pose.x, pose.y, pose.yaw)

    yaw = pose.yaw
    if abs(angular_radps) < 1e-6:
        dx = linear_mps * math.cos(yaw) * dt
        dy = linear_mps * math.sin(yaw) * dt
        next_yaw = yaw
    else:
        next_yaw = normalize_angle(yaw + (angular_radps * dt))
        radius = linear_mps / angular_radps
        dx = radius * (math.sin(next_yaw) - math.sin(yaw))
        dy = radius * (-math.cos(next_yaw) + math.cos(yaw))

    return Pose2D(
        stamp=stamp,
        x=pose.x + dx,
        y=pose.y + dy,
        yaw=next_yaw,
    )


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def human_bytes(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def optional_finite_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def finite_or(value: Optional[float], fallback: float) -> float:
    if value is None or not math.isfinite(value):
        return fallback
    return float(value)


def goal_region_label(goal_right: float, goal_forward: float, side_tol: float = 0.35, forward_tol: float = 0.35) -> str:
    if goal_forward > forward_tol:
        depth_label = "ahead"
    elif goal_forward < -forward_tol:
        depth_label = "behind"
    else:
        depth_label = "level"

    if goal_right > side_tol:
        side_label = "right"
    elif goal_right < -side_tol:
        side_label = "left"
    else:
        side_label = "center"

    if depth_label == "level":
        return f"side-{side_label}"
    return f"{depth_label}-{side_label}"


def desired_angular_sign(goal_right: float, side_tol: float = 0.35) -> float:
    if goal_right > side_tol:
        return -1.0
    if goal_right < -side_tol:
        return 1.0
    return 0.0


def steering_hint_text(goal_right: float, goal_forward: float) -> str:
    turn_sign = desired_angular_sign(goal_right)
    if turn_sign < 0.0:
        if goal_forward > 0.35:
            return "goal is ahead-right, so any steering should favor a right turn (w < 0)"
        return "goal is on robot-right, so rotation should favor a right turn (w < 0)"
    if turn_sign > 0.0:
        if goal_forward > 0.35:
            return "goal is ahead-left, so any steering should favor a left turn (w > 0)"
        return "goal is on robot-left, so rotation should favor a left turn (w > 0)"
    if goal_forward > 0.35:
        return "goal is nearly centered ahead, so prefer forward progress with small steering"
    return "goal is nearly centered laterally, so avoid unnecessary turning"


def obstacle_memory_summary(metrics: Dict[str, object]) -> Dict[str, object]:
    sectors = metrics.get("sectors", {})
    corridor = metrics.get("corridor", {})
    return {
        "nearest_distance_m": optional_finite_float(metrics.get("nearest_distance_m")),
        "nearest_heading_deg": optional_finite_float(metrics.get("nearest_heading_deg")),
        "front_clearance_m": optional_finite_float(metrics.get("front_clearance_m")),
        "point_count": int(metrics.get("point_count", 0) or 0),
        "sectors": {
            name: {
                "label": str(sectors.get(name, {}).get("label", "unknown")),
                "min_distance_m": optional_finite_float(sectors.get(name, {}).get("min_distance_m")),
            }
            for name in ("left", "center", "right")
        },
        "corridor": {
            "status": str(corridor.get("status", "unknown")),
            "center_right_m": optional_finite_float(corridor.get("center_right_m")),
            "width_m": optional_finite_float(corridor.get("width_m")),
            "left_clearance_m": optional_finite_float(corridor.get("left_clearance_m")),
            "right_clearance_m": optional_finite_float(corridor.get("right_clearance_m")),
        },
    }


class OpenAIDriveNode(BirdEyeNode):
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.goal_input_x = float(args.goal_x)
        self.goal_input_y = float(args.goal_y)
        self.goal_x = self.goal_input_x if args.goal_frame == "world" else None
        self.goal_y = self.goal_input_y if args.goal_frame == "world" else None
        self.goal_anchor_pose: Optional[Pose2D] = None
        self.database_path = Path(args.database_path).expanduser().resolve()
        self.save_root = ensure_dir(Path(args.save_root).expanduser().resolve())
        self.session_dir = ensure_dir(self.save_root / datetime.now().strftime("%Y%m%d_%H%M%S"))
        self.session_log_path = self.session_dir / "session.jsonl"
        self.last_rgb_received_at = 0.0
        self.last_depth_received_at = 0.0
        self.last_camera_info_received_at = 0.0
        self.last_odom_received_at = 0.0
        self.last_imu_received_at = 0.0
        self.current_pose: Optional[Pose2D] = None
        self.odom_position_pose: Optional[Pose2D] = None
        self.odom_reported_yaw: Optional[float] = None
        self.imu_raw_yaw: Optional[float] = None
        self.imu_aligned_yaw: Optional[float] = None
        self.imu_integrated_raw_yaw: Optional[float] = None
        self.imu_integrated_aligned_yaw: Optional[float] = None
        self.imu_last_monotonic: Optional[float] = None
        self.last_imu_angular_z: Optional[float] = None
        self.yaw_alignment_offset: Optional[float] = None
        self.cmd_yaw_estimate: Optional[float] = None
        self.last_effective_yaw_source = "none"
        self.dead_reckoned_distance_m = 0.0
        self.dead_reckoned_turn_rad = 0.0
        self.local_goal_world_x: Optional[float] = None
        self.local_goal_world_y: Optional[float] = None
        self.local_goal_source = "pending"
        self.local_goal_reason = "not-initialized"
        self.local_goal_mode = "pending"
        self.local_goal_created_step = 0
        self.local_goal_updated_step = 0
        self.heading_alignment_active = False
        self.api_status = "waiting"
        self.last_error = ""
        self.latest_reasoning = ""
        self.latest_risk = "unknown"
        self.latest_action_text = "ACTION: [0.0, 0.0, 0.0]"
        self.last_obstacle_metrics: Dict[str, object] = {}
        self.latest_obstacle_cloud: Optional[Dict[str, np.ndarray]] = None
        self.world_obstacle_memory = np.empty((0, 3), dtype=np.float32)
        self.command_history: deque[Dict[str, object]] = deque(maxlen=HISTORY_WINDOW)
        self.pending_future: Optional[Future] = None
        self.pending_snapshot: Optional[PerceptionSnapshot] = None
        self.execution_queue: deque[ExecutionState] = deque(maxlen=args.max_waypoint_queue)
        self.stop_ramp: Optional[StopRampState] = None
        self.last_published_linear_mps = 0.0
        self.last_published_angular_radps = 0.0
        self.executor_pool = ThreadPoolExecutor(max_workers=1)
        self.openai_client = OpenAI()
        self.auto_enabled = True
        self.running = True
        self.step_counter = 0
        self.manual_snapshot_counter = 0
        self.next_query_time = 0.0
        self.active_execution: Optional[ExecutionState] = None
        self.bootstrap_active: Optional[BootstrapState] = None
        self.bootstrap_cycle_index = 0
        self.ignore_next_result = False
        self.goal_completed = False
        self.db_exists = self.database_path.exists()
        self.db_size = self.database_path.stat().st_size if self.db_exists else 0
        self.previous_step_context: Optional[Dict[str, object]] = None
        self.previous_step_contexts: deque[Dict[str, object]] = deque(maxlen=PREVIOUS_CONTEXT_WINDOW)
        self.motion_last_update_monotonic: Optional[float] = None
        self.detour_commit_sign = 0.0
        self.detour_commit_until_monotonic = 0.0
        self.route_plan_mode = "none"
        self.route_plan_sign = 0.0
        self.route_plan_reason = "not-initialized"
        self.route_plan_created_step = 0
        self.route_plan_updated_step = 0
        self.route_plan_hold_until_step = 0

        super().__init__(
            rgb_topic=args.rgb_topic,
            depth_topic=args.depth_topic,
            camera_info_topic=args.camera_info_topic,
            depth_scale=args.depth_scale,
            depth_min=args.depth_min,
            depth_max=args.depth_max,
            max_forward=args.max_forward,
            max_side=args.max_side,
            stride=args.stride,
            camera_height=args.camera_height,
            floor_tolerance=args.floor_tolerance,
            auto_floor_bottom_ratio=args.auto_floor_bottom_ratio,
            auto_floor_percentile=args.auto_floor_percentile,
            grid_step=args.grid_step,
            ppm=args.ppm,
            left_panel_width=args.left_panel_width,
            bev_render_mode=args.bev_render_mode,
            cloud_point_size=args.cloud_point_size,
            ego_radius_m=args.ego_radius,
        )

        self.cmd_pub = self.create_publisher(Twist, args.cmd_vel_topic, 10)
        self.create_subscription(Odometry, args.odom_topic, self.on_odom, qos_profile_sensor_data)
        if args.pose_source != "odom":
            self.current_pose = Pose2D(stamp=time.time(), x=0.0, y=0.0, yaw=0.0)
            self.motion_last_update_monotonic = time.monotonic()
            self.cmd_yaw_estimate = 0.0
            self.api_status = "idle"
        if args.yaw_source in ("imu", "hybrid"):
            self.create_subscription(Imu, args.imu_topic, self.on_imu, qos_profile_sensor_data)
        self.cmd_timer = self.create_timer(1.0 / CMD_PUBLISH_HZ, self.on_cmd_timer)
        if args.goal_frame == "world":
            self.get_logger().info(f"goal(world): ({self.goal_input_x:.3f}, {self.goal_input_y:.3f})")
        else:
            self.get_logger().info(
                f"goal(start_local): right={self.goal_input_x:.3f}, forward={self.goal_input_y:.3f}"
            )
        self.get_logger().info(f"goal frame: {args.goal_frame}")
        self.get_logger().info(f"pose source: {args.pose_source}")
        self.get_logger().info(f"yaw source: {args.yaw_source}")
        self.get_logger().info(f"odom topic: {args.odom_topic}")
        self.get_logger().info(f"odom yaw sign: {args.odom_yaw_sign:+d}")
        self.get_logger().info(f"cmd linear sign: {args.cmd_linear_sign:+d}")
        self.get_logger().info(f"imu topic: {args.imu_topic}")
        self.get_logger().info(f"cmd_vel topic: {args.cmd_vel_topic}")
        self.get_logger().info(f"database path: {self.database_path}")
        self.get_logger().info(f"session dir: {self.session_dir}")

    def on_camera_info(self, msg):
        self.last_camera_info_received_at = time.time()
        super().on_camera_info(msg)

    def on_rgb(self, msg):
        self.last_rgb_received_at = time.time()
        super().on_rgb(msg)

    def on_depth(self, msg):
        self.last_depth_received_at = time.time()
        super().on_depth(msg)

    def on_odom(self, msg: Odometry):
        self.last_odom_received_at = time.time()
        pose = msg.pose.pose
        q = pose.orientation
        raw_yaw = float(self.args.odom_yaw_sign) * quaternion_to_yaw(float(q.x), float(q.y), float(q.z), float(q.w))
        self.odom_position_pose = Pose2D(
            stamp=time.time(),
            x=float(pose.position.x),
            y=float(pose.position.y),
            yaw=raw_yaw,
        )
        self.odom_reported_yaw = raw_yaw
        self.maybe_update_yaw_alignment()
        if self.args.pose_source == "odom" or self.args.yaw_source in ("odom", "hybrid"):
            self.compose_current_pose()
        if self.args.pose_source == "odom" and self.bootstrap_active is not None:
            self.stop_robot()
            self.bootstrap_active = None
            self.api_status = "localized"
            self.last_error = "rtabmap odom acquired; switching to OpenAI planning"
            self.next_query_time = time.monotonic()

    def on_imu(self, msg: Imu):
        self.last_imu_received_at = time.time()
        imu_now = time.monotonic()
        dt = None
        if self.imu_last_monotonic is not None:
            dt = imu_now - self.imu_last_monotonic
        self.imu_last_monotonic = imu_now
        angular_z = optional_finite_float(msg.angular_velocity.z)
        if angular_z is not None:
            self.last_imu_angular_z = angular_z

        q = msg.orientation
        orientation_norm = float(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w)
        if orientation_norm > 1e-6:
            self.imu_raw_yaw = quaternion_to_yaw(float(q.x), float(q.y), float(q.z), float(q.w))
            if self.imu_integrated_raw_yaw is None:
                self.imu_integrated_raw_yaw = self.imu_raw_yaw
        elif self.imu_integrated_raw_yaw is None and self.cmd_yaw_estimate is not None:
            self.imu_integrated_raw_yaw = float(self.cmd_yaw_estimate)

        if (
            dt is not None
            and 0.0 < dt <= 0.5
            and angular_z is not None
            and self.imu_integrated_raw_yaw is not None
        ):
            self.imu_integrated_raw_yaw = normalize_angle(self.imu_integrated_raw_yaw + (angular_z * dt))

        self.maybe_update_yaw_alignment()
        self.compose_current_pose()

    def maybe_update_yaw_alignment(self):
        if self.imu_raw_yaw is not None:
            if self.yaw_alignment_offset is not None:
                self.imu_aligned_yaw = normalize_angle(self.imu_raw_yaw + self.yaw_alignment_offset)
            else:
                self.imu_aligned_yaw = self.imu_raw_yaw
        if self.imu_integrated_raw_yaw is not None:
            if self.yaw_alignment_offset is not None:
                self.imu_integrated_aligned_yaw = normalize_angle(
                    self.imu_integrated_raw_yaw + self.yaw_alignment_offset
                )
            else:
                self.imu_integrated_aligned_yaw = self.imu_integrated_raw_yaw
        if self.imu_raw_yaw is None or self.odom_reported_yaw is None:
            return
        self.yaw_alignment_offset = normalize_angle(self.odom_reported_yaw - self.imu_raw_yaw)
        self.imu_aligned_yaw = normalize_angle(self.imu_raw_yaw + self.yaw_alignment_offset)
        if self.imu_integrated_raw_yaw is not None:
            self.imu_integrated_aligned_yaw = normalize_angle(
                self.imu_integrated_raw_yaw + self.yaw_alignment_offset
            )

    def select_effective_yaw(self, *, with_source: bool = False) -> Union[Optional[float], Tuple[Optional[float], str]]:
        imu_yaw = self.imu_aligned_yaw if self.imu_aligned_yaw is not None else self.imu_raw_yaw
        imu_integrated_yaw = (
            self.imu_integrated_aligned_yaw if self.imu_integrated_aligned_yaw is not None else self.imu_integrated_raw_yaw
        )
        result: Optional[float] = None
        source = "none"
        if self.args.yaw_source == "imu":
            if imu_yaw is not None:
                result = imu_yaw
                source = "imu_orientation"
            elif imu_integrated_yaw is not None:
                result = imu_integrated_yaw
                source = "imu_integrated"
        elif self.args.yaw_source == "odom":
            result = self.odom_reported_yaw
            source = "odom"
        elif self.args.yaw_source == "cmd_vel":
            result = self.cmd_yaw_estimate
            source = "cmd_vel"
        elif imu_yaw is not None:
            imu_age = time.time() - self.last_imu_received_at if self.last_imu_received_at > 0.0 else None
            if imu_age is not None and imu_age <= (self.args.stale_timeout + self.args.execution_stale_grace_s):
                result = imu_yaw
                source = "imu_orientation"
            elif imu_integrated_yaw is not None:
                result = imu_integrated_yaw
                source = "imu_integrated"
        elif imu_integrated_yaw is not None:
            imu_age = time.time() - self.last_imu_received_at if self.last_imu_received_at > 0.0 else None
            if imu_age is not None and imu_age <= (self.args.stale_timeout + self.args.execution_stale_grace_s):
                result = imu_integrated_yaw
                source = "imu_integrated"

        if result is None and self.cmd_yaw_estimate is not None:
            result = self.cmd_yaw_estimate
            source = "cmd_vel"
        if result is None and self.odom_reported_yaw is not None:
            result = self.odom_reported_yaw
            source = "odom"

        self.last_effective_yaw_source = source
        if with_source:
            return result, source
        return result

    def uses_dead_reckoned_pose(self) -> bool:
        return self.args.pose_source in ("cmd_vel", "imu_cmd_vel")

    def pose_source_text(self) -> str:
        if self.args.pose_source == "imu_cmd_vel":
            return "Pose is dead-reckoned from executed cmd_vel x/y with IMU-guided heading."
        if self.args.pose_source == "cmd_vel":
            return "Pose is dead-reckoned from executed cmd_vel commands."
        return "Pose comes from external odometry."

    def start_local_goal_anchor_ready(self, pose: Optional[Pose2D]) -> bool:
        if self.args.goal_frame == "world":
            return True
        if self.goal_x is not None and self.goal_y is not None:
            return True
        if pose is None:
            return False
        if self.args.pose_source == "imu_cmd_vel" and self.args.yaw_source in ("imu", "hybrid"):
            return self.last_imu_received_at > 0.0 and self.select_effective_yaw() is not None
        return True

    def compose_current_pose(self):
        if self.args.pose_source == "cmd_vel":
            return
        if self.args.pose_source == "imu_cmd_vel":
            yaw = self.select_effective_yaw()
            if self.current_pose is None:
                if yaw is None:
                    return
                self.current_pose = Pose2D(stamp=time.time(), x=0.0, y=0.0, yaw=yaw)
                return
            if yaw is None:
                return
            self.current_pose = Pose2D(
                stamp=time.time(),
                x=self.current_pose.x,
                y=self.current_pose.y,
                yaw=yaw,
            )
            return
        if self.odom_position_pose is None:
            self.current_pose = None
            return
        yaw = self.select_effective_yaw()
        if yaw is None:
            yaw = self.odom_position_pose.yaw
        self.current_pose = Pose2D(
            stamp=time.time(),
            x=self.odom_position_pose.x,
            y=self.odom_position_pose.y,
            yaw=yaw,
        )

    def update_dead_reckoning_pose(self, now_monotonic: Optional[float] = None):
        if now_monotonic is None:
            now_monotonic = time.monotonic()

        if self.current_pose is None:
            if self.uses_dead_reckoned_pose():
                initial_yaw = self.select_effective_yaw()
                if initial_yaw is None:
                    initial_yaw = 0.0
                self.current_pose = Pose2D(stamp=time.time(), x=0.0, y=0.0, yaw=initial_yaw)
            else:
                if self.motion_last_update_monotonic is None:
                    self.motion_last_update_monotonic = now_monotonic
                return
        if self.cmd_yaw_estimate is None:
            self.cmd_yaw_estimate = self.current_pose.yaw

        if self.motion_last_update_monotonic is None:
            self.motion_last_update_monotonic = now_monotonic
            return

        dt = max(0.0, now_monotonic - self.motion_last_update_monotonic)
        self.motion_last_update_monotonic = now_monotonic
        if dt <= 0.0:
            return

        linear_mps = float(self.args.cmd_linear_sign) * float(self.last_published_linear_mps)
        angular_radps = float(self.last_published_angular_radps)
        if abs(linear_mps) < 1e-6 and abs(angular_radps) < 1e-6:
            return

        self.dead_reckoned_distance_m += abs(linear_mps * dt)
        self.dead_reckoned_turn_rad += abs(angular_radps * dt)
        self.cmd_yaw_estimate = normalize_angle(float(self.cmd_yaw_estimate) + (angular_radps * dt))

        if self.args.pose_source == "cmd_vel":
            self.current_pose = integrate_unicycle_pose(
                self.current_pose,
                linear_mps=linear_mps,
                angular_radps=angular_radps,
                dt=dt,
                stamp=time.time(),
            )
        elif self.args.pose_source == "imu_cmd_vel":
            current_yaw = self.current_pose.yaw
            next_yaw = self.select_effective_yaw()
            if next_yaw is None:
                next_yaw = self.cmd_yaw_estimate
            if next_yaw is None:
                next_yaw = current_yaw
            yaw_delta = normalize_angle(next_yaw - current_yaw)
            avg_yaw = normalize_angle(current_yaw + (0.5 * yaw_delta))
            self.current_pose = Pose2D(
                stamp=time.time(),
                x=self.current_pose.x + (linear_mps * math.cos(avg_yaw) * dt),
                y=self.current_pose.y + (linear_mps * math.sin(avg_yaw) * dt),
                yaw=next_yaw,
            )
        elif self.args.pose_source == "odom":
            self.compose_current_pose()

    def publish_command(self, linear_mps: float, angular_radps: float):
        if not rclpy.ok():
            return
        twist = Twist()
        twist.linear.x = float(linear_mps)
        twist.angular.z = float(angular_radps)
        try:
            self.cmd_pub.publish(twist)
        except Exception:
            return
        self.last_published_linear_mps = float(linear_mps)
        self.last_published_angular_radps = float(angular_radps)

    def start_stop_ramp(self, reason: str) -> bool:
        if self.stop_ramp is not None:
            return True
        if self.args.stop_ramp_s <= 0.05:
            return False
        if abs(self.last_published_linear_mps) < 1e-3 and abs(self.last_published_angular_radps) < 1e-3:
            return False

        now = time.monotonic()
        self.stop_ramp = StopRampState(
            start_linear_mps=float(self.last_published_linear_mps),
            start_angular_radps=float(self.last_published_angular_radps),
            start_monotonic=now,
            end_monotonic=now + float(self.args.stop_ramp_s),
            reason=reason,
        )
        return True

    def stop_ramp_command(self, now_monotonic: float) -> Tuple[float, float, bool]:
        if self.stop_ramp is None:
            return 0.0, 0.0, True

        duration = max(1e-6, self.stop_ramp.end_monotonic - self.stop_ramp.start_monotonic)
        progress = min(1.0, max(0.0, (now_monotonic - self.stop_ramp.start_monotonic) / duration))
        scale = max(0.0, 1.0 - progress)
        linear_mps = self.stop_ramp.start_linear_mps * scale
        angular_radps = self.stop_ramp.start_angular_radps * scale
        done = now_monotonic >= self.stop_ramp.end_monotonic
        if done:
            linear_mps = 0.0
            angular_radps = 0.0
        return linear_mps, angular_radps, done

    def on_cmd_timer(self):
        now = time.monotonic()
        self.update_dead_reckoning_pose(now)

        if self.maybe_mark_goal_complete(self.current_pose, reason="goal-complete-threshold"):
            return

        if self.bootstrap_active is not None and self.active_execution is None:
            ready, _ = self.perception_ready_without_odom()
            if not ready:
                self.stop_robot(immediate=True)
                self.bootstrap_active = None
                self.api_status = "waiting"
                self.last_error = "bootstrap paused: rgb/depth/camera info not ready"
                return

            if now >= self.bootstrap_active.end_monotonic:
                self.stop_robot(immediate=True)
                self.bootstrap_active = None
                self.motion_last_update_monotonic = now
                self.next_query_time = now
                return

            self.publish_command(
                float(self.bootstrap_active.applied["linear_mps"]),
                float(self.bootstrap_active.applied["angular_radps"]),
            )
            return

        if self.active_execution is None:
            if self.auto_enabled and self.execution_queue:
                next_execution = self.execution_queue.popleft()
                current_pose = self.current_pose or next_execution.snapshot.pose
                next_execution.start_pose = Pose2D(
                    current_pose.stamp,
                    current_pose.x,
                    current_pose.y,
                    current_pose.yaw,
                )
                next_execution.start_monotonic = now
                next_execution.end_monotonic = now + float(next_execution.applied["duration_s"])
                next_execution.hold_until_monotonic = next_execution.end_monotonic + float(self.args.command_hold_s)
                self.activate_execution_state(next_execution)
                if self.active_execution is None:
                    return
            else:
                return

        fresh, stale_info = self.data_is_fresh()
        if not fresh:
            ages = [age for age in (stale_info.get("rgb_age_s"), stale_info.get("depth_age_s")) if age is not None]
            if self.args.pose_source == "odom" and stale_info.get("odom_age_s") is not None:
                ages.append(stale_info.get("odom_age_s"))
            max_age = max(ages) if ages else None
            if (
                max_age is not None
                and max_age <= (self.args.stale_timeout + self.args.execution_stale_grace_s)
                and self.can_hold_current_command(self.active_execution)
            ):
                self.api_status = "stale-grace"
                self.last_error = "sensor refresh delayed; holding command briefly"
                self.publish_command(
                    float(self.active_execution.applied["linear_mps"]),
                    float(self.active_execution.applied["angular_radps"]),
                )
                return

            self.stop_robot(immediate=True)
            self.active_execution.status = "aborted"
            self.active_execution.safety_override = (
                self.active_execution.safety_override + "; stale-data-stop"
            ).strip("; ")
            self.finalize_execution("aborted")
            self.api_status = "error"
            self.last_error = "stale data during execution"
            return

        current_pose = self.current_pose or self.active_execution.start_pose
        reached_current_waypoint = (
            self.execution_waypoint_reached(self.active_execution, current_pose)
            if self.args.control_mode == "waypoint"
            else False
        )
        execution_finished = now >= self.active_execution.end_monotonic

        if self.auto_enabled and self.execution_queue and (
            reached_current_waypoint or execution_finished
        ):
            next_execution = self.execution_queue.popleft()
            self.stop_ramp = None
            self.motion_last_update_monotonic = now
            self.finalize_execution("completed" if (reached_current_waypoint or execution_finished) else "superseded")
            current_pose = self.current_pose or next_execution.snapshot.pose
            next_execution.start_pose = Pose2D(
                current_pose.stamp,
                current_pose.x,
                current_pose.y,
                current_pose.yaw,
            )
            next_execution.start_monotonic = now
            next_execution.end_monotonic = now + float(next_execution.applied["duration_s"])
            next_execution.hold_until_monotonic = next_execution.end_monotonic + float(self.args.command_hold_s)
            self.activate_execution_state(next_execution)
            if self.active_execution is None:
                return
            current_pose = self.current_pose or self.active_execution.start_pose
            reached_current_waypoint = (
                self.execution_waypoint_reached(self.active_execution, current_pose)
                if self.args.control_mode == "waypoint"
                else False
            )
            execution_finished = now >= self.active_execution.end_monotonic

        if (
            self.args.control_mode == "waypoint"
            and
            reached_current_waypoint
            and now < self.active_execution.hold_until_monotonic
            and self.can_hold_current_command(self.active_execution)
        ):
            if "hold-last-safe-command" not in self.active_execution.safety_override:
                suffix = "hold-last-safe-command"
                if self.active_execution.safety_override == "none":
                    self.active_execution.safety_override = suffix
                else:
                    self.active_execution.safety_override = self.active_execution.safety_override + f"; {suffix}"
            self.api_status = "holding-next-waypoint"
            self.last_error = "holding current motion while waiting for next queued waypoint"
            self.publish_command(
                float(self.active_execution.applied["linear_mps"]),
                float(self.active_execution.applied["angular_radps"]),
            )
            return

        if (
            self.args.control_mode == "waypoint"
            and reached_current_waypoint
            and now >= self.active_execution.hold_until_monotonic
            and not self.execution_queue
        ) or (
            self.args.control_mode == "direct_cmd_vel"
            and execution_finished
            and not self.execution_queue
        ):
            if self.stop_ramp is None:
                if self.start_stop_ramp("normal-stop") and "smooth-stop-ramp" not in self.active_execution.safety_override:
                    if self.active_execution.safety_override == "none":
                        self.active_execution.safety_override = "smooth-stop-ramp"
                    else:
                        self.active_execution.safety_override = self.active_execution.safety_override + "; smooth-stop-ramp"
            if self.stop_ramp is not None:
                linear_mps, angular_radps, done = self.stop_ramp_command(now)
                self.publish_command(linear_mps, angular_radps)
                self.api_status = "stopping"
                self.last_error = ""
                if done:
                    self.stop_ramp = None
                    self.motion_last_update_monotonic = now
                    self.finalize_execution("completed")
                return
            self.stop_robot(immediate=True)
            self.motion_last_update_monotonic = now
            self.finalize_execution("completed")
            return

        if self.args.control_mode == "direct_cmd_vel":
            self.api_status = "tracking-direct-cmd"
            self.last_error = ""
            self.publish_command(
                float(self.active_execution.applied["linear_mps"]),
                float(self.active_execution.applied["angular_radps"]),
            )
            return

        local_waypoint = self.execution_waypoint_local(self.active_execution, current_pose)
        tracked_command, _ = self.controller_command_for_waypoint(
            local_waypoint,
            self.last_obstacle_metrics,
            requested_duration=float(self.active_execution.requested.get("duration_s", self.args.min_motion_duration)),
            current_applied=self.active_execution.applied,
        )
        self.active_execution.applied = tracked_command
        self.api_status = "tracking-path"
        self.last_error = ""
        self.publish_command(
            float(tracked_command["linear_mps"]),
            float(tracked_command["angular_radps"]),
        )

    def stop_robot(self, immediate: bool = True):
        if not rclpy.ok():
            return
        if not immediate and self.start_stop_ramp("requested-stop"):
            return
        self.stop_ramp = None
        self.publish_command(0.0, 0.0)

    def request_emergency_stop(self, reason: str):
        self.update_dead_reckoning_pose(time.monotonic())
        self.stop_robot(immediate=True)
        if self.pending_future is not None:
            self.ignore_next_result = True
        self.execution_queue.clear()
        self.detour_commit_sign = 0.0
        self.detour_commit_until_monotonic = 0.0
        self.stop_ramp = None
        if self.bootstrap_active is not None:
            self.bootstrap_active = None
        if self.active_execution is not None:
            self.active_execution.status = "aborted"
            self.active_execution.safety_override = (self.active_execution.safety_override + f"; {reason}").strip("; ")
            self.finalize_execution("aborted")
        self.api_status = "stopped"
        self.last_error = reason

    def perception_ready_without_odom(self) -> Tuple[bool, Dict[str, object]]:
        now = time.time()
        rgb_age = now - self.last_rgb_received_at if self.last_rgb_received_at > 0.0 else None
        depth_age = now - self.last_depth_received_at if self.last_depth_received_at > 0.0 else None
        info = {
            "rgb_age_s": rgb_age,
            "depth_age_s": depth_age,
            "camera_info_ready": self.fx is not None,
            "pose_source": self.args.pose_source,
        }
        ready = True
        for age in (rgb_age, depth_age):
            if age is None or age > self.args.stale_timeout:
                ready = False
        if self.fx is None or self.rgb_bgr is None or self.depth_vis is None:
            ready = False
        return ready, info

    def data_is_fresh(self) -> Tuple[bool, Dict[str, object]]:
        now = time.time()
        rgb_age = now - self.last_rgb_received_at if self.last_rgb_received_at > 0.0 else None
        depth_age = now - self.last_depth_received_at if self.last_depth_received_at > 0.0 else None
        odom_age = now - self.last_odom_received_at if self.last_odom_received_at > 0.0 else None
        imu_age = now - self.last_imu_received_at if self.last_imu_received_at > 0.0 else None
        stale = {
            "rgb_age_s": rgb_age,
            "depth_age_s": depth_age,
            "odom_age_s": odom_age,
            "imu_age_s": imu_age,
            "camera_info_ready": self.fx is not None,
            "pose_source": self.args.pose_source,
            "yaw_source": self.args.yaw_source,
            "goal_anchor_ready": self.start_local_goal_anchor_ready(self.current_pose),
        }
        fresh = True
        required_ages = [rgb_age, depth_age]
        if self.args.pose_source == "odom":
            required_ages.append(odom_age)
        if self.args.yaw_source == "imu":
            required_ages.append(imu_age)
        for age in required_ages:
            if age is None or age > self.args.stale_timeout:
                fresh = False
        if self.fx is None:
            fresh = False
        if self.current_pose is None:
            fresh = False
        if not stale["goal_anchor_ready"]:
            fresh = False
        return fresh, stale

    def resolve_goal_world(self, pose: Optional[Pose2D]) -> Tuple[Optional[float], Optional[float]]:
        if self.args.goal_frame == "world":
            return self.goal_x, self.goal_y

        if pose is None:
            return self.goal_x, self.goal_y

        if not self.start_local_goal_anchor_ready(pose):
            return self.goal_x, self.goal_y

        if self.goal_x is None or self.goal_y is None:
            delta_x, delta_y = robot_to_world(self.goal_input_x, self.goal_input_y, pose.yaw)
            self.goal_x = pose.x + delta_x
            self.goal_y = pose.y + delta_y
            self.goal_anchor_pose = Pose2D(pose.stamp, pose.x, pose.y, pose.yaw)
            self.get_logger().info(
                "resolved start_local goal to world frame: "
                f"world=({self.goal_x:.3f}, {self.goal_y:.3f}) "
                f"from anchor=({pose.x:.3f}, {pose.y:.3f}, {math.degrees(pose.yaw):.1f}deg)"
            )
        return self.goal_x, self.goal_y

    def goal_world_line(self, pose: Optional[Pose2D]) -> str:
        goal_x, goal_y = self.resolve_goal_world(pose)
        if goal_x is None or goal_y is None:
            return "pending-start-anchor"
        return f"x={goal_x:.3f}, y={goal_y:.3f}"

    def compute_global_goal_local(self, pose: Pose2D) -> Tuple[float, float, float, float]:
        goal_x, goal_y = self.resolve_goal_world(pose)
        if goal_x is None or goal_y is None:
            right = self.goal_input_x
            forward = self.goal_input_y
            distance = math.hypot(right, forward)
            bearing_deg = math.degrees(math.atan2(right, forward))
            return right, forward, distance, bearing_deg

        dx = goal_x - pose.x
        dy = goal_y - pose.y
        right, forward = world_to_robot(dx, dy, pose.yaw)
        distance = math.hypot(right, forward)
        bearing_deg = math.degrees(math.atan2(right, forward))
        return right, forward, distance, bearing_deg

    def local_goal_tuple_from_state(self, pose: Pose2D) -> Optional[Tuple[float, float, float, float]]:
        if self.local_goal_world_x is None or self.local_goal_world_y is None:
            return None
        dx = float(self.local_goal_world_x) - pose.x
        dy = float(self.local_goal_world_y) - pose.y
        right, forward = world_to_robot(dx, dy, pose.yaw)
        distance = math.hypot(right, forward)
        bearing_deg = math.degrees(math.atan2(right, forward))
        return right, forward, distance, bearing_deg

    def heading_alignment_local_tuple(
        self,
        global_goal: Tuple[float, float, float, float],
    ) -> Tuple[float, float, float, float]:
        global_right, global_forward, _, global_bearing_deg = global_goal
        rotate_radius = max(0.35, float(self.args.rotate_local_goal_radius_m))
        turn_sign = desired_angular_sign(global_right)
        if turn_sign == 0.0:
            turn_sign = -1.0 if global_bearing_deg > 0.0 else 1.0
        right = -turn_sign * rotate_radius
        forward = 0.0
        distance = rotate_radius
        bearing_deg = math.degrees(math.atan2(right, max(forward, 1e-3)))
        if abs(global_forward) < 0.05 and abs(global_bearing_deg) < 1.0:
            right = 0.0
            distance = 0.0
            bearing_deg = 0.0
        return right, forward, distance, bearing_deg

    def compute_goal_local(self, pose: Pose2D) -> Tuple[float, float, float, float]:
        global_goal = self.compute_global_goal_local(pose)
        local_goal = self.local_goal_tuple_from_state(pose)
        if local_goal is not None:
            return local_goal
        return global_goal

    def planning_reference_local_tuple(
        self,
        pose: Pose2D,
    ) -> Tuple[Optional[Tuple[float, float, float, float]], str]:
        local_goal = self.local_goal_tuple_from_state(pose)
        if local_goal is not None and getattr(self, "local_goal_mode", "translate") != "rotate_to_global":
            return local_goal, "active-local-goal"

        if self.active_execution is not None:
            waypoint = self.execution_waypoint_local(self.active_execution, pose)
            right = float(waypoint["right_m"])
            forward = float(waypoint["forward_m"])
            distance = math.hypot(right, forward)
            bearing_deg = math.degrees(math.atan2(right, max(forward, 1e-3)))
            return (right, forward, distance, bearing_deg), "active-execution"

        if self.execution_queue:
            waypoint = self.execution_waypoint_local(self.execution_queue[0], pose)
            right = float(waypoint["right_m"])
            forward = float(waypoint["forward_m"])
            distance = math.hypot(right, forward)
            bearing_deg = math.degrees(math.atan2(right, max(forward, 1e-3)))
            return (right, forward, distance, bearing_deg), "queue-head"

        return None, "none"

    def local_goal_needs_refresh(
        self,
        pose: Pose2D,
        local_tuple: Optional[Tuple[float, float, float, float]],
        global_distance: float,
    ) -> Tuple[bool, str]:
        if local_tuple is None:
            return True, "missing-local-goal"

        right, forward, distance, _ = local_tuple
        if distance <= self.args.local_goal_reach_m:
            return True, "local-goal-reached"
        if forward < -0.20:
            return True, "local-goal-behind-robot"
        if self.local_goal_updated_step > 0:
            age_steps = max(0, (self.step_counter + 1) - self.local_goal_updated_step)
            if age_steps >= self.args.local_goal_hold_steps:
                still_good_forward = (
                    distance > max(self.args.local_goal_reach_m * 1.5, 0.55)
                    and forward > max(0.35, self.args.local_goal_min_forward_m * 0.7)
                    and global_distance > (self.args.local_goal_lookahead_m + 0.35)
                )
                if not still_good_forward:
                    return True, "local-goal-aged-out"
        path_blocked, block_along, _ = self.red_point_path_blocked(
            right,
            max(0.25, forward),
            pose=pose,
            extra_margin=0.04,
        )
        if path_blocked and block_along is not None and block_along < max(0.75, distance * 0.85):
            return True, "local-goal-path-blocked"
        if global_distance <= self.args.local_goal_lookahead_m:
            return True, "global-goal-within-lookahead"
        return False, "keep-local-goal"

    def should_force_heading_alignment(
        self,
        global_forward: float,
        global_bearing_deg: float,
    ) -> bool:
        self.heading_alignment_active = False
        return False

    def smooth_translate_candidate(
        self,
        pose: Pose2D,
        candidate: Dict[str, float],
        refresh_reason: str,
    ) -> Tuple[Dict[str, float], Optional[str]]:
        if getattr(self, "local_goal_mode", "translate") == "rotate_to_global":
            return candidate, None
        if refresh_reason in ("local-goal-path-blocked", "local-goal-behind-robot", "missing-local-goal"):
            return candidate, None

        reference_local, reference_source = self.planning_reference_local_tuple(pose)
        if reference_local is None:
            return candidate, None

        ref_right, ref_forward, _, _ = reference_local
        candidate_right = float(candidate["right_m"])
        candidate_forward = float(candidate["forward_m"])
        candidate_speed = float(candidate["speed_mps"])

        current_heading = math.atan2(ref_right, max(ref_forward, 0.12))
        candidate_heading = math.atan2(candidate_right, max(candidate_forward, 0.12))
        heading_delta = abs(normalize_angle(candidate_heading - current_heading))
        lateral_delta = abs(candidate_right - ref_right)

        if heading_delta < math.radians(8.0) and lateral_delta < 0.22:
            return candidate, None

        current_weight = 0.58
        if refresh_reason == "local-goal-aged-out":
            current_weight = 0.68
        elif refresh_reason == "local-goal-reached":
            current_weight = 0.42
        elif refresh_reason == "global-goal-within-lookahead":
            current_weight = 0.32

        same_side = (
            abs(ref_right) < 0.14
            or abs(candidate_right) < 0.14
            or math.copysign(1.0, ref_right) == math.copysign(1.0, candidate_right)
        )
        if not same_side:
            current_weight = min(current_weight, 0.42)

        smoothed_right = (current_weight * ref_right) + ((1.0 - current_weight) * candidate_right)
        smoothed_forward = max(
            0.25,
            (current_weight * max(0.25, ref_forward)) + ((1.0 - current_weight) * max(0.25, candidate_forward)),
        )
        smoothed_speed = max(candidate_speed, 0.0)

        candidate_clearance, _, _ = self.path_min_clearance(candidate_right, candidate_forward, pose=pose)
        smoothed_clearance, _, _ = self.path_min_clearance(smoothed_right, smoothed_forward, pose=pose)
        smooth_blocked, _, _ = self.red_point_path_blocked(
            smoothed_right,
            max(0.25, smoothed_forward),
            pose=pose,
            extra_margin=0.05,
        )
        if smooth_blocked:
            return candidate, None

        if not math.isfinite(candidate_clearance):
            candidate_clearance = self.args.desired_clearance + 1.0
        if not math.isfinite(smoothed_clearance):
            smoothed_clearance = self.args.desired_clearance + 1.0
        if smoothed_clearance < (candidate_clearance - 0.10):
            return candidate, None

        return {
            "right_m": smoothed_right,
            "forward_m": smoothed_forward,
            "speed_mps": smoothed_speed,
        }, f"smooth-local-goal-with-{reference_source}"

    def choose_local_goal_candidate(
        self,
        pose: Pose2D,
        global_goal: Tuple[float, float, float, float],
        obstacle_metrics: Dict[str, object],
        planner_hint: Dict[str, object],
        refresh_reason: str,
        force_rotate_mode: bool,
    ) -> Tuple[Dict[str, float], str, str, str]:
        global_right, global_forward, global_distance, global_bearing_deg = global_goal
        max_wp_forward = min(float(self.args.local_goal_lookahead_m), self.max_forward * 0.55)
        max_wp_right = min(float(self.args.local_goal_lookahead_m), self.max_side * 0.75)
        min_forward = min(max_wp_forward, max(0.35, float(self.args.local_goal_min_forward_m)))
        corridor = obstacle_metrics.get("corridor", {})
        sectors = obstacle_metrics.get("sectors", {})
        corridor_center = optional_finite_float(corridor.get("center_right_m"))
        can_reuse_active = refresh_reason in ("missing-local-goal", "keep-local-goal")
        rotate_mode_needed = force_rotate_mode

        if rotate_mode_needed:
            rotation_bias = self.sector_rotation_bias(sectors)
            if rotation_bias != 0.0:
                point_sign = -rotation_bias
            elif abs(global_right) > 0.08:
                point_sign = 1.0 if global_right > 0.0 else -1.0
            else:
                point_sign = -1.0 if global_bearing_deg < 0.0 else 1.0
            rotate_radius = clamp(float(self.args.rotate_local_goal_radius_m), 0.35, max_wp_right)
            return {
                "right_m": point_sign * rotate_radius,
                "forward_m": clamp(0.05, 0.0, max_wp_forward),
                "speed_mps": min(self.args.max_linear, 0.12),
            }, "rotate-goal", "global-goal-behind-rotate-subgoal", "rotate_to_global"

        if global_distance <= self.args.local_goal_lookahead_m:
            return {
                "right_m": global_right,
                "forward_m": global_forward,
                "speed_mps": min(self.args.max_linear, 0.65),
            }, "global-goal", "global-goal-within-lookahead", "translate"

        if can_reuse_active and self.active_execution is not None:
            current_local = self.execution_waypoint_local(self.active_execution, pose)
            return current_local, "active-execution", "reuse-active-execution-waypoint", "translate"

        if self.execution_queue:
            queued_local = self.execution_waypoint_local(self.execution_queue[0], pose)
            return queued_local, "queue-head", "reuse-queued-waypoint", "translate"

        planner_best = planner_hint.get("best", {})
        if (
            self.route_plan_mode == "startup-explore"
            and (self.step_counter + 1) <= self.route_plan_hold_until_step
            and planner_best
        ):
            startup_right = optional_finite_float(planner_best.get("right_m"))
            startup_forward = optional_finite_float(planner_best.get("forward_m"))
            startup_speed = optional_finite_float(planner_best.get("speed_mps"))
            if startup_right is not None and startup_forward is not None and startup_speed is not None:
                return {
                    "right_m": startup_right,
                    "forward_m": startup_forward,
                    "speed_mps": startup_speed,
                }, "startup-explore", "use-startup-exploration-subgoal", "translate"

        planner_right = optional_finite_float(planner_best.get("right_m"))
        planner_forward = optional_finite_float(planner_best.get("forward_m"))
        planner_speed = optional_finite_float(planner_best.get("speed_mps"))
        if (
            planner_right is not None
            and planner_forward is not None
            and planner_speed is not None
            and not bool(planner_best.get("blocked", False))
        ):
            return {
                "right_m": planner_right,
                "forward_m": planner_forward,
                "speed_mps": planner_speed,
            }, f"planner:{planner_best.get('label', 'best')}", "planner-best-candidate", "translate"

        projected_right = clamp(global_right, -max_wp_right, max_wp_right)
        projected_forward = clamp(max(global_forward, min_forward), min_forward, max_wp_forward)
        if corridor_center is not None:
            projected_right = clamp((0.45 * projected_right) + (0.55 * corridor_center), -max_wp_right, max_wp_right)
            return {
                "right_m": projected_right,
                "forward_m": projected_forward,
                "speed_mps": min(self.args.max_linear, 0.55),
            }, "corridor-projection", "blend-global-goal-with-corridor-center", "translate"

        return {
            "right_m": projected_right,
            "forward_m": projected_forward,
            "speed_mps": min(self.args.max_linear, 0.55),
        }, "global-projection", "project-global-goal-into-local-lookahead", "translate"

    def update_goal_state(
        self,
        pose: Pose2D,
        obstacle_metrics: Dict[str, object],
        planner_hint: Dict[str, object],
        force_rotate_mode: bool,
    ) -> Dict[str, object]:
        global_goal = self.compute_global_goal_local(pose)
        global_right, global_forward, global_distance, global_bearing_deg = global_goal
        current_local_goal = self.local_goal_tuple_from_state(pose)
        refresh_needed, refresh_reason = self.local_goal_needs_refresh(pose, current_local_goal, global_distance)
        if force_rotate_mode:
            align_right, align_forward, align_distance, align_bearing_deg = self.heading_alignment_local_tuple(global_goal)
            entering_alignment = (
                self.local_goal_mode != "rotate_to_global"
                or self.local_goal_source != "heading-alignment"
                or self.local_goal_world_x is not None
                or self.local_goal_world_y is not None
            )
            self.local_goal_world_x = None
            self.local_goal_world_y = None
            self.local_goal_source = "heading-alignment"
            self.local_goal_reason = (
                f"{refresh_reason}; heading-alignment-active; defer-local-goal-until-global-heading-ready"
            )
            self.local_goal_mode = "rotate_to_global"
            self.detour_commit_sign = 0.0
            self.detour_commit_until_monotonic = 0.0
            if entering_alignment or self.local_goal_created_step <= 0:
                self.local_goal_created_step = self.step_counter + 1
            self.local_goal_updated_step = self.step_counter + 1
            local_age_steps = max(0, (self.step_counter + 1) - self.local_goal_created_step)
            return {
                "global_world_x": self.goal_x,
                "global_world_y": self.goal_y,
                "global_right_m": global_right,
                "global_forward_m": global_forward,
                "global_distance_m": global_distance,
                "global_bearing_deg": global_bearing_deg,
                "local_world_x": None,
                "local_world_y": None,
                "local_right_m": align_right,
                "local_forward_m": align_forward,
                "local_distance_m": align_distance,
                "local_bearing_deg": align_bearing_deg,
                "local_source": self.local_goal_source,
                "local_reason": self.local_goal_reason,
                "local_mode": self.local_goal_mode,
                "local_created_step": self.local_goal_created_step,
                "local_updated_step": self.local_goal_updated_step,
                "local_age_steps": local_age_steps,
                "heading_alignment_active": self.heading_alignment_active,
            }

        if refresh_needed:
            candidate, source, source_reason, local_mode = self.choose_local_goal_candidate(
                pose,
                global_goal,
                obstacle_metrics,
                planner_hint,
                refresh_reason,
                force_rotate_mode,
            )
            if local_mode == "translate":
                candidate, smooth_reason = self.smooth_translate_candidate(pose, candidate, refresh_reason)
                if smooth_reason:
                    source_reason = f"{source_reason}; {smooth_reason}"
            delta_x, delta_y = robot_to_world(candidate["right_m"], candidate["forward_m"], pose.yaw)
            self.local_goal_world_x = pose.x + delta_x
            self.local_goal_world_y = pose.y + delta_y
            self.local_goal_source = source
            self.local_goal_reason = f"{refresh_reason}; {source_reason}"
            self.local_goal_mode = local_mode
            if local_mode == "rotate_to_global":
                self.detour_commit_sign = 0.0
                self.detour_commit_until_monotonic = 0.0
            self.local_goal_created_step = self.step_counter + 1
            self.local_goal_updated_step = self.step_counter + 1
            current_local_goal = self.local_goal_tuple_from_state(pose)
        elif current_local_goal is not None:
            self.local_goal_reason = refresh_reason
            if not hasattr(self, "local_goal_mode"):
                self.local_goal_mode = "translate"

        if force_rotate_mode and self.local_goal_mode != "rotate_to_global":
            self.local_goal_mode = "rotate_to_global"
            self.detour_commit_sign = 0.0
            self.detour_commit_until_monotonic = 0.0

        if current_local_goal is None:
            current_local_goal = global_goal

        local_right, local_forward, local_distance, local_bearing_deg = current_local_goal
        local_age_steps = 0
        if self.local_goal_updated_step > 0:
            local_age_steps = max(0, (self.step_counter + 1) - self.local_goal_updated_step)

        return {
            "global_world_x": self.goal_x,
            "global_world_y": self.goal_y,
            "global_right_m": global_right,
            "global_forward_m": global_forward,
            "global_distance_m": global_distance,
            "global_bearing_deg": global_bearing_deg,
            "local_world_x": self.local_goal_world_x,
            "local_world_y": self.local_goal_world_y,
            "local_right_m": local_right,
            "local_forward_m": local_forward,
            "local_distance_m": local_distance,
            "local_bearing_deg": local_bearing_deg,
            "local_source": self.local_goal_source,
            "local_reason": self.local_goal_reason,
            "local_mode": getattr(self, "local_goal_mode", "translate"),
            "local_created_step": self.local_goal_created_step,
            "local_updated_step": self.local_goal_updated_step,
            "local_age_steps": local_age_steps,
            "heading_alignment_active": self.heading_alignment_active,
        }

    def build_pose_diagnostics(self) -> Dict[str, object]:
        effective_yaw, effective_source = self.select_effective_yaw(with_source=True)
        imu_orientation_yaw = self.imu_aligned_yaw if self.imu_aligned_yaw is not None else self.imu_raw_yaw
        imu_integrated_yaw = (
            self.imu_integrated_aligned_yaw
            if self.imu_integrated_aligned_yaw is not None
            else self.imu_integrated_raw_yaw
        )
        orientation_vs_integrated_deg = None
        if imu_orientation_yaw is not None and imu_integrated_yaw is not None:
            orientation_vs_integrated_deg = math.degrees(
                normalize_angle(imu_orientation_yaw - imu_integrated_yaw)
            )

        effective_vs_cmd_deg = None
        if effective_yaw is not None and self.cmd_yaw_estimate is not None:
            effective_vs_cmd_deg = math.degrees(normalize_angle(effective_yaw - self.cmd_yaw_estimate))

        effective_vs_odom_deg = None
        if effective_yaw is not None and self.odom_reported_yaw is not None:
            effective_vs_odom_deg = math.degrees(normalize_angle(effective_yaw - self.odom_reported_yaw))

        warnings: List[str] = []
        if self.args.yaw_source in ("imu", "hybrid") and self.last_imu_received_at <= 0.0:
            warnings.append("imu-not-received")
        if orientation_vs_integrated_deg is not None and abs(orientation_vs_integrated_deg) > 15.0:
            warnings.append("imu-orientation-vs-gyro-drift")
        if effective_vs_cmd_deg is not None and abs(effective_vs_cmd_deg) > 20.0:
            warnings.append("heading-vs-cmd-drift")
        if effective_vs_odom_deg is not None and abs(effective_vs_odom_deg) > 25.0:
            warnings.append("heading-vs-odom-drift")

        return {
            "effective_yaw_source": effective_source,
            "imu_raw_yaw_deg": math.degrees(self.imu_raw_yaw) if self.imu_raw_yaw is not None else None,
            "imu_aligned_yaw_deg": math.degrees(self.imu_aligned_yaw) if self.imu_aligned_yaw is not None else None,
            "imu_integrated_yaw_deg": (
                math.degrees(imu_integrated_yaw) if imu_integrated_yaw is not None else None
            ),
            "odom_yaw_deg": math.degrees(self.odom_reported_yaw) if self.odom_reported_yaw is not None else None,
            "cmd_yaw_estimate_deg": (
                math.degrees(self.cmd_yaw_estimate) if self.cmd_yaw_estimate is not None else None
            ),
            "yaw_alignment_offset_deg": (
                math.degrees(self.yaw_alignment_offset) if self.yaw_alignment_offset is not None else None
            ),
            "orientation_vs_integrated_deg": orientation_vs_integrated_deg,
            "effective_vs_cmd_deg": effective_vs_cmd_deg,
            "effective_vs_odom_deg": effective_vs_odom_deg,
            "last_imu_angular_z": self.last_imu_angular_z,
            "dead_reckoned_distance_m": self.dead_reckoned_distance_m,
            "dead_reckoned_turn_deg": math.degrees(self.dead_reckoned_turn_rad),
            "warnings": warnings,
        }

    def goal_is_complete(self, distance_m: float) -> bool:
        return distance_m <= self.args.goal_complete_distance

    def maybe_mark_goal_complete(self, pose: Optional[Pose2D], reason: str = "goal-complete") -> bool:
        if pose is None:
            return False

        _, _, goal_distance, _ = self.compute_global_goal_local(pose)
        if not self.goal_is_complete(goal_distance):
            return False

        self.goal_completed = True
        self.execution_queue.clear()
        self.detour_commit_sign = 0.0
        self.detour_commit_until_monotonic = 0.0
        if self.pending_future is not None:
            self.ignore_next_result = True
        self.stop_ramp = None
        self.bootstrap_active = None
        self.latest_reasoning = f"goal complete within {self.args.goal_complete_distance:.2f} m"
        self.latest_risk = "complete"
        self.latest_action_text = "ACTION: [0.0, 0.0, 0.0]"
        self.api_status = "complete"
        self.last_error = ""

        if self.active_execution is not None:
            self.active_execution.status = "completed"
            self.active_execution.safety_override = (
                self.active_execution.safety_override + f"; {reason}"
            ).strip("; ")
            self.stop_robot(immediate=True)
            self.finalize_execution("goal-complete")
        else:
            self.stop_robot(immediate=True)

        self.log_step_event(
            {
                "kind": "goal_complete",
                "timestamp": time.time(),
                "reason": reason,
                "pose": asdict(pose),
                "goal_distance_m": goal_distance,
                "threshold_m": self.args.goal_complete_distance,
            }
        )
        return True

    def analyze_obstacles(self) -> Dict[str, object]:
        self.latest_obstacle_cloud = None
        metrics: Dict[str, object] = {
            "status": "waiting",
            "nearest_distance_m": None,
            "nearest_heading_deg": None,
            "front_clearance_m": None,
            "desired_clearance_m": self.args.desired_clearance,
            "point_count": 0,
            "floor_mode": "none",
            "sectors": {},
            "corridor": {
                "status": "unknown",
                "lookahead_min_m": 0.45,
                "lookahead_max_m": min(self.max_forward * 0.7, 2.8),
                "left_wall_x_m": None,
                "right_wall_x_m": None,
                "left_clearance_m": None,
                "right_clearance_m": None,
                "center_right_m": 0.0,
                "width_m": None,
            },
        }

        if self.depth_m is None:
            metrics["status"] = "waiting-depth"
            return metrics
        if not self.ensure_ray_table():
            metrics["status"] = "waiting-camera-info"
            return metrics

        depth_sub = self.depth_m[:: self.stride, :: self.stride]
        if depth_sub.shape != self.ray_x.shape:
            h = min(depth_sub.shape[0], self.ray_x.shape[0])
            w = min(depth_sub.shape[1], self.ray_x.shape[1])
            if h <= 0 or w <= 0:
                metrics["status"] = "shape-mismatch"
                return metrics
            depth_sub = depth_sub[:h, :w]
            ray_x = self.ray_x[:h, :w]
            ray_y = self.ray_y[:h, :w]
        else:
            ray_x = self.ray_x
            ray_y = self.ray_y

        z = depth_sub
        valid = np.isfinite(z) & (z >= self.depth_min) & (z <= self.depth_max)
        if not np.any(valid):
            metrics["status"] = "no-valid-depth"
            return metrics

        x = ray_x * z
        y = ray_y * z
        valid &= np.abs(x) <= self.max_side
        valid &= z <= self.max_forward

        floor_mode = "none"
        if self.camera_height > 0.0:
            valid &= y < (self.camera_height - self.floor_tolerance)
            floor_mode = f"height={self.camera_height:.2f}m"
        elif self.auto_floor_bottom_ratio > 0.0:
            h_sub = depth_sub.shape[0]
            bottom_start = int(h_sub * (1.0 - self.auto_floor_bottom_ratio))
            row_idx = np.arange(h_sub, dtype=np.int32)[:, None]
            floor_candidates = valid & (row_idx >= bottom_start)
            if np.any(floor_candidates):
                floor_y = float(np.percentile(y[floor_candidates], self.auto_floor_percentile))
                valid &= y < (floor_y - self.floor_tolerance)
                floor_mode = f"auto-bottom({self.auto_floor_bottom_ratio:.2f})"
            else:
                floor_mode = "auto-bottom(no-cand)"
        metrics["floor_mode"] = floor_mode

        if not np.any(valid):
            metrics["status"] = "no-obstacles"
            return metrics

        x_obs = x[valid]
        z_obs = z[valid]
        self.latest_obstacle_cloud = {
            "right_m": x_obs.copy(),
            "forward_m": z_obs.copy(),
        }
        distances = np.sqrt(x_obs * x_obs + z_obs * z_obs)
        headings = np.degrees(np.arctan2(x_obs, z_obs))

        if distances.size > 0:
            i = int(np.argmin(distances))
            metrics["nearest_distance_m"] = float(distances[i])
            metrics["nearest_heading_deg"] = float(headings[i])

        front_mask = np.abs(headings) <= 20.0
        if np.any(front_mask):
            metrics["front_clearance_m"] = float(np.min(distances[front_mask]))

        front_stop_clearance = self.robot_front_stop_clearance()
        preferred_center_clearance = self.robot_preferred_center_clearance()
        sectors = {}
        for name, mask in (
            ("left", headings < -15.0),
            ("center", np.abs(headings) <= 15.0),
            ("right", headings > 15.0),
        ):
            if np.any(mask):
                min_dist = float(np.min(distances[mask]))
                count = int(np.sum(mask))
                if min_dist < front_stop_clearance:
                    label = "blocked"
                elif min_dist < preferred_center_clearance:
                    label = "tight"
                elif min_dist < (preferred_center_clearance + 0.45):
                    label = "crowded"
                else:
                    label = "open"
            else:
                min_dist = None
                count = 0
                label = "clear"
            sectors[name] = {"count": count, "min_distance_m": min_dist, "label": label}

        corridor = dict(metrics["corridor"])
        corridor_mask = (z_obs >= corridor["lookahead_min_m"]) & (z_obs <= corridor["lookahead_max_m"])
        if np.any(corridor_mask):
            x_corridor = x_obs[corridor_mask]
            left_points = x_corridor[x_corridor < -0.10]
            right_points = x_corridor[x_corridor > 0.10]
            wall_bias = clamp(self.robot_side_escape_clearance() * 0.7, 0.45, 1.05)
            left_wall_x = float(np.max(left_points)) if left_points.size > 0 else None
            right_wall_x = float(np.min(right_points)) if right_points.size > 0 else None

            corridor["left_wall_x_m"] = left_wall_x
            corridor["right_wall_x_m"] = right_wall_x
            corridor["left_clearance_m"] = abs(left_wall_x) if left_wall_x is not None else None
            corridor["right_clearance_m"] = right_wall_x if right_wall_x is not None else None

            if left_wall_x is not None and right_wall_x is not None:
                corridor["status"] = "bounded"
                corridor["center_right_m"] = 0.5 * (left_wall_x + right_wall_x)
                corridor["width_m"] = max(0.0, right_wall_x - left_wall_x)
            elif left_wall_x is not None:
                corridor["status"] = "left-wall"
                corridor["center_right_m"] = clamp(left_wall_x + wall_bias, -self.max_side, self.max_side)
            elif right_wall_x is not None:
                corridor["status"] = "right-wall"
                corridor["center_right_m"] = clamp(right_wall_x - wall_bias, -self.max_side, self.max_side)
            else:
                corridor["status"] = "open"
                corridor["center_right_m"] = 0.0
        else:
            corridor["status"] = "no-forward-band"

        metrics["status"] = "ready"
        metrics["point_count"] = int(distances.size)
        metrics["sectors"] = sectors
        metrics["corridor"] = corridor
        return metrics

    def update_world_obstacle_memory(self, pose: Optional[Pose2D]):
        if pose is None:
            return

        cloud = self.latest_obstacle_cloud
        if cloud is None:
            return

        right_points = cloud.get("right_m")
        forward_points = cloud.get("forward_m")
        if right_points is None or forward_points is None or right_points.size == 0 or forward_points.size == 0:
            return

        now = time.time()
        cos_yaw = math.cos(pose.yaw)
        sin_yaw = math.sin(pose.yaw)
        world_x = pose.x + (forward_points * cos_yaw) + (right_points * sin_yaw)
        world_y = pose.y + (forward_points * sin_yaw) - (right_points * cos_yaw)
        stamps = np.full(world_x.shape, now, dtype=np.float32)
        new_points = np.column_stack(
            (
                world_x.astype(np.float32, copy=False),
                world_y.astype(np.float32, copy=False),
                stamps,
            )
        )

        if self.world_obstacle_memory.size == 0:
            merged = new_points
        else:
            merged = np.vstack((self.world_obstacle_memory, new_points))

        age_limit = now - float(self.args.memory_horizon_s)
        merged = merged[merged[:, 2] >= age_limit]
        if merged.size == 0:
            self.world_obstacle_memory = np.empty((0, 3), dtype=np.float32)
            return

        dx = merged[:, 0] - pose.x
        dy = merged[:, 1] - pose.y
        max_dist_sq = float(self.args.memory_range_m) ** 2
        merged = merged[(dx * dx + dy * dy) <= max_dist_sq]
        if merged.size == 0:
            self.world_obstacle_memory = np.empty((0, 3), dtype=np.float32)
            return

        order = np.argsort(merged[:, 2])[::-1]
        merged = merged[order]
        voxel = max(0.05, float(self.args.memory_voxel_m))
        voxel_xy = np.round(merged[:, :2] / voxel).astype(np.int32)
        structured = np.empty(voxel_xy.shape[0], dtype=[("x", np.int32), ("y", np.int32)])
        structured["x"] = voxel_xy[:, 0]
        structured["y"] = voxel_xy[:, 1]
        _, unique_idx = np.unique(structured, return_index=True)
        keep_mask = np.zeros(structured.shape[0], dtype=bool)
        keep_mask[unique_idx] = True
        merged = merged[keep_mask]
        max_points = 6000
        if merged.shape[0] > max_points:
            merged = merged[:max_points]
        self.world_obstacle_memory = merged.astype(np.float32, copy=False)

    def local_memory_cloud(self, pose: Optional[Pose2D]) -> Optional[Dict[str, np.ndarray]]:
        if pose is None or self.world_obstacle_memory.size == 0:
            return None

        dx = self.world_obstacle_memory[:, 0] - pose.x
        dy = self.world_obstacle_memory[:, 1] - pose.y
        sin_yaw = math.sin(pose.yaw)
        cos_yaw = math.cos(pose.yaw)
        right = (dx * sin_yaw) - (dy * cos_yaw)
        forward = (dx * cos_yaw) + (dy * sin_yaw)
        mask = (
            (forward >= -0.25)
            & (forward <= max(self.max_forward, float(self.args.memory_range_m)))
            & (np.abs(right) <= max(self.max_side, float(self.args.memory_range_m)))
        )
        if not np.any(mask):
            return None
        return {
            "right_m": right[mask].astype(np.float32, copy=False),
            "forward_m": forward[mask].astype(np.float32, copy=False),
        }

    def combined_local_obstacle_cloud(self, pose: Optional[Pose2D]) -> Optional[Dict[str, np.ndarray]]:
        parts_right: List[np.ndarray] = []
        parts_forward: List[np.ndarray] = []

        if self.latest_obstacle_cloud is not None:
            current_right = self.latest_obstacle_cloud.get("right_m")
            current_forward = self.latest_obstacle_cloud.get("forward_m")
            if current_right is not None and current_forward is not None and current_right.size > 0 and current_forward.size > 0:
                parts_right.append(current_right.astype(np.float32, copy=False))
                parts_forward.append(current_forward.astype(np.float32, copy=False))

        memory_cloud = self.local_memory_cloud(pose)
        if memory_cloud is not None:
            parts_right.append(memory_cloud["right_m"])
            parts_forward.append(memory_cloud["forward_m"])

        if not parts_right:
            return None

        return {
            "right_m": np.concatenate(parts_right),
            "forward_m": np.concatenate(parts_forward),
        }

    def path_min_clearance(
        self,
        waypoint_right: float,
        waypoint_forward: float,
        pose: Optional[Pose2D] = None,
    ) -> Tuple[float, Optional[float], float]:
        cloud = self.combined_local_obstacle_cloud(pose if pose is not None else self.current_pose)
        if cloud is None:
            return float("inf"), None, 0.0

        right_points = cloud.get("right_m")
        forward_points = cloud.get("forward_m")
        if right_points is None or forward_points is None or right_points.size == 0 or forward_points.size == 0:
            return float("inf"), None, 0.0

        segment_length = math.hypot(waypoint_right, waypoint_forward)
        if not math.isfinite(segment_length) or segment_length < 0.12 or waypoint_forward <= 0.04:
            return float("inf"), None, 0.0

        unit_right = waypoint_right / segment_length
        unit_forward = waypoint_forward / segment_length
        along_track = (right_points * unit_right) + (forward_points * unit_forward)
        cross_track = np.abs((right_points * unit_forward) - (forward_points * unit_right))
        relevant = (
            (along_track >= 0.10)
            & (along_track <= min(segment_length + 0.20, self.max_forward))
        )
        if not np.any(relevant):
            return float("inf"), None, 0.0

        relevant_cross = cross_track[relevant]
        relevant_along = along_track[relevant]
        relevant_right = right_points[relevant]
        min_index = int(np.argmin(relevant_cross))
        min_clearance = float(relevant_cross[min_index])
        nearest_along = float(relevant_along[min_index])
        nearest_side = float(relevant_right[min_index])
        return min_clearance, nearest_along, nearest_side

    def build_map_memory_summary(self, pose: Pose2D) -> Dict[str, object]:
        memory_cloud = self.local_memory_cloud(pose)
        if memory_cloud is None:
            return {
                "status": "empty",
                "point_count": 0,
                "nearest_distance_m": None,
                "nearest_heading_deg": None,
                "front_memory_clearance_m": None,
                "sectors": {
                    "left": {"count": 0, "min_distance_m": None},
                    "center": {"count": 0, "min_distance_m": None},
                    "right": {"count": 0, "min_distance_m": None},
                },
            }

        right = memory_cloud["right_m"]
        forward = memory_cloud["forward_m"]
        distances = np.sqrt((right * right) + (forward * forward))
        headings = np.degrees(np.arctan2(right, forward))
        nearest_index = int(np.argmin(distances))
        front_mask = np.abs(headings) <= 18.0
        sectors: Dict[str, Dict[str, object]] = {}
        for name, mask in (
            ("left", headings < -12.0),
            ("center", np.abs(headings) <= 12.0),
            ("right", headings > 12.0),
        ):
            if np.any(mask):
                sectors[name] = {
                    "count": int(np.sum(mask)),
                    "min_distance_m": float(np.min(distances[mask])),
                }
            else:
                sectors[name] = {"count": 0, "min_distance_m": None}

        return {
            "status": "ready",
            "point_count": int(distances.size),
            "nearest_distance_m": float(distances[nearest_index]),
            "nearest_heading_deg": float(headings[nearest_index]),
            "front_memory_clearance_m": float(np.min(distances[front_mask])) if np.any(front_mask) else None,
            "sectors": sectors,
        }

    def build_planner_hint(
        self,
        pose: Pose2D,
        goal_right: float,
        goal_forward: float,
        goal_distance: float,
        obstacle_metrics: Dict[str, object],
        force_rotate_mode: bool = False,
    ) -> Dict[str, object]:
        max_wp_forward = min(self.max_forward * 0.55, 2.5)
        max_wp_right = min(self.max_side * 0.75, 1.8)
        corridor = obstacle_metrics.get("corridor", {})
        corridor_center = optional_finite_float(corridor.get("center_right_m"))
        corridor_width = optional_finite_float(corridor.get("width_m"))
        desired_clearance = float(self.args.desired_clearance)
        preferred_clearance = self.robot_preferred_center_clearance()
        detour_right = clamp(desired_clearance, 0.8, max_wp_right)
        reference_local, reference_source = self.planning_reference_local_tuple(pose)
        reference_heading = None
        reference_right = None
        reference_sign = 0.0
        if reference_local is not None and reference_source != "heading-alignment":
            reference_right = float(reference_local[0])
            reference_heading = math.atan2(float(reference_local[0]), max(float(reference_local[1]), 0.12))
            reference_sign = self.waypoint_commit_sign(float(reference_local[0]), float(reference_local[1]))

        if force_rotate_mode:
            rotate_radius = clamp(float(self.args.rotate_local_goal_radius_m), 0.35, max_wp_right)
            rotate_sign = 1.0 if goal_right > 0.0 else -1.0
            if abs(goal_right) <= 0.08:
                rotate_sign = -1.0 if goal_forward < 0.0 else 1.0
            rotate_candidate = {
                "label": "rotate-align",
                "right_m": rotate_sign * rotate_radius,
                "forward_m": 0.05,
                "speed_mps": 0.10,
                "min_clearance_m": None,
                "block_along_m": None,
                "blocked": False,
                "candidate_sign": rotate_sign,
                "commitment_bonus": 0.0,
                "score": 0.0,
            }
            return {
                "best": rotate_candidate,
                "candidates": [rotate_candidate],
                "commitment_sign": 0.0,
                "commitment_source": "rotate-align",
            }

        step_index = self.step_counter + 1
        if (
            self.route_plan_mode == "startup-explore"
            and self.route_plan_sign != 0.0
            and step_index <= self.route_plan_hold_until_step
        ):
            explore_right = clamp(
                self.route_plan_sign * clamp(desired_clearance * 1.05, 0.9, max_wp_right),
                -max_wp_right,
                max_wp_right,
            )
            explore_forward = min(max_wp_forward, 1.15)
            blocked, _, _ = self.red_point_path_blocked(
                explore_right,
                explore_forward,
                pose=pose,
                extra_margin=0.08,
            )
            if blocked:
                explore_forward = 0.0
            explore_clearance, _, _ = self.path_min_clearance(explore_right, max(0.25, explore_forward), pose=pose)
            startup_candidate = {
                "label": "startup-explore",
                "right_m": explore_right,
                "forward_m": explore_forward,
                "speed_mps": min(self.args.max_linear, 0.38 if explore_forward > 0.2 else 0.0),
                "min_clearance_m": explore_clearance if math.isfinite(explore_clearance) else None,
                "block_along_m": None,
                "blocked": bool(blocked),
                "candidate_sign": self.route_plan_sign,
                "commitment_bonus": 0.55,
                "score": 10.0 if not blocked else 5.0,
            }
            return {
                "best": startup_candidate,
                "candidates": [startup_candidate],
                "commitment_sign": self.route_plan_sign,
                "commitment_source": "startup-explore",
            }

        candidates: List[Dict[str, float]] = []
        candidates.append(
            {
                "label": "direct",
                "right_m": clamp(goal_right, -max_wp_right, max_wp_right),
                "forward_m": clamp(max(goal_forward, 0.9), 0.6, max_wp_forward),
                "speed_mps": min(self.args.max_linear, 0.95),
            }
        )

        center_right = corridor_center if corridor_center is not None else 0.0
        candidates.append(
            {
                "label": "corridor-center",
                "right_m": clamp(center_right, -max_wp_right, max_wp_right),
                "forward_m": clamp(max(goal_forward, 1.2), 0.9, max_wp_forward),
                "speed_mps": min(self.args.max_linear, 1.15 if corridor_width is None or corridor_width > 1.8 else 0.90),
            }
        )
        candidates.append(
            {
                "label": "left-detour",
                "right_m": -detour_right,
                "forward_m": clamp(max(goal_forward, 1.1), 0.9, max_wp_forward),
                "speed_mps": min(self.args.max_linear, 0.82),
            }
        )
        candidates.append(
            {
                "label": "right-detour",
                "right_m": detour_right,
                "forward_m": clamp(max(goal_forward, 1.1), 0.9, max_wp_forward),
                "speed_mps": min(self.args.max_linear, 0.82),
            }
        )

        if self.active_execution is not None:
            active_waypoint = self.execution_waypoint_local(self.active_execution, pose)
            candidates.append(
                {
                    "label": "continue-stream",
                    "right_m": clamp(float(active_waypoint["right_m"]), -max_wp_right, max_wp_right),
                    "forward_m": clamp(max(float(active_waypoint["forward_m"]), 0.7), 0.4, max_wp_forward),
                    "speed_mps": min(self.args.max_linear, max(0.45, float(active_waypoint["speed_mps"]))),
                }
            )
        elif self.execution_queue:
            queued_waypoint = self.execution_waypoint_local(self.execution_queue[0], pose)
            candidates.append(
                {
                    "label": "queue-head",
                    "right_m": clamp(float(queued_waypoint["right_m"]), -max_wp_right, max_wp_right),
                    "forward_m": clamp(max(float(queued_waypoint["forward_m"]), 0.7), 0.4, max_wp_forward),
                    "speed_mps": min(self.args.max_linear, max(0.45, float(queued_waypoint["speed_mps"]))),
                }
            )

        evaluated: List[Dict[str, object]] = []
        best: Optional[Dict[str, object]] = None
        committed_sign, commitment_source = self.current_commitment_sign(pose)
        best_same_sign: Optional[Dict[str, object]] = None
        best_opposite_sign: Optional[Dict[str, object]] = None
        for candidate in candidates:
            right = float(candidate["right_m"])
            forward = float(candidate["forward_m"])
            speed = float(candidate["speed_mps"])
            clearance, block_along, _ = self.path_min_clearance(right, forward, pose=pose)
            hard_margin = self.robot_hard_block_margin()
            blocked = math.isfinite(clearance) and clearance <= hard_margin
            heading = math.atan2(right, max(forward, 0.12))
            progress_score = 0.42 * min(goal_distance, max(0.0, forward))
            continuation_bonus = 0.34 * min(max(0.0, forward), 1.6)
            lateral_penalty = 0.10 * abs(right - clamp(goal_right, -1.2, 1.2))
            turn_penalty = 0.18 * abs(heading)
            clearance_bonus = 0.45 * min(clearance if math.isfinite(clearance) else (preferred_clearance + 0.8), preferred_clearance + 0.8)
            soft_clearance_penalty = 0.0
            if math.isfinite(clearance) and clearance < preferred_clearance:
                soft_clearance_penalty = 1.9 * (preferred_clearance - clearance)
            corridor_center_penalty = 0.0
            if corridor_center is not None and corridor_width is not None and corridor_width < 3.0:
                corridor_center_penalty = 0.18 * abs(right - corridor_center)
            blocked_penalty = 8.0 if blocked else 0.0
            short_penalty = 0.8 if forward < 0.75 and goal_distance > 1.2 else 0.0
            continuity_penalty = 0.0
            continuity_bonus = 0.0
            candidate_sign = self.waypoint_commit_sign(right, forward)
            if reference_heading is not None and reference_right is not None:
                continuity_penalty += 0.22 * abs(normalize_angle(heading - reference_heading))
                continuity_penalty += 0.12 * abs(right - reference_right)
                if reference_sign != 0.0 and candidate_sign != 0.0:
                    if candidate_sign == reference_sign:
                        continuity_bonus += 0.28
                    else:
                        continuity_penalty += 0.42
            score = (
                progress_score
                + continuation_bonus
                + clearance_bonus
                + continuity_bonus
                - lateral_penalty
                - turn_penalty
                - soft_clearance_penalty
                - corridor_center_penalty
                - blocked_penalty
                - short_penalty
                - continuity_penalty
            )
            commitment_bonus = 0.0
            if committed_sign != 0.0 and candidate_sign != 0.0:
                if candidate_sign == committed_sign:
                    commitment_bonus = 0.55
                else:
                    commitment_bonus = -0.85
            score += commitment_bonus
            item = {
                "label": str(candidate["label"]),
                "right_m": right,
                "forward_m": forward,
                "speed_mps": speed,
                "min_clearance_m": clearance if math.isfinite(clearance) else None,
                "block_along_m": block_along,
                "blocked": blocked,
                "candidate_sign": candidate_sign,
                "commitment_bonus": commitment_bonus,
                "score": score,
            }
            evaluated.append(item)
            if best is None or float(item["score"]) > float(best["score"]):
                best = item
            if committed_sign != 0.0 and candidate_sign == committed_sign:
                if best_same_sign is None or float(item["score"]) > float(best_same_sign["score"]):
                    best_same_sign = item
            elif committed_sign != 0.0 and candidate_sign == (-committed_sign):
                if best_opposite_sign is None or float(item["score"]) > float(best_opposite_sign["score"]):
                    best_opposite_sign = item

        assert best is not None
        if committed_sign != 0.0 and best_same_sign is not None and best_opposite_sign is not None and best is best_opposite_sign:
            same_clearance = optional_finite_float(best_same_sign.get("min_clearance_m"))
            opposite_clearance = optional_finite_float(best_opposite_sign.get("min_clearance_m"))
            if same_clearance is None:
                same_clearance = desired_clearance + 1.0
            if opposite_clearance is None:
                opposite_clearance = desired_clearance + 1.0
            if opposite_clearance < (same_clearance + self.args.flip_clearance_margin):
                best = best_same_sign

        return {
            "best": best,
            "candidates": evaluated[:4],
            "commitment_sign": committed_sign,
            "commitment_source": commitment_source,
        }

    def waypoint_commit_sign(self, right_m: float, forward_m: float) -> float:
        if forward_m < 0.45 or abs(right_m) < 0.28:
            return 0.0
        return 1.0 if right_m > 0.0 else -1.0

    def route_plan_side_label(self, sign: float) -> str:
        if sign > 0.0:
            return "right"
        if sign < 0.0:
            return "left"
        return "none"

    def clear_route_plan(self, reason: str = "clear-route-plan"):
        self.route_plan_mode = "none"
        self.route_plan_sign = 0.0
        self.route_plan_reason = reason
        self.route_plan_created_step = 0
        self.route_plan_updated_step = 0
        self.route_plan_hold_until_step = 0

    def apply_agent_plan_commitment(self, execution: ExecutionState):
        nav_mode = str(execution.requested.get("nav_mode", "progress"))
        observation_target = str(execution.requested.get("observation_target", "front_corridor"))
        commit_steps = int(execution.requested.get("plan_commit_steps", 1))
        if commit_steps <= 1:
            return

        sign = 0.0
        route_mode = "none"
        if nav_mode in ("scan_left", "detour_left"):
            sign = -1.0
            route_mode = "agent-scan" if nav_mode == "scan_left" else "agent-detour"
        elif nav_mode in ("scan_right", "detour_right"):
            sign = 1.0
            route_mode = "agent-scan" if nav_mode == "scan_right" else "agent-detour"
        elif nav_mode == "explore":
            sign = self.waypoint_commit_sign(
                float(execution.waypoint.get("right_m", 0.0)),
                float(execution.waypoint.get("forward_m", 0.0)),
            )
            route_mode = "agent-explore"

        if route_mode == "none":
            return

        if sign == 0.0:
            sign = 1.0 if float(execution.applied.get("angular_radps", 0.0)) < 0.0 else -1.0

        entering = self.route_plan_mode != route_mode or self.route_plan_sign != sign
        self.route_plan_mode = route_mode
        self.route_plan_sign = sign
        self.route_plan_reason = (
            f"llm-agent-commit nav_mode={nav_mode}; observation_target={observation_target}; "
            f"side={self.route_plan_side_label(sign)}; commit_steps={commit_steps}"
        )
        if entering or self.route_plan_created_step <= 0:
            self.route_plan_created_step = execution.step_index
        self.route_plan_updated_step = execution.step_index
        self.route_plan_hold_until_step = max(self.route_plan_hold_until_step, execution.step_index + commit_steps)

    def choose_route_plan_sign(
        self,
        pose: Pose2D,
        global_right: float,
        obstacle_metrics: Dict[str, object],
    ) -> float:
        corridor = obstacle_metrics.get("corridor", {})
        sectors = obstacle_metrics.get("sectors", {})
        left_clearance = optional_finite_float(corridor.get("left_clearance_m"))
        right_clearance = optional_finite_float(corridor.get("right_clearance_m"))
        committed_sign = 0.0
        if self.detour_commit_sign != 0.0 and time.monotonic() < self.detour_commit_until_monotonic:
            committed_sign = self.detour_commit_sign
        elif self.route_plan_mode == "around_wall" and (self.step_counter + 1) <= self.route_plan_hold_until_step:
            committed_sign = self.route_plan_sign

        def sector_bonus(name: str) -> float:
            label = str(sectors.get(name, {}).get("label", "clear"))
            return {
                "blocked": -1.2,
                "tight": -0.6,
                "crowded": -0.2,
                "open": 0.35,
                "clear": 0.25,
            }.get(label, 0.0)

        left_score = (left_clearance if left_clearance is not None else (self.args.desired_clearance + 0.7)) + sector_bonus("left")
        right_score = (right_clearance if right_clearance is not None else (self.args.desired_clearance + 0.7)) + sector_bonus("right")
        if committed_sign < 0.0:
            left_score += 0.45
        elif committed_sign > 0.0:
            right_score += 0.45

        if global_right < -0.12:
            left_score += 0.08
        elif global_right > 0.12:
            right_score += 0.08

        if right_score > (left_score + 0.05):
            return 1.0
        if left_score > (right_score + 0.05):
            return -1.0
        if committed_sign != 0.0:
            return committed_sign
        if abs(global_right) > 0.08:
            return 1.0 if global_right > 0.0 else -1.0
        return 1.0

    def update_route_plan_state(
        self,
        pose: Pose2D,
        global_goal: Tuple[float, float, float, float],
        obstacle_metrics: Dict[str, object],
        planner_hint: Dict[str, object],
    ) -> Dict[str, object]:
        step_index = self.step_counter + 1
        global_right, _global_forward, global_distance, _global_bearing_deg = global_goal
        corridor = obstacle_metrics.get("corridor", {})
        sectors = obstacle_metrics.get("sectors", {})
        front_clearance = optional_finite_float(obstacle_metrics.get("front_clearance_m"))
        center_label = str(sectors.get("center", {}).get("label", "clear"))
        planner_best = planner_hint.get("best", {})
        planner_blocked = bool(planner_best.get("blocked", False))
        corridor_status = str(corridor.get("status", "unknown"))
        global_bearing_deg = float(global_goal[3])
        front_blocked = (
            front_clearance is not None
            and front_clearance < max(self.args.min_front_clearance + 0.05, self.args.desired_clearance * 0.85)
        )
        startup_uncertain = (
            step_index <= STARTUP_EXPLORE_HOLD_STEPS
            and len(self.command_history) < 2
            and self.active_execution is None
            and not self.execution_queue
            and global_distance > max(self.args.local_goal_lookahead_m + 0.4, 1.8)
            and (
                planner_blocked
                or center_label in ("blocked", "tight")
                or corridor_status in ("unknown", "no-forward-band")
                or abs(global_bearing_deg) > 55.0
            )
        )
        blocked_now = (
            not self.heading_alignment_active
            and global_distance > 0.8
            and (front_blocked or center_label in ("blocked", "tight"))
            and (planner_blocked or corridor_status in ("bounded", "left-wall", "right-wall"))
        )

        if startup_uncertain and self.route_plan_mode == "none":
            sign = self.choose_route_plan_sign(pose, global_right, obstacle_metrics)
            self.route_plan_mode = "startup-explore"
            self.route_plan_sign = sign
            self.route_plan_reason = (
                f"startup-uncertain; bearing_deg={global_bearing_deg:.1f}; center={center_label}; "
                f"planner_blocked={planner_blocked}; corridor={corridor_status}; explore_side={self.route_plan_side_label(sign)}"
            )
            self.route_plan_created_step = step_index
            self.route_plan_updated_step = step_index
            self.route_plan_hold_until_step = step_index + STARTUP_EXPLORE_HOLD_STEPS
        elif blocked_now:
            sign = self.choose_route_plan_sign(pose, global_right, obstacle_metrics)
            entering = self.route_plan_mode != "around_wall" or self.route_plan_sign != sign
            self.route_plan_mode = "around_wall"
            self.route_plan_sign = sign
            self.route_plan_reason = (
                f"front-blocked={front_blocked}; center={center_label}; planner_blocked={planner_blocked}; "
                f"corridor={corridor_status}; detour_side={self.route_plan_side_label(sign)}"
            )
            if entering or self.route_plan_created_step <= 0:
                self.route_plan_created_step = step_index
            self.route_plan_updated_step = step_index
            self.route_plan_hold_until_step = max(self.route_plan_hold_until_step, step_index + WALL_ROUTE_PLAN_HOLD_STEPS)
        elif self.route_plan_mode in ("around_wall", "startup-explore", "agent-scan", "agent-detour", "agent-explore"):
            hold_remaining = max(0, self.route_plan_hold_until_step - step_index)
            comfortable_front = front_clearance is None or front_clearance > (self.args.desired_clearance + 0.45)
            corridor_recovered = center_label in ("clear", "open", "crowded")
            if self.route_plan_mode == "startup-explore":
                if hold_remaining <= 0 or (comfortable_front and corridor_recovered and abs(global_bearing_deg) <= 45.0):
                    self.clear_route_plan("startup-explore-complete")
                else:
                    self.route_plan_reason = (
                        f"maintain-startup-explore; hold_remaining={hold_remaining}; "
                        f"center={center_label}; front_clearance={front_clearance}; bearing_deg={global_bearing_deg:.1f}"
                    )
                    self.route_plan_updated_step = step_index
            elif self.route_plan_mode in ("agent-scan", "agent-detour", "agent-explore"):
                if hold_remaining <= 0:
                    self.clear_route_plan("agent-plan-complete")
                else:
                    self.route_plan_reason = (
                        f"maintain-{self.route_plan_mode}; hold_remaining={hold_remaining}; "
                        f"center={center_label}; front_clearance={front_clearance}"
                    )
                    self.route_plan_updated_step = step_index
            elif hold_remaining <= 0 and comfortable_front and corridor_recovered:
                self.clear_route_plan("route-plan-cleared-corridor-recovered")
            else:
                self.route_plan_reason = (
                    f"maintain-around-wall-plan; hold_remaining={hold_remaining}; "
                    f"center={center_label}; front_clearance={front_clearance}"
                )
                self.route_plan_updated_step = step_index

        age_steps = 0
        if self.route_plan_created_step > 0:
            age_steps = max(0, step_index - self.route_plan_created_step)
        hold_remaining = max(0, self.route_plan_hold_until_step - step_index)
        return {
            "mode": self.route_plan_mode,
            "sign": self.route_plan_sign,
            "side": self.route_plan_side_label(self.route_plan_sign),
            "reason": self.route_plan_reason,
            "created_step": self.route_plan_created_step,
            "updated_step": self.route_plan_updated_step,
            "age_steps": age_steps,
            "hold_remaining_steps": hold_remaining,
            "active": self.route_plan_mode != "none",
        }

    def current_commitment_sign(self, pose: Pose2D) -> Tuple[float, str]:
        now = time.monotonic()
        if (
            self.route_plan_mode in ("around_wall", "startup-explore", "agent-scan", "agent-detour", "agent-explore")
            and (self.step_counter + 1) <= self.route_plan_hold_until_step
            and self.route_plan_sign != 0.0
        ):
            return self.route_plan_sign, self.route_plan_mode
        if self.detour_commit_sign != 0.0 and now < self.detour_commit_until_monotonic:
            return self.detour_commit_sign, "latched"

        if self.active_execution is not None:
            active_waypoint = self.execution_waypoint_local(self.active_execution, pose)
            sign = self.waypoint_commit_sign(float(active_waypoint["right_m"]), float(active_waypoint["forward_m"]))
            if sign != 0.0:
                return sign, "active"

        if self.execution_queue:
            queued_waypoint = self.execution_waypoint_local(self.execution_queue[0], pose)
            sign = self.waypoint_commit_sign(float(queued_waypoint["right_m"]), float(queued_waypoint["forward_m"]))
            if sign != 0.0:
                return sign, "queue"

        return 0.0, "none"

    def latch_detour_commitment(self, waypoint: Dict[str, float]):
        sign = self.waypoint_commit_sign(float(waypoint["right_m"]), float(waypoint["forward_m"]))
        if sign == 0.0:
            return
        self.detour_commit_sign = sign
        self.detour_commit_until_monotonic = time.monotonic() + float(self.args.detour_commit_s)

    def build_history_summary(self) -> List[Dict[str, object]]:
        return [dict(item) for item in self.command_history]

    def build_trajectory_tail_lines(self, pose: Pose2D, limit: int = 8) -> List[str]:
        if not self.command_history:
            return ["- none"]

        recent = list(self.command_history)[-limit:]
        lines: List[str] = []
        oldest_end = recent[0]["end_pose"]
        newest_end = recent[-1]["end_pose"]
        net_dx = float(newest_end["x"]) - float(oldest_end["x"])
        net_dy = float(newest_end["y"]) - float(oldest_end["y"])
        net_right, net_forward = world_to_robot(net_dx, net_dy, pose.yaw)
        lines.append(
            f"- net recent delta in current local frame: right={net_right:.2f}, forward={net_forward:.2f}, steps={len(recent)}"
        )
        for idx, record in enumerate(recent, start=1):
            end_pose = record["end_pose"]
            dx = float(end_pose["x"]) - pose.x
            dy = float(end_pose["y"]) - pose.y
            right, forward = world_to_robot(dx, dy, pose.yaw)
            lines.append(
                f"- trail#{idx}: end=[r={right:.2f}, f={forward:.2f}] cmd=[{record['applied']['linear_mps']:.2f}, {record['applied']['angular_radps']:.2f}] status={record['status']}"
            )
        return lines

    def clone_previous_step_context(self) -> Optional[Dict[str, object]]:
        if self.previous_step_context is None:
            return None

        previous = self.previous_step_context
        return {
            "rgb_bgr": previous["rgb_bgr"].copy(),
            "depth_vis": previous["depth_vis"].copy(),
            "bev_img": previous["bev_img"].copy(),
            "pose": Pose2D(previous["pose"].stamp, previous["pose"].x, previous["pose"].y, previous["pose"].yaw),
            "goal_local_right": float(previous["goal_local_right"]),
            "goal_local_forward": float(previous["goal_local_forward"]),
            "goal_distance": float(previous["goal_distance"]),
            "goal_bearing_deg": float(previous["goal_bearing_deg"]),
            "global_goal_right": float(previous.get("global_goal_right", 0.0)),
            "global_goal_forward": float(previous.get("global_goal_forward", 0.0)),
            "global_goal_distance": float(previous.get("global_goal_distance", 0.0)),
            "global_goal_bearing_deg": float(previous.get("global_goal_bearing_deg", 0.0)),
            "goal_state": copy.deepcopy(previous.get("goal_state", {})),
            "waypoint": dict(previous["waypoint"]),
            "world_waypoint": dict(previous["world_waypoint"]),
            "applied": dict(previous["applied"]),
            "requested": dict(previous["requested"]),
            "status": str(previous["status"]),
            "delta_local_right_m": float(previous["delta_local_right_m"]),
            "delta_local_forward_m": float(previous["delta_local_forward_m"]),
            "delta_yaw_deg": float(previous["delta_yaw_deg"]),
            "safety_override": str(previous["safety_override"]),
            "reasoning_summary": str(previous["reasoning_summary"]),
            "action_text": str(previous["action_text"]),
            "front_clearance_before_m": previous["front_clearance_before_m"],
            "front_clearance_after_m": previous["front_clearance_after_m"],
            "obstacle_memory_before": copy.deepcopy(previous["obstacle_memory_before"]),
            "obstacle_memory_after": copy.deepcopy(previous["obstacle_memory_after"]),
            "map_memory_summary": copy.deepcopy(previous["map_memory_summary"]),
            "planner_hint": copy.deepcopy(previous["planner_hint"]),
            "route_plan": copy.deepcopy(previous.get("route_plan", {})),
            "pose_diagnostics": copy.deepcopy(previous.get("pose_diagnostics", {})),
        }

    def clone_previous_step_contexts(self) -> List[Dict[str, object]]:
        if not self.previous_step_contexts:
            return []

        cloned: List[Dict[str, object]] = []
        for previous in list(self.previous_step_contexts):
            cloned.append(
                {
                    "rgb_bgr": previous["rgb_bgr"].copy(),
                    "depth_vis": previous["depth_vis"].copy(),
                    "bev_img": previous["bev_img"].copy(),
                    "pose": Pose2D(previous["pose"].stamp, previous["pose"].x, previous["pose"].y, previous["pose"].yaw),
                    "goal_local_right": float(previous["goal_local_right"]),
                    "goal_local_forward": float(previous["goal_local_forward"]),
                    "goal_distance": float(previous["goal_distance"]),
                    "goal_bearing_deg": float(previous["goal_bearing_deg"]),
                    "global_goal_right": float(previous.get("global_goal_right", 0.0)),
                    "global_goal_forward": float(previous.get("global_goal_forward", 0.0)),
                    "global_goal_distance": float(previous.get("global_goal_distance", 0.0)),
                    "global_goal_bearing_deg": float(previous.get("global_goal_bearing_deg", 0.0)),
                    "goal_state": copy.deepcopy(previous.get("goal_state", {})),
                    "waypoint": dict(previous["waypoint"]),
                    "world_waypoint": dict(previous["world_waypoint"]),
                    "applied": dict(previous["applied"]),
                    "requested": dict(previous["requested"]),
                    "status": str(previous["status"]),
                    "delta_local_right_m": float(previous["delta_local_right_m"]),
                    "delta_local_forward_m": float(previous["delta_local_forward_m"]),
                    "delta_yaw_deg": float(previous["delta_yaw_deg"]),
                    "safety_override": str(previous["safety_override"]),
                    "reasoning_summary": str(previous["reasoning_summary"]),
                    "action_text": str(previous["action_text"]),
                    "front_clearance_before_m": previous["front_clearance_before_m"],
                    "front_clearance_after_m": previous["front_clearance_after_m"],
                    "obstacle_memory_before": copy.deepcopy(previous["obstacle_memory_before"]),
                    "obstacle_memory_after": copy.deepcopy(previous["obstacle_memory_after"]),
                    "map_memory_summary": copy.deepcopy(previous["map_memory_summary"]),
                    "planner_hint": copy.deepcopy(previous["planner_hint"]),
                    "route_plan": copy.deepcopy(previous.get("route_plan", {})),
                    "pose_diagnostics": copy.deepcopy(previous.get("pose_diagnostics", {})),
                }
            )
        return cloned

    def capture_snapshot(self) -> Optional[PerceptionSnapshot]:
        fresh, stale_info = self.data_is_fresh()
        if not fresh or self.current_pose is None:
            return None
        if self.rgb_bgr is None or self.depth_vis is None:
            return None

        bev_img = self.build_bev()
        obstacle_metrics = self.analyze_obstacles()
        self.last_obstacle_metrics = obstacle_metrics
        pose = self.current_pose
        self.update_world_obstacle_memory(pose)
        map_memory_summary = self.build_map_memory_summary(pose)
        global_goal_right, global_goal_forward, global_goal_distance, global_goal_bearing_deg = self.compute_global_goal_local(pose)
        force_rotate_mode = self.should_force_heading_alignment(global_goal_forward, global_goal_bearing_deg)
        planner_hint = self.build_planner_hint(
            pose,
            goal_right=global_goal_right,
            goal_forward=global_goal_forward,
            goal_distance=global_goal_distance,
            obstacle_metrics=obstacle_metrics,
            force_rotate_mode=force_rotate_mode,
        )
        route_plan = self.update_route_plan_state(
            pose,
            (global_goal_right, global_goal_forward, global_goal_distance, global_goal_bearing_deg),
            obstacle_metrics,
            planner_hint,
        )
        if route_plan.get("active") and planner_hint.get("commitment_source") != "wall-route-plan" and not force_rotate_mode:
            planner_hint = self.build_planner_hint(
                pose,
                goal_right=global_goal_right,
                goal_forward=global_goal_forward,
                goal_distance=global_goal_distance,
                obstacle_metrics=obstacle_metrics,
                force_rotate_mode=force_rotate_mode,
            )
        goal_state = self.update_goal_state(pose, obstacle_metrics, planner_hint, force_rotate_mode)
        pose_diagnostics = self.build_pose_diagnostics()

        return PerceptionSnapshot(
            capture_time=time.time(),
            step_index=self.step_counter + 1,
            rgb_bgr=self.rgb_bgr.copy(),
            depth_vis=self.depth_vis.copy(),
            bev_img=bev_img.copy(),
            pose=Pose2D(pose.stamp, pose.x, pose.y, pose.yaw),
            goal_local_right=float(goal_state["local_right_m"]),
            goal_local_forward=float(goal_state["local_forward_m"]),
            goal_distance=float(goal_state["local_distance_m"]),
            goal_bearing_deg=float(goal_state["local_bearing_deg"]),
            global_goal_right=global_goal_right,
            global_goal_forward=global_goal_forward,
            global_goal_distance=global_goal_distance,
            global_goal_bearing_deg=global_goal_bearing_deg,
            goal_state=goal_state,
            obstacle_metrics=obstacle_metrics,
            map_memory_summary=map_memory_summary,
            planner_hint=planner_hint,
            route_plan=route_plan,
            pose_diagnostics=pose_diagnostics,
            history_summary=self.build_history_summary(),
            stale_info=stale_info,
            previous_step=self.clone_previous_step_context(),
            previous_steps=self.clone_previous_step_contexts(),
        )

    def encode_image_for_api(self, image: np.ndarray, max_edge: int = 640) -> str:
        height, width = image.shape[:2]
        scale = min(1.0, float(max_edge) / float(max(height, width)))
        if scale < 1.0:
            resized = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        else:
            resized = image
        ok, buffer = cv2.imencode(".png", resized)
        if not ok:
            raise RuntimeError("failed to encode image for api")
        encoded = base64.b64encode(buffer.tobytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def build_prompt_text(self, snapshot: PerceptionSnapshot) -> str:
        sectors = snapshot.obstacle_metrics.get("sectors", {})
        corridor = snapshot.obstacle_metrics.get("corridor", {})
        map_memory = snapshot.map_memory_summary
        planner_hint = snapshot.planner_hint
        route_plan = snapshot.route_plan
        sector_lines = []
        for name in ("left", "center", "right"):
            info = sectors.get(name, {})
            sector_lines.append(
                f"- {name}: label={info.get('label', 'unknown')}, "
                f"count={info.get('count', 0)}, "
                f"min_distance_m={info.get('min_distance_m')}"
            )
        corridor_lines = [
            f"- corridor status={corridor.get('status')}, center_right_m={corridor.get('center_right_m')}, width_m={corridor.get('width_m')}",
            f"- side walls: left_x_m={corridor.get('left_wall_x_m')}, right_x_m={corridor.get('right_wall_x_m')}",
            f"- side clearance: left_m={corridor.get('left_clearance_m')}, right_m={corridor.get('right_clearance_m')}",
        ]
        memory_lines = [
            (
                f"- persistent memory: status={map_memory.get('status')}, "
                f"point_count={map_memory.get('point_count')}, "
                f"nearest_distance_m={map_memory.get('nearest_distance_m')}, "
                f"nearest_heading_deg={map_memory.get('nearest_heading_deg')}"
            ),
            f"- persistent front memory clearance m={map_memory.get('front_memory_clearance_m')}",
        ]
        memory_sectors = map_memory.get("sectors", {})
        for name in ("left", "center", "right"):
            info = memory_sectors.get(name, {})
            memory_lines.append(
                f"- persistent {name}: count={info.get('count', 0)}, min_distance_m={info.get('min_distance_m')}"
            )

        planner_lines = ["- none"]
        best_candidate = planner_hint.get("best", {})
        if best_candidate:
            planner_lines = [
                (
                    f"- best candidate={best_candidate.get('label')}, "
                    f"wp=[r={best_candidate.get('right_m')}, f={best_candidate.get('forward_m')}, s={best_candidate.get('speed_mps')}], "
                    f"clearance_m={best_candidate.get('min_clearance_m')}, blocked={best_candidate.get('blocked')}, score={best_candidate.get('score')}"
                ),
                (
                    f"- planner commitment sign={planner_hint.get('commitment_sign')}, "
                    f"source={planner_hint.get('commitment_source')}"
                ),
            ]
            for candidate in planner_hint.get("candidates", [])[:4]:
                planner_lines.append(
                    (
                        f"- candidate {candidate.get('label')}: "
                        f"wp=[r={candidate.get('right_m')}, f={candidate.get('forward_m')}, s={candidate.get('speed_mps')}], "
                        f"clearance_m={candidate.get('min_clearance_m')}, blocked={candidate.get('blocked')}, score={candidate.get('score')}"
                    )
                )

        route_plan_lines = [
            (
                f"- route plan: mode={route_plan.get('mode')}, side={route_plan.get('side')}, "
                f"active={route_plan.get('active')}, hold_remaining_steps={route_plan.get('hold_remaining_steps')}, "
                f"age_steps={route_plan.get('age_steps')}"
            ),
            f"- route plan reason={route_plan.get('reason')}",
        ]

        history_lines = []
        if snapshot.history_summary:
            for item in snapshot.history_summary[-HISTORY_WINDOW:]:
                waypoint = item.get("waypoint", {})
                history_lines.append(
                    f"- step={item['step_index']}, status={item['status']}, "
                    f"wp=[r={waypoint.get('right_m', 0.0):.2f}, f={waypoint.get('forward_m', 0.0):.2f}, s={waypoint.get('speed_mps', 0.0):.2f}], "
                    f"cmd=[{item['applied']['linear_mps']:.3f}, {item['applied']['angular_radps']:.3f}, {item['applied']['duration_s']:.3f}], "
                    f"delta_local=[right={item['delta_local_right_m']:.3f}, forward={item['delta_local_forward_m']:.3f}, yaw={item['delta_yaw_deg']:.1f}deg], "
                    f"safety={item['safety_override']}"
                )
        else:
            history_lines.append("- none")

        nearest_distance = snapshot.obstacle_metrics.get("nearest_distance_m")
        nearest_heading = snapshot.obstacle_metrics.get("nearest_heading_deg")
        front_clearance = snapshot.obstacle_metrics.get("front_clearance_m")
        stale = snapshot.stale_info
        pose_source = snapshot.stale_info.get("pose_source", self.args.pose_source)
        goal_state = snapshot.goal_state
        pose_diagnostics = snapshot.pose_diagnostics
        goal_region = goal_region_label(snapshot.goal_local_right, snapshot.goal_local_forward)
        steering_hint = steering_hint_text(snapshot.goal_local_right, snapshot.goal_local_forward)
        global_goal_region = goal_region_label(snapshot.global_goal_right, snapshot.global_goal_forward)
        global_steering_hint = steering_hint_text(snapshot.global_goal_right, snapshot.global_goal_forward)
        previous_step = snapshot.previous_step
        trajectory_lines = self.build_trajectory_tail_lines(snapshot.pose)
        previous_steps = snapshot.previous_steps
        queued_waypoint_lines = self.queued_waypoint_preview_lines(snapshot.pose)
        active_cmd = {"linear_mps": 0.0, "angular_radps": 0.0, "duration_s": 0.0}
        active_waypoint = {"right_m": 0.0, "forward_m": 0.0, "speed_mps": 0.0}
        if self.active_execution is not None:
            active_cmd = dict(self.active_execution.applied)
            active_waypoint = self.execution_waypoint_local(self.active_execution, snapshot.pose)
        pose_diag_lines = [
            f"- effective yaw source={pose_diagnostics.get('effective_yaw_source')}",
            f"- imu raw yaw deg={pose_diagnostics.get('imu_raw_yaw_deg')}, aligned={pose_diagnostics.get('imu_aligned_yaw_deg')}, integrated={pose_diagnostics.get('imu_integrated_yaw_deg')}",
            f"- cmd yaw estimate deg={pose_diagnostics.get('cmd_yaw_estimate_deg')}, odom yaw deg={pose_diagnostics.get('odom_yaw_deg')}",
            f"- yaw alignment offset deg={pose_diagnostics.get('yaw_alignment_offset_deg')}",
            f"- imu orientation vs integrated deg={pose_diagnostics.get('orientation_vs_integrated_deg')}",
            f"- effective yaw vs cmd deg={pose_diagnostics.get('effective_vs_cmd_deg')}, vs odom deg={pose_diagnostics.get('effective_vs_odom_deg')}",
            f"- dead reckoned distance m={pose_diagnostics.get('dead_reckoned_distance_m')}, turn_deg={pose_diagnostics.get('dead_reckoned_turn_deg')}",
            f"- pose warnings={pose_diagnostics.get('warnings') or ['none']}",
        ]

        previous_lines = ["- none"]
        if previous_steps:
            previous_lines = []
            for idx, step in enumerate(previous_steps[:PREVIOUS_CONTEXT_WINDOW], start=1):
                previous_waypoint = step.get("waypoint", {})
                previous_applied = step.get("applied", {})
                previous_before = step.get("obstacle_memory_before", {})
                previous_before_sectors = previous_before.get("sectors", {})
                previous_before_corridor = previous_before.get("corridor", {})
                previous_after = step.get("obstacle_memory_after", {})
                previous_lines.extend(
                    [
                        (
                            f"- prev#{idx} status={step.get('status')}, "
                            f"wp=[r={previous_waypoint.get('right_m', 0.0):.2f}, f={previous_waypoint.get('forward_m', 0.0):.2f}, s={previous_waypoint.get('speed_mps', 0.0):.2f}], "
                            f"cmd=[{previous_applied.get('linear_mps', 0.0):.3f}, {previous_applied.get('angular_radps', 0.0):.3f}, {previous_applied.get('duration_s', 0.0):.3f}]"
                        ),
                        (
                            f"- prev#{idx} obstacle before: nearest={previous_before.get('nearest_distance_m')}m @ {previous_before.get('nearest_heading_deg')}deg, "
                            f"front_clearance={previous_before.get('front_clearance_m')}, "
                            f"sectors L/C/R={previous_before_sectors.get('left', {}).get('label', 'n/a')}/"
                            f"{previous_before_sectors.get('center', {}).get('label', 'n/a')}/"
                            f"{previous_before_sectors.get('right', {}).get('label', 'n/a')}, "
                            f"corridor={previous_before_corridor.get('status')} ctr={previous_before_corridor.get('center_right_m')} "
                            f"width={previous_before_corridor.get('width_m')}"
                        ),
                        (
                            f"- prev#{idx} result delta_local=[right={step.get('delta_local_right_m', 0.0):.3f}, "
                            f"forward={step.get('delta_local_forward_m', 0.0):.3f}, "
                            f"yaw={step.get('delta_yaw_deg', 0.0):.1f}deg], "
                            f"front_clearance_after={previous_after.get('front_clearance_m')}"
                        ),
                    ]
                )
        elif previous_step is not None:
            previous_waypoint = previous_step.get("waypoint", {})
            previous_applied = previous_step.get("applied", {})
            previous_before = previous_step.get("obstacle_memory_before", {})
            previous_before_sectors = previous_before.get("sectors", {})
            previous_before_corridor = previous_before.get("corridor", {})
            previous_after = previous_step.get("obstacle_memory_after", {})
            previous_lines = [
                (
                    f"- previous step status={previous_step.get('status')}, "
                    f"wp=[r={previous_waypoint.get('right_m', 0.0):.2f}, f={previous_waypoint.get('forward_m', 0.0):.2f}, s={previous_waypoint.get('speed_mps', 0.0):.2f}], "
                    f"cmd=[{previous_applied.get('linear_mps', 0.0):.3f}, {previous_applied.get('angular_radps', 0.0):.3f}, {previous_applied.get('duration_s', 0.0):.3f}]"
                ),
                (
                    f"- previous obstacle before move: nearest={previous_before.get('nearest_distance_m')}m @ {previous_before.get('nearest_heading_deg')}deg, "
                    f"front_clearance={previous_before.get('front_clearance_m')}, "
                    f"sectors L/C/R={previous_before_sectors.get('left', {}).get('label', 'n/a')}/"
                    f"{previous_before_sectors.get('center', {}).get('label', 'n/a')}/"
                    f"{previous_before_sectors.get('right', {}).get('label', 'n/a')}, "
                    f"corridor={previous_before_corridor.get('status')} ctr={previous_before_corridor.get('center_right_m')} "
                    f"width={previous_before_corridor.get('width_m')}"
                ),
                (
                    f"- previous result delta_local=[right={previous_step.get('delta_local_right_m', 0.0):.3f}, "
                    f"forward={previous_step.get('delta_local_forward_m', 0.0):.3f}, "
                    f"yaw={previous_step.get('delta_yaw_deg', 0.0):.1f}deg], "
                    f"front_clearance_after={previous_after.get('front_clearance_m')}"
                ),
            ]

        return "\n".join(
            [
                "Current robot state",
                f"- control mode: {self.args.control_mode}",
                f"- pose source: {pose_source}",
                f"- yaw source: {snapshot.stale_info.get('yaw_source', self.args.yaw_source)}",
                f"- world pose: x={snapshot.pose.x:.3f}, y={snapshot.pose.y:.3f}, yaw_deg={math.degrees(snapshot.pose.yaw):.2f}",
                f"- goal frame: {self.args.goal_frame}",
                (
                    f"- goal input local: right={self.goal_input_x:.3f}, forward={self.goal_input_y:.3f}"
                    if self.args.goal_frame == "start_local"
                    else f"- goal input world: x={self.goal_input_x:.3f}, y={self.goal_input_y:.3f}"
                ),
                f"- global goal world: {self.goal_world_line(snapshot.pose)}",
                f"- global goal local: right={snapshot.global_goal_right:.3f}, forward={snapshot.global_goal_forward:.3f}, distance={snapshot.global_goal_distance:.3f}",
                f"- global goal region: {global_goal_region}",
                f"- global goal bearing signed_deg={snapshot.global_goal_bearing_deg:.2f}, abs_deg={abs(snapshot.global_goal_bearing_deg):.2f}",
                f"- global steering hint: {global_steering_hint}",
                f"- active local goal source={goal_state.get('local_source')}, mode={goal_state.get('local_mode')}, heading_alignment_active={goal_state.get('heading_alignment_active')}, reason={goal_state.get('local_reason')}",
                f"- active local goal world: x={goal_state.get('local_world_x')}, y={goal_state.get('local_world_y')}",
                f"- active local goal local: right={snapshot.goal_local_right:.3f}, forward={snapshot.goal_local_forward:.3f}, distance={snapshot.goal_distance:.3f}",
                f"- active local goal age steps={goal_state.get('local_age_steps')}, created_step={goal_state.get('local_created_step')}, updated_step={goal_state.get('local_updated_step')}",
                f"- start-local goal anchor ready: {snapshot.stale_info.get('goal_anchor_ready')}",
                f"- active local goal region: {goal_region}",
                f"- active local goal bearing signed_deg={snapshot.goal_bearing_deg:.2f}, abs_deg={abs(snapshot.goal_bearing_deg):.2f}",
                f"- active local steering hint: {steering_hint}",
                f"- current waypoint: right={active_waypoint['right_m']:.3f}, forward={active_waypoint['forward_m']:.3f}, speed={active_waypoint['speed_mps']:.3f}",
                f"- current executing cmd: [{active_cmd['linear_mps']:.3f}, {active_cmd['angular_radps']:.3f}, {active_cmd['duration_s']:.3f}]",
                f"- {self.pose_source_text()}",
                f"- robot_radius_m={self.args.robot_radius}",
                f"- body_safety_buffer_m={self.args.body_safety_buffer}",
                f"- queued waypoint count: {len(self.execution_queue)}",
                "",
                "Pose integration diagnostics",
                *pose_diag_lines,
                "",
                "Obstacle summary",
                f"- nearest obstacle distance_m={nearest_distance}, heading_deg={nearest_heading}",
                f"- front clearance m={front_clearance}",
                f"- desired obstacle clearance m={self.args.desired_clearance}",
                f"- floor filter mode={snapshot.obstacle_metrics.get('floor_mode')}",
                f"- obstacle point count={snapshot.obstacle_metrics.get('point_count')}",
                *sector_lines,
                *corridor_lines,
                "",
                "Persistent obstacle memory in current local frame",
                *memory_lines,
                "",
                "Deterministic planner hint from remembered obstacles",
                *planner_lines,
                "",
                "Persistent route plan state",
                *route_plan_lines,
                "",
                "Queued waypoint stream in current local frame",
                *queued_waypoint_lines,
                "",
                "Recent trajectory tail in current local frame",
                *trajectory_lines,
                "",
                "Previous-step obstacle memory",
                *previous_lines,
                "",
                "Recent command execution history",
                *history_lines,
                "",
                "Action policy",
                "- Use recent history only as background diagnostics.",
                (
                    "- DIRECT CMD MODE: linear_mps/angular_radps/duration_s will be executed directly after hard safety clipping. waypoint_* is diagnostic only. Prefer smooth continuous forward arcs and do not oscillate turn direction unless red BEV obstacles clearly require it."
                    if self.args.control_mode == "direct_cmd_vel"
                    else "- WAYPOINT MODE: waypoint_* is the primary target. Concentrate on choosing a safe point in free space first; the controller converts that point to cmd_vel."
                ),
                "- In waypoint mode, linear_mps/angular_radps are only secondary hints. The point geometry matters more than the raw command.",
                "- PRIORITIZE RED BEV OBSTACLES FIRST. RGB and depth are secondary references and must not override red obstacle geometry in BEV.",
                "- Filled red shadowed regions behind red points in BEV must also be treated as blocked or unknown wall continuation, not as free space.",
                "- The provided global goal is the ultimate destination, not the next local target to greedily chase right now.",
                "- The provided active local goal is the current short-horizon subgoal. Use it for immediate steering, but keep it consistent with the global goal and safe corridor continuation.",
                "- If route plan mode is startup-explore, the robot is still orienting itself. Use a short graceful exploratory move or slight scan turn toward the remembered open side before committing to a long detour.",
                "- If route plan mode is around_wall, keep following that detour side until the corridor clearly opens up. Do not greedily cut back toward the goal just because one frame looks slightly better.",
                "- Treat route plan mode around_wall as a short-horizon global detour commitment around an impassable wall, not as a one-frame suggestion.",
                "- If the current corridor choice is still safe and continues well, preserve it. Do not replace a good route with a different route unless the new route is clearly safer or clearly improves continuation.",
                "- Avoid naive replanning. Small perception changes should usually cause small route updates, not a different corridor choice.",
                "- If the global goal is behind, do not force a rigid rotate-only maneuver. Prefer short-term memory, a slight scan turn, or a remembered around-wall detour if that gives a cleaner continuation.",
                "- Locally, prioritize staying in the safer corridor with better continuation even if that temporarily reduces or delays immediate progress toward the global goal.",
                "- Use the recent trajectory tail to avoid undoing a good corridor choice or oscillating left-right across the same passage.",
                "- First imagine a short 2-point path fragment through free space. Output only the first point, but choose it so the second step stays feasible.",
                "- If the corridor is wide and red BEV obstacles are not close, drive decisively. Prefer faster sustained motion over timid crawling.",
                "- Use more of the allowed max_linear and max_duration when the route is open.",
                "- Only slow down when red BEV obstacles, narrow side clearance, or a large heading change clearly require it.",
                "- If one side wall gets too close, do not merely skim it. Steer away decisively with a stronger escape arc.",
                "- desired_clearance_m is clearance from the robot body, not from a point centerline. Account for robot_radius_m in every path choice.",
                "- A point is invalid if the robot body tube from robot origin to that point would pass too close to red dots or side walls.",
                "- YOU MUST STRICTLY AVOID TO COLLIDE TO RED DOTS IN BEV VIEW. IMAGE AND DEPTH IS JUST FOR REFERENCE. DO NOT GET CLOSER TO RED OBSTACLES!!",
                "- Base the next action on the current images and the active local goal values. Use the separate global goal as long-horizon context.",
                "- Also use the persistent obstacle memory and planner hint. Obstacles remembered there still matter even if they are less visible now.",
                "- If the planner commitment says keep the current detour side, do not flip left/right unless the opposite side is clearly safer by a meaningful margin.",
                "- GO THROUGH EMPTY FREE SPACE ONLY. Do not skim red dots and do not aim for space hidden behind red dots.",
                "- If the straight segment from the robot to the waypoint goes near red dots, that waypoint is invalid and must be rejected.",
                "- If the direct point toward goal hugs a wall, reject it and choose the safer corridor-center or escape-side point first.",
                "- Compare at least these candidate path types before deciding: direct, left detour, right detour.",
                "- Do not greedily choose the closest heading to the goal if a wider and safer detour exists.",
                "- Evaluate whether the chosen waypoint still leaves a good next step through the corridor. Do not pick a waypoint that immediately creates a dead end or wall trap.",
                "- Prefer the route whose worst-case clearance to red obstacles is larger, even if that route is longer.",
                "- Use remembered obstacles to imagine how the corridor continues beyond the current camera frame, and keep the waypoint in the safer route through that corridor.",
                "- Prefer a 2-step-feasible route over a 1-step greedy shortcut.",
                "- Treat the next output as a waypoint update that should connect smoothly to the existing queued path, not as an isolated stop-start segment.",
                "- Also use previous-step obstacle memory because a turn can move a close obstacle outside the current camera FOV without removing the obstacle.",
                "- Treat the previous BEV as short-term obstacle memory; do not assume an obstacle is gone only because it is less visible after a turn.",
                "- If the previous step detoured around a close obstacle or wall, do not immediately undo that detour unless current and previous evidence together show a better corridor.",
                "- Use active goal_local_right as the source of truth for immediate left vs right.",
                "- If active goal_local_right > 0, turning toward the active local goal means w < 0.",
                "- If active goal_local_right < 0, turning toward the active local goal means w > 0.",
                "- Do not infer left/right from generic signed-angle conventions.",
                "- First choose a calm local waypoint, then choose cmd_vel that smoothly tracks it.",
                "- If current goal_local changes after rotation, follow the updated current values immediately.",
                "- If the goal is ahead and nearly centered, prefer forward progress over in-place rotation.",
                "- If front clearance is already comfortable and current forward motion is safe, maintain that forward progress.",
                "- Keep rotation cautious: prefer small steering corrections before strong turn rates.",
                "- If a safe forward arc exists, prefer keeping motion continuous instead of stopping between steps.",
                "- If center is tight but one side has more room, choose forward motion with steering to bypass the obstacle.",
                "- Try to maintain about the requested obstacle clearance while passing obstacles.",
                "- Red BEV points are impassable obstacles. Do not put a waypoint through them just because the area behind them looks open.",
                "- If a solid wall blocks progress and no safe direct waypoint exists, switch to exploration: rotate or probe the more open side to discover a new corridor instead of repeatedly stopping.",
                "- Small scan turns are allowed when a wall blocks direct progress and short-term visual memory suggests a better continuation may appear. Keep those scan turns deliberate and coherent with the remembered route.",
                "- If front progress is blocked by a wall and the robot is too close to that wall, briefly reverse to create clearance before the next turn.",
                "- Behave like a short-horizon path planner, not a greedy target follower.",
                "- Reject short forward waypoints that only creep toward nearby red obstacles. Prefer a wider detour waypoint or a short exploratory turn instead.",
                "- When the corridor ahead is clear, prefer a waypoint horizon around 1 to 2 meters so the robot moves decisively.",
                "- Choose the waypoint through the safer middle of the visible corridor, not tight to a wall.",
                "- Prefer the center of empty space, not the edge of empty space.",
                "- If one side wall is close, move the waypoint away from that wall before converting to cmd_vel.",
                "- Prefer a waypoint with better side clearance even if it is a little less direct to the goal.",
                "- A longer safe waypoint through remembered free space is better than a shorter waypoint that narrows toward remembered walls.",
                "- Use queued waypoints as a continuous path memory. Extend that stream smoothly instead of resetting it every query.",
                "- Use previous BEV and recent RGB images as short-term exploration memory when deciding how to go around a wall.",
                "- Use ACTION: [0, 0, 0] only for imminent collision, persistent stale perception, or goal reached.",
                "- When safe, prefer multi-second commands over short stop-and-go actions.",
                "- Reserve full stop for unsafe, stale, or goal-reached cases.",
                "",
                "Safety caps",
                f"- max_linear_mps={self.args.max_linear}",
                f"- max_angular_radps={self.args.max_angular}",
                f"- max_duration_s={self.args.max_duration}",
                f"- prefer_duration_at_least_s={self.args.min_motion_duration}",
                f"- max_linear_step_per_update={self.args.max_linear_step}",
                f"- max_angular_step_per_update={self.args.max_angular_step}",
                f"- robot_radius_m={self.args.robot_radius}",
                f"- body_safety_buffer_m={self.args.body_safety_buffer}",
                f"- desired_clearance_m={self.args.desired_clearance}",
                f"- min_front_clearance_m={self.args.min_front_clearance}",
                f"- stale_timeout_s={self.args.stale_timeout}",
                "",
                "Freshness",
                f"- rgb_age_s={stale.get('rgb_age_s')}",
                f"- depth_age_s={stale.get('depth_age_s')}",
                f"- odom_age_s={stale.get('odom_age_s')}",
                f"- imu_age_s={stale.get('imu_age_s')}",
                "",
                "Interpretation notes",
                "- The BEV is already aligned to the robot's current heading and origin.",
                "- Up in BEV is forward, right in BEV is robot-right.",
                "- Positive angular velocity means left turn. Negative angular velocity means right turn.",
                "- Example: goal_local_right=+2.0 and goal_local_forward=+6.0 means ahead-right, so a turning command should have w < 0.",
                "- Example: goal_local_right=-2.0 and goal_local_forward=+6.0 means ahead-left, so a turning command should have w > 0.",
                "- Return a cautious single action only.",
            ]
        )

    def build_compact_prompt_text(self, snapshot: PerceptionSnapshot) -> str:
        corridor = snapshot.obstacle_metrics.get("corridor", {})
        sectors = snapshot.obstacle_metrics.get("sectors", {})
        map_memory = snapshot.map_memory_summary
        planner_best = snapshot.planner_hint.get("best", {})
        route_plan = snapshot.route_plan
        goal_state = snapshot.goal_state
        pose_diagnostics = snapshot.pose_diagnostics
        previous_summaries: List[str] = []
        for idx, step in enumerate(snapshot.previous_steps[:PREVIOUS_CONTEXT_WINDOW], start=1):
            previous_summaries.append(
                f"prev{idx} status={step.get('status')} "
                f"wp=[r={step.get('waypoint', {}).get('right_m', 0.0):.2f}, "
                f"f={step.get('waypoint', {}).get('forward_m', 0.0):.2f}] "
                f"delta=[r={step.get('delta_local_right_m', 0.0):.2f}, "
                f"f={step.get('delta_local_forward_m', 0.0):.2f}, "
                f"yaw={step.get('delta_yaw_deg', 0.0):.1f}deg]"
            )
        if not previous_summaries and snapshot.previous_step is not None:
            previous_step = snapshot.previous_step
            previous_summaries.append(
                f"prev1 status={previous_step.get('status')} "
                f"wp=[r={previous_step.get('waypoint', {}).get('right_m', 0.0):.2f}, "
                f"f={previous_step.get('waypoint', {}).get('forward_m', 0.0):.2f}] "
                f"delta=[r={previous_step.get('delta_local_right_m', 0.0):.2f}, "
                f"f={previous_step.get('delta_local_forward_m', 0.0):.2f}, "
                f"yaw={previous_step.get('delta_yaw_deg', 0.0):.1f}deg]"
            )
        previous_summary = " | ".join(previous_summaries) if previous_summaries else "none"
        trajectory_summary = " | ".join(self.build_trajectory_tail_lines(snapshot.pose, limit=5))

        return "\n".join(
            [
                "Compact planning state",
                f"control_mode={self.args.control_mode}",
                f"active_local_goal right={snapshot.goal_local_right:.3f} forward={snapshot.goal_local_forward:.3f} distance={snapshot.goal_distance:.3f} bearing_deg={snapshot.goal_bearing_deg:.2f}",
                f"global_goal right={snapshot.global_goal_right:.3f} forward={snapshot.global_goal_forward:.3f} distance={snapshot.global_goal_distance:.3f} bearing_deg={snapshot.global_goal_bearing_deg:.2f}",
                f"local_goal_source={goal_state.get('local_source')} local_goal_mode={goal_state.get('local_mode')} heading_alignment_active={goal_state.get('heading_alignment_active')} local_goal_reason={goal_state.get('local_reason')}",
                f"local_goal_world=({goal_state.get('local_world_x')}, {goal_state.get('local_world_y')}) age_steps={goal_state.get('local_age_steps')}",
                f"goal_anchor_ready={snapshot.stale_info.get('goal_anchor_ready')}",
                f"robot_radius={self.args.robot_radius} body_buffer={self.args.body_safety_buffer} desired_clearance={self.args.desired_clearance}",
                f"yaw_source_used={pose_diagnostics.get('effective_yaw_source')} imu_vs_integrated_deg={pose_diagnostics.get('orientation_vs_integrated_deg')} effective_vs_cmd_deg={pose_diagnostics.get('effective_vs_cmd_deg')}",
                f"front_clearance={snapshot.obstacle_metrics.get('front_clearance_m')} nearest={snapshot.obstacle_metrics.get('nearest_distance_m')}@{snapshot.obstacle_metrics.get('nearest_heading_deg')}",
                f"sector_labels left={sectors.get('left', {}).get('label')} center={sectors.get('center', {}).get('label')} right={sectors.get('right', {}).get('label')}",
                f"corridor status={corridor.get('status')} center_right={corridor.get('center_right_m')} width={corridor.get('width_m')}",
                f"memory front_clearance={map_memory.get('front_memory_clearance_m')} count={map_memory.get('point_count')}",
                f"route_plan mode={route_plan.get('mode')} side={route_plan.get('side')} active={route_plan.get('active')} hold_remaining={route_plan.get('hold_remaining_steps')} reason={route_plan.get('reason')}",
                (
                    f"planner_best label={planner_best.get('label')} "
                    f"wp=[r={planner_best.get('right_m')}, f={planner_best.get('forward_m')}, s={planner_best.get('speed_mps')}] "
                    f"clearance={planner_best.get('min_clearance_m')} blocked={planner_best.get('blocked')}"
                    if planner_best
                    else "planner_best none"
                ),
                f"prev_step {previous_summary}",
                f"trajectory_tail {trajectory_summary}",
                "Rules:",
                "- Avoid red dots absolutely. Use remembered obstacles too.",
                "- Prioritize red BEV obstacle geometry over RGB/depth cues.",
                "- Treat filled red shadow regions behind red points in BEV as blocked or unknown wall continuation.",
                (
                "- In direct_cmd_vel mode, cmd_vel is the source of truth. Keep commands smooth and continuous, and avoid left-right twitch unless BEV obstacles clearly force it. waypoint is only advisory."
                    if self.args.control_mode == "direct_cmd_vel"
                    else "- Pick one safe local waypoint first; cmd_vel is derived from that point and is secondary."
                ),
                "- Behave like an agent: observe, choose intent, commit briefly, act, then review. Scanning left or right is a valid deliberate action.",
                "- If front and side clearance are comfortable, use a brisk sustained speed instead of slow crawling.",
                "- Prefer using more of max_linear and max_duration when the corridor is clearly open.",
                "- Prefer free corridor center and safer detours over greedy heading to the global goal.",
                "- Use the active local goal for immediate motion and the global goal for long-horizon direction.",
                "- If route_plan mode is startup-explore, begin with a short exploratory move or slight scan turn toward the more promising side instead of forcing direct goal progress immediately.",
                "- If route_plan mode is around_wall, continue that detour side until the corridor really opens. Do not greedily cut back toward the goal.",
                "- Preserve a good route if it is still safe. Route changes should be deliberate, not reactive to small frame-to-frame noise.",
                "- Prefer continuity of corridor choice and path shape. Only switch to a new route when it is materially safer or offers clearly better continuation.",
                "- If the global goal is behind, do not freeze into a hard rotate-only policy. Prefer slight scan turns and remembered-corridor detours that can reveal a better continuation.",
                "- Do not greedily optimize immediate reduction of the global goal if that harms corridor continuation.",
                "- Use the recent trajectory tail to avoid immediately undoing a corridor choice that was working.",
                "- Think 1 to 2 steps ahead and avoid greedy shortcuts that likely force a stop, reversal, or wall-hugging next.",
                "- desired_clearance is from the robot body; include robot_radius in your path fit judgment.",
                "- Reject any point whose robot-body path would hug a wall or red dots; choose corridor-center or escape-side points first.",
                "- If blocked close to a wall, a short reverse-then-turn recovery is better than repeated stop-turn in place.",
                "- Use recent BEV and recent RGB history as short-term exploration memory when deciding how to go around a wall.",
                "- Keep JSON short and fill schema only.",
            ]
        )

    def build_api_content(
        self,
        snapshot: PerceptionSnapshot,
        *,
        compact: bool,
        include_previous_bev: bool,
    ) -> Tuple[List[Dict[str, object]], str, List[str]]:
        rgb_uri = self.encode_image_for_api(snapshot.rgb_bgr)
        depth_uri = self.encode_image_for_api(snapshot.depth_vis)
        bev_uri = self.encode_image_for_api(snapshot.bev_img)
        prompt_text = self.build_compact_prompt_text(snapshot) if compact else self.build_prompt_text(snapshot)
        debug_image_notes = [
            "Current RGB image attached",
            "Current depth visualization attached",
            "Current BEV image attached",
        ]
        content: List[Dict[str, object]] = [
            {"type": "input_text", "text": prompt_text},
            {"type": "input_text", "text": "Current RGB image"},
            {"type": "input_image", "image_url": rgb_uri, "detail": "auto"},
            {"type": "input_text", "text": "Current depth visualization"},
            {"type": "input_image", "image_url": depth_uri, "detail": "auto"},
            {"type": "input_text", "text": "Current BEV image"},
            {"type": "input_image", "image_url": bev_uri, "detail": "auto"},
        ]

        if include_previous_bev:
            previous_steps = snapshot.previous_steps[:PREVIOUS_BEV_IMAGE_WINDOW]
            if not previous_steps and snapshot.previous_step is not None:
                previous_steps = [snapshot.previous_step]
            for idx, previous_step in enumerate(previous_steps, start=1):
                previous_bev_uri = self.encode_image_for_api(previous_step["bev_img"])
                content.extend(
                    [
                        {
                            "type": "input_text",
                            "text": (
                                f"Previous-step BEV image #{idx}, captured before an earlier executed command. "
                                "Use it as short-term obstacle memory. Obstacles may be less visible now only because the robot turned or moved."
                            ),
                        },
                        {"type": "input_image", "image_url": previous_bev_uri, "detail": "auto"},
                    ]
                )
                debug_image_notes.append(f"Previous-step BEV image #{idx} attached")
                if idx <= PREVIOUS_RGB_IMAGE_WINDOW:
                    previous_rgb_uri = self.encode_image_for_api(previous_step["rgb_bgr"])
                    content.extend(
                        [
                            {
                                "type": "input_text",
                                "text": (
                                    f"Previous-step RGB image #{idx}, captured during recent motion. "
                                    "Use it as short-term visual exploration memory for corridor shape, openings, and wall-following context."
                                ),
                            },
                            {"type": "input_image", "image_url": previous_rgb_uri, "detail": "auto"},
                        ]
                    )
                    debug_image_notes.append(f"Previous-step RGB image #{idx} attached")
        return content, prompt_text, debug_image_notes

    def request_drive_command(self, snapshot: PerceptionSnapshot) -> Dict[str, object]:
        configured_effort = self.args.reasoning_effort
        if configured_effort == "minimal":
            configured_effort = "none"

        attempts = [
            {
                "label": "primary",
                "reasoning_effort": configured_effort,
                "max_output_tokens": max(400, int(self.args.api_max_output_tokens)),
                "include_previous_bev": True,
                "compact_prompt": False,
            },
            {
                "label": "retry_more_budget",
                "reasoning_effort": "none",
                "max_output_tokens": max(700, int(self.args.api_max_output_tokens) * 2),
                "include_previous_bev": False,
                "compact_prompt": False,
            },
            {
                "label": "retry_compact",
                "reasoning_effort": "none",
                "max_output_tokens": max(900, int(self.args.api_max_output_tokens) * 3),
                "include_previous_bev": False,
                "compact_prompt": True,
            },
        ]

        errors: List[str] = []
        for attempt in attempts:
            content, prompt_text, prompt_image_notes = self.build_api_content(
                snapshot,
                compact=bool(attempt["compact_prompt"]),
                include_previous_bev=bool(attempt["include_previous_bev"]),
            )
            try:
                response = self.openai_client.responses.parse(
                    model=self.args.model,
                    instructions=SYSTEM_PROMPT,
                    input=[
                        {
                            "type": "message",
                            "role": "user",
                            "content": content,
                        }
                    ],
                    text_format=DriveCommand,
                    reasoning={"effort": str(attempt["reasoning_effort"])},
                    max_output_tokens=int(attempt["max_output_tokens"]),
                    text={"verbosity": "low"},
                    store=False,
                    timeout=self.args.api_timeout,
                )

                parsed = response.output_parsed
                if parsed is None:
                    status = getattr(response, "status", None)
                    incomplete_details = getattr(response, "incomplete_details", None)
                    output_types = [item.type for item in getattr(response, "output", [])]
                    error_text = (
                        "openai response did not match the drive command schema "
                        f"(attempt={attempt['label']}, status={status}, incomplete={incomplete_details}, "
                        f"output_types={output_types}, output_text={response.output_text!r})"
                    )
                    errors.append(error_text)
                    continue

                return {
                    "parsed": parsed.model_dump(),
                    "raw_output_text": response.output_text,
                    "response": {
                        "id": getattr(response, "id", None),
                        "model": getattr(response, "model", None),
                        "status": getattr(response, "status", None),
                        "attempt": attempt["label"],
                        "reasoning_effort": attempt["reasoning_effort"],
                        "max_output_tokens": attempt["max_output_tokens"],
                        "output_text": response.output_text,
                        "output_types": [getattr(item, "type", type(item).__name__) for item in getattr(response, "output", [])],
                        "incomplete_details": str(getattr(response, "incomplete_details", None)),
                    },
                    "usage": response.usage.model_dump(mode="json") if response.usage is not None else None,
                    "prompt_debug": {
                        "attempt": attempt["label"],
                        "compact_prompt": bool(attempt["compact_prompt"]),
                        "include_previous_bev": bool(attempt["include_previous_bev"]),
                        "prompt_text": prompt_text,
                        "image_notes": prompt_image_notes,
                        "system_prompt": SYSTEM_PROMPT,
                    },
                }
            except Exception as exc:
                errors.append(f"attempt={attempt['label']}: {exc}")

        raise RuntimeError(" | ".join(errors))

    def sector_rotation_bias(self, sectors: Dict[str, object]) -> float:
        left = sectors.get("left", {})
        right = sectors.get("right", {})
        left_score = left.get("min_distance_m")
        right_score = right.get("min_distance_m")
        if left_score is None and right_score is None:
            return 0.0
        if left_score is None:
            return 1.0
        if right_score is None:
            return -1.0
        if float(left_score) > float(right_score):
            return 1.0
        if float(right_score) > float(left_score):
            return -1.0
        return 0.0

    def sector_min_distance(self, sectors: Dict[str, object], name: str) -> Optional[float]:
        info = sectors.get(name, {})
        value = info.get("min_distance_m")
        if value is None:
            return None
        return float(value)

    def should_allow_turn_away_from_goal(
        self,
        desired_turn_sign: float,
        sectors: Dict[str, object],
        front_clearance: Optional[float],
    ) -> bool:
        if desired_turn_sign == 0.0:
            return True
        if front_clearance is None or float(front_clearance) > (self.args.min_front_clearance + 0.25):
            return False

        desired_sector = "left" if desired_turn_sign > 0.0 else "right"
        opposite_sector = "right" if desired_turn_sign > 0.0 else "left"
        desired_clearance = self.sector_min_distance(sectors, desired_sector)
        opposite_clearance = self.sector_min_distance(sectors, opposite_sector)

        if desired_clearance is None:
            return True
        if opposite_clearance is None:
            return False
        return opposite_clearance > (desired_clearance + 0.6)

    def choose_bootstrap_command(self, obstacle_metrics: Dict[str, object]) -> Tuple[Dict[str, float], str]:
        sectors = obstacle_metrics.get("sectors", {})
        front_clearance = obstacle_metrics.get("front_clearance_m")
        rotation_bias = self.sector_rotation_bias(sectors)
        if rotation_bias == 0.0:
            rotation_bias = 1.0 if (self.bootstrap_cycle_index % 2) == 0 else -1.0

        if front_clearance is not None and float(front_clearance) < self.args.min_front_clearance:
            return (
                {
                    "linear_mps": 0.0,
                    "angular_radps": 0.45 * rotation_bias,
                    "duration_s": 0.8,
                },
                "bootstrap rotate because front clearance is blocked while waiting for /rtabmap/odom",
            )

        phase = self.bootstrap_cycle_index % 6
        if phase in (0, 1, 2, 3):
            direction = 1.0 if phase in (0, 1) else -1.0
            return (
                {
                    "linear_mps": 0.0,
                    "angular_radps": 0.45 * direction,
                    "duration_s": 0.8,
                },
                "bootstrap scan rotation while waiting for /rtabmap/odom",
            )

        if front_clearance is None or float(front_clearance) > max(self.args.min_front_clearance + 0.4, 1.0):
            return (
                {
                    "linear_mps": min(0.08, self.args.max_linear),
                    "angular_radps": 0.0,
                    "duration_s": min(0.6, self.args.max_duration),
                },
                "bootstrap creep forward for visual parallax while waiting for /rtabmap/odom",
            )

        return (
            {
                "linear_mps": 0.0,
                "angular_radps": 0.45 * rotation_bias,
                "duration_s": 0.8,
            },
            "bootstrap rotate because forward motion is not safe while waiting for /rtabmap/odom",
        )

    def maybe_start_bootstrap_localization(self):
        if self.args.pose_source != "odom":
            return
        if not self.auto_enabled:
            return
        if self.bootstrap_active is not None or self.active_execution is not None or self.pending_future is not None:
            return
        if self.current_pose is not None:
            return

        ready, _ = self.perception_ready_without_odom()
        if not ready:
            self.api_status = "waiting-localization"
            self.last_error = "waiting for rgb/depth/camera info and /rtabmap/odom"
            return

        obstacle_metrics = self.analyze_obstacles()
        self.last_obstacle_metrics = obstacle_metrics
        applied, reason = self.choose_bootstrap_command(obstacle_metrics)
        now = time.monotonic()
        self.bootstrap_active = BootstrapState(
            applied=applied,
            reason=reason,
            start_monotonic=now,
            end_monotonic=now + float(applied["duration_s"]),
            cycle_index=self.bootstrap_cycle_index,
        )
        self.bootstrap_cycle_index += 1
        self.api_status = "bootstrap-localization"
        self.latest_reasoning = reason
        self.latest_risk = "bootstrap"
        self.latest_action_text = (
            f"ACTION: [{applied['linear_mps']:.3f}, {applied['angular_radps']:.3f}, {applied['duration_s']:.3f}]"
        )
        self.last_error = "no /rtabmap/odom yet; running localization bootstrap motion"
        self.log_step_event(
            {
                "kind": "bootstrap",
                "timestamp": time.time(),
                "cycle_index": self.bootstrap_active.cycle_index,
                "applied": applied,
                "reason": reason,
                "obstacle_metrics": obstacle_metrics,
            }
        )

    def sanitize_command(
        self,
        command: Dict[str, object],
        snapshot: PerceptionSnapshot,
    ) -> Tuple[Dict[str, float], Dict[str, float], str]:
        reasons: List[str] = []
        requested_duration = float(command.get("duration_s", self.args.min_motion_duration))
        if not math.isfinite(requested_duration):
            requested_duration = self.args.min_motion_duration
            reasons.append("duration-non-finite->min-motion-duration")

        waypoint, waypoint_reasons = self.sanitize_local_waypoint(command, snapshot)
        if self.args.control_mode == "direct_cmd_vel":
            safe, controller_reasons = self.direct_command_from_model(
                command,
                snapshot,
                requested_duration=requested_duration,
            )
        else:
            safe, controller_reasons = self.waypoint_to_command(
                waypoint,
                snapshot,
                requested_duration=requested_duration,
            )
        reasons.extend(waypoint_reasons)
        reasons.extend(controller_reasons)
        remaining_global_distance = snapshot.global_goal_distance

        if safe["duration_s"] <= 0.05:
            safe["linear_mps"] = 0.0
            safe["angular_radps"] = 0.0
            safe["duration_s"] = 0.0
            reasons.append("duration-too-small->stop")
        elif (
            (abs(safe["linear_mps"]) > 0.05 or abs(safe["angular_radps"]) > 0.08)
            and safe["duration_s"] < self.args.min_motion_duration
            and remaining_global_distance > 0.5
        ):
            safe["duration_s"] = min(self.args.max_duration, self.args.min_motion_duration)
            reasons.append("extend-short-motion-command")

        front_clearance = snapshot.obstacle_metrics.get("front_clearance_m")
        sectors = snapshot.obstacle_metrics.get("sectors", {})
        corridor = snapshot.obstacle_metrics.get("corridor", {})
        left_clearance = optional_finite_float(corridor.get("left_clearance_m"))
        right_clearance = optional_finite_float(corridor.get("right_clearance_m"))
        center_label = str(sectors.get("center", {}).get("label", "clear"))
        current_applied = self.active_execution.applied if self.active_execution is not None else None
        if front_clearance is not None and float(front_clearance) < self.robot_front_stop_clearance() and safe["linear_mps"] > 0.0:
            safe["linear_mps"] = 0.0
            if abs(safe["angular_radps"]) < 0.1:
                bias = self.sector_rotation_bias(sectors)
                if bias == 0.0:
                    bias = -1.0 if snapshot.goal_bearing_deg > 0.0 else 1.0
                safe["angular_radps"] = 0.4 * bias
            reasons.append("front-clearance-blocked-forward")

        route_plan_mode = str(snapshot.route_plan.get("mode", "none"))
        if abs(snapshot.goal_bearing_deg) > 135.0 and safe["linear_mps"] > 0.0 and route_plan_mode == "none":
            safe["linear_mps"] = min(safe["linear_mps"], 0.06)
            if abs(safe["angular_radps"]) < 0.14:
                safe["angular_radps"] = -0.18 if snapshot.goal_bearing_deg > 0.0 else 0.18
            safe["duration_s"] = min(self.args.max_duration, max(safe["duration_s"], 0.9))
            reasons.append("goal-behind-soft-reorient")

        desired_turn = desired_angular_sign(snapshot.goal_local_right)
        desired_clearance = float(self.args.desired_clearance)
        local_goal_mode = str(snapshot.goal_state.get("local_mode", "translate"))
        front_tight = front_clearance is not None and float(front_clearance) < desired_clearance
        center_label = str(sectors.get("center", {}).get("label", "clear"))
        previous_step = snapshot.previous_step
        previous_obstacle_before = previous_step.get("obstacle_memory_before", {}) if previous_step is not None else {}
        previous_applied = previous_step.get("applied", {}) if previous_step is not None else {}

        if local_goal_mode == "rotate_to_global":
            safe["linear_mps"] = 0.0
            rotate_rate = 0.22 if abs(snapshot.global_goal_bearing_deg) < 120.0 else 0.30
            if abs(safe["angular_radps"]) < rotate_rate:
                if desired_turn == 0.0:
                    desired_turn = -1.0 if snapshot.global_goal_bearing_deg > 0.0 else 1.0
                safe["angular_radps"] = rotate_rate * desired_turn
            safe["duration_s"] = max(safe["duration_s"], min(self.args.max_duration, 1.2))
            reasons.append("rotate-subgoal-limit-forward")

        if desired_turn != 0.0 and abs(safe["angular_radps"]) >= 0.08:
            current_turn = 1.0 if safe["angular_radps"] > 0.0 else -1.0
            allow_goal_flip = (
                abs(snapshot.goal_bearing_deg) > 32.0
                and (front_clearance is None or float(front_clearance) > (self.robot_side_escape_clearance() + 0.15))
                and center_label in ("clear", "open")
            )
            if (
                current_turn != desired_turn
                and allow_goal_flip
                and not self.should_allow_turn_away_from_goal(desired_turn, sectors, front_clearance)
            ):
                safe["angular_radps"] = abs(safe["angular_radps"]) * desired_turn
                reasons.append("flip-turn-toward-goal")

        if (
            local_goal_mode != "rotate_to_global"
            and
            front_tight
            and snapshot.goal_local_forward > 0.4
            and abs(snapshot.goal_bearing_deg) <= 85.0
            and (front_clearance is None or float(front_clearance) > self.robot_front_stop_clearance())
        ):
            detour_bias = self.choose_detour_bias(sectors, desired_turn)
            if detour_bias != 0.0:
                target_linear = min(0.75, self.args.max_linear)
                if front_clearance is not None and float(front_clearance) < (desired_clearance * 0.8):
                    target_linear = min(target_linear, 0.28)
                if safe["linear_mps"] < target_linear:
                    safe["linear_mps"] = target_linear
                target_turn = 0.28 * detour_bias
                if abs(snapshot.goal_bearing_deg) > 25.0:
                    target_turn = 0.38 * detour_bias
                if abs(safe["angular_radps"]) < abs(target_turn) or math.copysign(1.0, safe["angular_radps"] or target_turn) != math.copysign(1.0, target_turn):
                    safe["angular_radps"] = target_turn
                safe["duration_s"] = max(safe["duration_s"], min(2.4, self.args.max_duration))
                reasons.append("prefer-1m-clearance-detour")

        previous_front_clearance = optional_finite_float(previous_obstacle_before.get("front_clearance_m"))
        previous_center_label = str(previous_obstacle_before.get("sectors", {}).get("center", {}).get("label", "clear"))
        previous_turn_rate = optional_finite_float(previous_applied.get("angular_radps"))
        previous_turn_sign = 0.0
        if previous_turn_rate is not None and abs(previous_turn_rate) >= 0.06:
            previous_turn_sign = 1.0 if previous_turn_rate > 0.0 else -1.0
        previous_close_obstacle = (
            (previous_front_clearance is not None and previous_front_clearance < (desired_clearance + 0.25))
            or previous_center_label in ("blocked", "tight", "crowded")
        )
        current_turn_sign = 0.0
        if abs(safe["angular_radps"]) >= 0.08:
            current_turn_sign = 1.0 if safe["angular_radps"] > 0.0 else -1.0
        current_not_wide_open = front_clearance is None or float(front_clearance) < (desired_clearance + 0.55)
        if (
            local_goal_mode != "rotate_to_global"
            and
            previous_turn_sign != 0.0
            and current_turn_sign != 0.0
            and current_turn_sign != previous_turn_sign
            and previous_close_obstacle
            and current_not_wide_open
            and remaining_global_distance > 0.4
        ):
            safe["angular_radps"] = math.copysign(min(max(abs(safe["angular_radps"]), 0.08), 0.16), previous_turn_sign)
            safe["duration_s"] = max(safe["duration_s"], min(1.6, self.args.max_duration))
            reasons.append("preserve-recent-detour-memory")

        front_is_clear = front_clearance is None or float(front_clearance) > (self.robot_front_stop_clearance() + 0.35)
        if (
            local_goal_mode != "rotate_to_global"
            and
            snapshot.goal_local_forward > 0.75
            and abs(snapshot.goal_bearing_deg) <= 25.0
            and front_is_clear
            and center_label in ("clear", "open", "crowded")
        ):
            if safe["linear_mps"] <= 0.05:
                safe["linear_mps"] = min(0.95, self.args.max_linear)
                reasons.append("goal-ahead-add-forward-progress")
            if abs(safe["angular_radps"]) > 0.30:
                safe["angular_radps"] = math.copysign(0.30, safe["angular_radps"])
                reasons.append("goal-ahead-limit-turn-rate")

        if (
            local_goal_mode != "rotate_to_global"
            and snapshot.goal_local_forward > 0.75
            and abs(snapshot.goal_bearing_deg) <= 10.0
            and abs(safe["angular_radps"]) > 0.18
        ):
            safe["angular_radps"] = math.copysign(0.18, safe["angular_radps"])
            reasons.append("goal-near-center-limit-rotation")

        comfortable_front_clearance = front_clearance is None or float(front_clearance) > (self.robot_side_escape_clearance() + 0.20)
        if local_goal_mode != "rotate_to_global" and comfortable_front_clearance and snapshot.goal_local_forward > 1.0:
            if (
                current_applied is not None
                and current_applied["linear_mps"] > 0.15
                and abs(current_applied["angular_radps"]) <= 0.18
                and safe["linear_mps"] < current_applied["linear_mps"]
                and abs(snapshot.goal_bearing_deg) <= 18.0
            ):
                safe["linear_mps"] = min(self.args.max_linear, float(current_applied["linear_mps"]))
                reasons.append("maintain-safe-forward-progress")

            if safe["linear_mps"] > 0.15 and abs(safe["angular_radps"]) > 0.22:
                safe["angular_radps"] = math.copysign(0.22, safe["angular_radps"])
                reasons.append("cautious-rotation-while-moving")

            if (
                current_applied is not None
                and current_applied["linear_mps"] > 0.15
                and abs(current_applied["angular_radps"]) <= 0.12
                and safe["linear_mps"] <= 0.05
                and abs(snapshot.goal_bearing_deg) <= 12.0
            ):
                safe["linear_mps"] = min(self.args.max_linear, float(current_applied["linear_mps"]))
                safe["angular_radps"] = math.copysign(
                    min(abs(safe["angular_radps"]), 0.12),
                    safe["angular_radps"] if abs(safe["angular_radps"]) > 1e-6 else current_applied["angular_radps"],
                )
                reasons.append("avoid-unnecessary-stop-when-straight-safe")

        if (
            local_goal_mode != "rotate_to_global"
            and
            current_applied is not None
            and remaining_global_distance > 0.25
            and (front_clearance is None or float(front_clearance) > self.robot_front_stop_clearance())
        ):
            safe["linear_mps"] = clamp(
                safe["linear_mps"],
                float(current_applied["linear_mps"]) - self.args.max_linear_step,
                float(current_applied["linear_mps"]) + self.args.max_linear_step,
            )
            safe["angular_radps"] = clamp(
                safe["angular_radps"],
                float(current_applied["angular_radps"]) - self.args.max_angular_step,
                float(current_applied["angular_radps"]) + self.args.max_angular_step,
            )
            reasons.append("final-rate-limit")

        reverse_path_blocked, reverse_block_along, _ = self.red_point_path_blocked(
            waypoint["right_m"],
            max(0.25, waypoint["forward_m"]),
            pose=snapshot.pose,
            extra_margin=0.06,
        )
        reverse_escape_needed = self.should_reverse_escape(
            front_clearance=front_clearance,
            center_label=center_label,
            left_clearance=left_clearance,
            right_clearance=right_clearance,
            path_blocked=reverse_path_blocked,
            block_along=reverse_block_along,
        )
        if reverse_escape_needed:
            reverse_cmd, reverse_reason = self.reverse_escape_command(
                left_clearance=left_clearance,
                right_clearance=right_clearance,
                goal_right=snapshot.goal_local_right,
                duration_override=min(self.args.max_duration, max(self.args.reverse_escape_duration, safe["duration_s"])),
            )
            safe = reverse_cmd
            reasons.append(reverse_reason)

        if self.goal_is_complete(remaining_global_distance):
            safe = {"linear_mps": 0.0, "angular_radps": 0.0, "duration_s": 0.0}
            reasons.append("global-goal-reached-stop")

        if abs(safe["linear_mps"]) < 1e-3:
            safe["linear_mps"] = 0.0
        if abs(safe["angular_radps"]) < 1e-3:
            safe["angular_radps"] = 0.0

        return waypoint, safe, "; ".join(reasons) if reasons else "none"

    def direct_command_from_model(
        self,
        command: Dict[str, object],
        snapshot: PerceptionSnapshot,
        requested_duration: float,
    ) -> Tuple[Dict[str, float], List[str]]:
        profiled, reasons = self.profile_command_from_model(command, snapshot)
        remaining_global_distance = snapshot.global_goal_distance
        local_goal_mode = str(snapshot.goal_state.get("local_mode", "translate"))
        linear = optional_finite_float(command.get("linear_mps"))
        angular = optional_finite_float(command.get("angular_radps"))
        if linear is None:
            linear = profiled["linear_mps"]
            reasons.append("direct-linear-from-band")
        if angular is None:
            angular = profiled["angular_radps"]
            reasons.append("direct-angular-from-band")

        numeric_linear = clamp(linear, -self.args.max_linear, self.args.max_linear)
        numeric_angular = clamp(angular, -self.args.max_angular, self.args.max_angular)
        linear = clamp((0.78 * profiled["linear_mps"]) + (0.22 * numeric_linear), -self.args.max_linear, self.args.max_linear)
        angular = clamp((0.78 * profiled["angular_radps"]) + (0.22 * numeric_angular), -self.args.max_angular, self.args.max_angular)
        duration = clamp(max(profiled["duration_s"], requested_duration), 0.0, self.args.max_duration)
        reasons.append("direct-command-banded")

        if (
            (abs(linear) > 0.05 or abs(angular) > 0.08)
            and duration < self.args.min_motion_duration
            and remaining_global_distance > 0.5
        ):
            duration = min(self.args.max_duration, self.args.min_motion_duration)
            reasons.append("extend-short-direct-command")

        front_clearance = snapshot.obstacle_metrics.get("front_clearance_m")
        sectors = snapshot.obstacle_metrics.get("sectors", {})
        corridor = snapshot.obstacle_metrics.get("corridor", {})
        left_clearance = optional_finite_float(corridor.get("left_clearance_m"))
        right_clearance = optional_finite_float(corridor.get("right_clearance_m"))
        preferred_center_clearance = self.robot_preferred_center_clearance()
        side_escape_clearance = self.robot_side_escape_clearance()
        if front_clearance is not None and float(front_clearance) < self.robot_front_stop_clearance() and linear > 0.0:
            linear = 0.0
            if abs(angular) < 0.1:
                bias = self.sector_rotation_bias(sectors)
                if bias == 0.0:
                    bias = -1.0 if snapshot.goal_bearing_deg > 0.0 else 1.0
                angular = 0.4 * bias
            reasons.append("front-clearance-blocked-forward")

        route_plan_mode = str(snapshot.route_plan.get("mode", "none"))
        if abs(snapshot.goal_bearing_deg) > 135.0 and linear > 0.0 and route_plan_mode == "none":
            linear = min(linear, 0.06)
            if abs(angular) < 0.14:
                angular = -0.18 if snapshot.goal_bearing_deg > 0.0 else 0.18
            duration = min(self.args.max_duration, max(duration, 0.9))
            reasons.append("goal-behind-soft-reorient")

        if local_goal_mode == "rotate_to_global":
            linear = 0.0
            desired_turn = desired_angular_sign(snapshot.goal_local_right)
            if desired_turn == 0.0:
                desired_turn = -1.0 if snapshot.global_goal_bearing_deg > 0.0 else 1.0
            rotate_rate = 0.22 if abs(snapshot.global_goal_bearing_deg) < 120.0 else 0.30
            if abs(angular) < rotate_rate:
                angular = rotate_rate * desired_turn
            duration = max(duration, min(self.args.max_duration, 1.2))
            reasons.append("direct-rotate-subgoal-limit-forward")

        tight_side_clearance = min(
            left_clearance if left_clearance is not None else float("inf"),
            right_clearance if right_clearance is not None else float("inf"),
        )
        escape_right_sign = self.side_wall_escape_right_sign(left_clearance, right_clearance)
        if (
            local_goal_mode != "rotate_to_global"
            and
            escape_right_sign != 0.0
            and math.isfinite(tight_side_clearance)
            and tight_side_clearance < side_escape_clearance
        ):
            escape_turn = -0.30 * escape_right_sign
            if abs(angular) < abs(escape_turn) or math.copysign(1.0, angular or escape_turn) != math.copysign(1.0, escape_turn):
                angular = escape_turn
            if front_clearance is not None and float(front_clearance) > (self.robot_front_stop_clearance() + 0.18):
                linear = min(max(linear, 0.18), min(self.args.max_linear, 0.24))
            else:
                linear = min(linear, 0.10)
            reasons.append("direct-side-wall-escape")

        if self.goal_is_complete(remaining_global_distance):
            linear = 0.0
            angular = 0.0
            duration = 0.0
            reasons.append("global-goal-reached-stop")

        return {
            "linear_mps": linear,
            "angular_radps": angular,
            "duration_s": duration,
        }, reasons

    def build_execution_state(
        self,
        parsed: Dict[str, object],
        result: Dict[str, object],
        snapshot: PerceptionSnapshot,
    ) -> ExecutionState:
        waypoint, sanitized, safety_override = self.sanitize_command(parsed, snapshot)
        world_waypoint = self.local_waypoint_to_world(snapshot.pose, waypoint)
        now = time.monotonic()
        action_text = (
            f"MODE: {parsed.get('nav_mode', 'progress')} "
            f"PHASE: {parsed.get('agent_phase', 'advance')} "
            f"OBS: {parsed.get('observation_target', 'front_corridor')} "
            f"COMMIT: {int(parsed.get('plan_commit_steps', 1))} "
            f"BANDS: [{parsed.get('speed_band', 'cautious')}, {parsed.get('turn_band', 'straight')}, {parsed.get('duration_band', 'medium')}] "
            f"WAYPOINT: [{waypoint['right_m']:.2f}, {waypoint['forward_m']:.2f}, {waypoint['speed_mps']:.2f}] "
            f"ACTION: [{sanitized['linear_mps']:.2f}, {sanitized['angular_radps']:.2f}, {sanitized['duration_s']:.2f}]"
        )
        return ExecutionState(
            step_index=snapshot.step_index,
            requested={
                "nav_mode": str(parsed["nav_mode"]),
                "agent_phase": str(parsed["agent_phase"]),
                "observation_target": str(parsed["observation_target"]),
                "plan_commit_steps": int(parsed["plan_commit_steps"]),
                "speed_band": str(parsed["speed_band"]),
                "turn_band": str(parsed["turn_band"]),
                "duration_band": str(parsed["duration_band"]),
                "waypoint_right_m": float(parsed["waypoint_right_m"]),
                "waypoint_forward_m": float(parsed["waypoint_forward_m"]),
                "waypoint_speed_mps": float(parsed["waypoint_speed_mps"]),
                "linear_mps": float(parsed["linear_mps"]),
                "angular_radps": float(parsed["angular_radps"]),
                "duration_s": float(parsed["duration_s"]),
            },
            applied=sanitized,
            waypoint=waypoint,
            world_waypoint=world_waypoint,
            reasoning_summary=str(parsed["reasoning_summary"]),
            risk_level=str(parsed["risk_level"]),
            action_text=action_text,
            raw_output_text=str(result["raw_output_text"]),
            raw_response=result["response"],
            prompt_debug=copy.deepcopy(result.get("prompt_debug", {})),
            snapshot=snapshot,
            safety_override=safety_override,
            start_pose=Pose2D(snapshot.pose.stamp, snapshot.pose.x, snapshot.pose.y, snapshot.pose.yaw),
            start_monotonic=now,
            end_monotonic=now + float(sanitized["duration_s"]),
            hold_until_monotonic=now + float(sanitized["duration_s"]) + float(self.args.command_hold_s),
        )

    def activate_execution_state(self, execution: ExecutionState):
        self.stop_ramp = None
        self.active_execution = execution
        self.apply_agent_plan_commitment(execution)
        if str(execution.snapshot.goal_state.get("local_mode", "translate")) != "rotate_to_global":
            self.latch_detour_commitment(execution.waypoint)
        self.step_counter = execution.step_index
        self.motion_last_update_monotonic = time.monotonic()
        self.latest_action_text = execution.action_text
        self.latest_reasoning = execution.reasoning_summary
        self.latest_risk = execution.risk_level

        if not self.auto_enabled:
            self.last_error = "action ready but auto mode is paused"
            self.active_execution = None
            self.api_status = "paused"
            return

        if execution.applied["duration_s"] <= 0.0:
            self.api_status = "stop"
            self.finalize_execution("completed")
            return

        self.api_status = "executing"

    def can_hold_current_command(self, execution: ExecutionState) -> bool:
        if execution.applied["linear_mps"] <= 0.05:
            return False
        if execution.applied["duration_s"] <= 0.05:
            return False

        front_clearance = self.last_obstacle_metrics.get("front_clearance_m")
        if front_clearance is not None and float(front_clearance) <= (self.robot_front_stop_clearance() + 0.20):
            return False
        return True

    def local_waypoint_to_world(self, pose: Pose2D, waypoint: Dict[str, float]) -> Dict[str, float]:
        delta_x, delta_y = robot_to_world(float(waypoint["right_m"]), float(waypoint["forward_m"]), pose.yaw)
        return {
            "x_m": pose.x + delta_x,
            "y_m": pose.y + delta_y,
            "speed_mps": float(waypoint["speed_mps"]),
            "planned_right_m": float(waypoint["right_m"]),
            "planned_forward_m": float(waypoint["forward_m"]),
        }

    def execution_waypoint_local(self, execution: ExecutionState, pose: Pose2D) -> Dict[str, float]:
        delta_x = float(execution.world_waypoint["x_m"]) - pose.x
        delta_y = float(execution.world_waypoint["y_m"]) - pose.y
        right, forward = world_to_robot(delta_x, delta_y, pose.yaw)
        return {
            "right_m": right,
            "forward_m": forward,
            "speed_mps": float(execution.world_waypoint["speed_mps"]),
        }

    def execution_waypoint_distance(self, execution: ExecutionState, pose: Pose2D) -> float:
        local_waypoint = self.execution_waypoint_local(execution, pose)
        return math.hypot(local_waypoint["right_m"], local_waypoint["forward_m"])

    def execution_waypoint_reached(self, execution: ExecutionState, pose: Pose2D) -> bool:
        local_waypoint = self.execution_waypoint_local(execution, pose)
        distance = math.hypot(local_waypoint["right_m"], local_waypoint["forward_m"])
        if distance <= self.args.waypoint_reach_m:
            return True
        if local_waypoint["forward_m"] < -0.08 and abs(local_waypoint["right_m"]) <= (self.args.waypoint_reach_m * 1.5):
            return True
        return False

    def queued_waypoint_preview_lines(self, pose: Optional[Pose2D], limit: int = 3) -> List[str]:
        if pose is None:
            return ["- none"]

        preview: List[str] = []
        if self.active_execution is not None:
            local_waypoint = self.execution_waypoint_local(self.active_execution, pose)
            preview.append(
                f"- active target: right={local_waypoint['right_m']:.2f}, forward={local_waypoint['forward_m']:.2f}, speed={local_waypoint['speed_mps']:.2f}"
            )

        for index, execution in enumerate(list(self.execution_queue)[:limit], start=1):
            local_waypoint = self.execution_waypoint_local(execution, pose)
            preview.append(
                f"- queued#{index}: right={local_waypoint['right_m']:.2f}, forward={local_waypoint['forward_m']:.2f}, speed={local_waypoint['speed_mps']:.2f}"
            )

        return preview or ["- none"]

    def enqueue_execution(self, execution: ExecutionState):
        if self.execution_queue:
            tail = self.execution_queue[-1]
            distance = math.hypot(
                float(execution.world_waypoint["x_m"]) - float(tail.world_waypoint["x_m"]),
                float(execution.world_waypoint["y_m"]) - float(tail.world_waypoint["y_m"]),
            )
            if distance < 0.35:
                self.execution_queue[-1] = execution
                return
        self.execution_queue.append(execution)

    def red_point_path_blocked(
        self,
        waypoint_right: float,
        waypoint_forward: float,
        pose: Optional[Pose2D] = None,
        extra_margin: float = 0.0,
    ) -> Tuple[bool, Optional[float], float]:
        hard_margin = self.robot_hard_block_margin(extra_margin)
        clearance, block_along, block_side = self.path_min_clearance(
            waypoint_right,
            waypoint_forward,
            pose=pose if pose is not None else self.current_pose,
        )
        blocked = math.isfinite(clearance) and clearance <= hard_margin
        return blocked, block_along, block_side

    def choose_detour_bias(
        self,
        sectors: Dict[str, object],
        goal_turn: float,
    ) -> float:
        bias = self.sector_rotation_bias(sectors)
        if bias != 0.0:
            return bias
        return goal_turn

    def side_wall_escape_right_sign(
        self,
        left_clearance: Optional[float],
        right_clearance: Optional[float],
    ) -> float:
        left = left_clearance if left_clearance is not None else float("inf")
        right = right_clearance if right_clearance is not None else float("inf")
        if not math.isfinite(left) and not math.isfinite(right):
            return 0.0
        if left < right:
            return 1.0
        if right < left:
            return -1.0
        return 0.0

    def should_reverse_escape(
        self,
        *,
        front_clearance: Optional[float],
        center_label: Optional[str],
        left_clearance: Optional[float],
        right_clearance: Optional[float],
        path_blocked: bool,
        block_along: Optional[float],
    ) -> bool:
        front_blocked = front_clearance is not None and float(front_clearance) < (self.robot_front_stop_clearance() + 0.08)
        side_tight = min(
            left_clearance if left_clearance is not None else float("inf"),
            right_clearance if right_clearance is not None else float("inf"),
        ) < self.robot_side_escape_clearance()
        center_bad = center_label in ("blocked", "tight")
        near_block = block_along is not None and float(block_along) < 0.95
        return (front_blocked and (side_tight or center_bad)) or (path_blocked and near_block and side_tight)

    def reverse_escape_command(
        self,
        *,
        left_clearance: Optional[float],
        right_clearance: Optional[float],
        goal_right: float,
        duration_override: Optional[float] = None,
    ) -> Tuple[Dict[str, float], str]:
        escape_right_sign = self.side_wall_escape_right_sign(left_clearance, right_clearance)
        if escape_right_sign == 0.0:
            goal_turn = desired_angular_sign(goal_right)
            if goal_turn != 0.0:
                escape_right_sign = -goal_turn
            else:
                escape_right_sign = 1.0

        reverse_turn = -float(self.args.reverse_escape_turn) * escape_right_sign
        reverse_linear = -float(self.args.reverse_escape_speed)
        reverse_duration = float(duration_override if duration_override is not None else self.args.reverse_escape_duration)
        reverse_duration = clamp(reverse_duration, 0.25, min(self.args.max_duration, 1.4))
        return {
            "linear_mps": reverse_linear,
            "angular_radps": clamp(reverse_turn, -self.args.max_angular, self.args.max_angular),
            "duration_s": reverse_duration,
        }, "reverse-escape-from-wall"

    def speed_band_value(self, band: str) -> float:
        return {
            "stop": 0.0,
            "crawl": 0.10,
            "cautious": 0.20,
            "steady": 0.34,
            "brisk": 0.50,
        }.get(str(band), 0.20)

    def turn_band_value(self, band: str) -> float:
        return {
            "straight": 0.0,
            "slight_left": 0.08,
            "left": 0.16,
            "sharp_left": 0.28,
            "slight_right": -0.08,
            "right": -0.16,
            "sharp_right": -0.28,
        }.get(str(band), 0.0)

    def duration_band_value(self, band: str) -> float:
        base = {
            "short": 0.8,
            "medium": 1.4,
            "long": 2.1,
        }.get(str(band), 1.2)
        return clamp(base, 0.3, self.args.max_duration)

    def profile_command_from_model(
        self,
        command: Dict[str, object],
        snapshot: PerceptionSnapshot,
    ) -> Tuple[Dict[str, float], List[str]]:
        reasons: List[str] = []
        nav_mode = str(command.get("nav_mode", "progress"))
        speed_band = str(command.get("speed_band", "cautious"))
        turn_band = str(command.get("turn_band", "straight"))
        duration_band = str(command.get("duration_band", "medium"))

        linear = self.speed_band_value(speed_band)
        angular = self.turn_band_value(turn_band)
        duration = self.duration_band_value(duration_band)

        corridor = snapshot.obstacle_metrics.get("corridor", {})
        left_clearance = optional_finite_float(corridor.get("left_clearance_m"))
        right_clearance = optional_finite_float(corridor.get("right_clearance_m"))
        escape_right_sign = self.side_wall_escape_right_sign(left_clearance, right_clearance)

        if nav_mode == "progress":
            reasons.append("profile-progress")
        elif nav_mode == "detour_left":
            angular = max(angular, 0.12)
            linear = max(linear, 0.16)
            reasons.append("profile-detour-left")
        elif nav_mode == "detour_right":
            angular = min(angular, -0.12)
            linear = max(linear, 0.16)
            reasons.append("profile-detour-right")
        elif nav_mode == "scan_left":
            angular = max(angular, 0.16)
            linear = min(max(linear, 0.04), 0.10)
            reasons.append("profile-scan-left")
        elif nav_mode == "scan_right":
            angular = min(angular, -0.16)
            linear = min(max(linear, 0.04), 0.10)
            reasons.append("profile-scan-right")
        elif nav_mode == "reverse_escape":
            reverse_cmd, reverse_reason = self.reverse_escape_command(
                left_clearance=left_clearance,
                right_clearance=right_clearance,
                goal_right=snapshot.goal_local_right,
                duration_override=duration,
            )
            reasons.append(f"profile-{reverse_reason}")
            return reverse_cmd, reasons
        elif nav_mode == "explore":
            if abs(angular) < 0.10:
                if escape_right_sign != 0.0:
                    angular = -0.14 * escape_right_sign
                else:
                    angular = 0.14 if snapshot.goal_local_right < 0.0 else -0.14
            linear = min(linear, 0.12)
            reasons.append("profile-explore")

        linear = clamp(linear, 0.0, self.args.max_linear)
        angular = clamp(angular, -self.args.max_angular, self.args.max_angular)
        return {
            "linear_mps": linear,
            "angular_radps": angular,
            "duration_s": duration,
        }, reasons

    def robot_radius_m(self) -> float:
        return max(0.05, float(self.args.robot_radius))

    def robot_body_safety_buffer_m(self) -> float:
        return max(0.05, float(self.args.body_safety_buffer))

    def robot_hard_block_margin(self, extra: float = 0.0) -> float:
        return clamp(self.robot_radius_m() + self.robot_body_safety_buffer_m() + 0.06 + extra, 0.36, 1.05)

    def robot_preferred_center_clearance(self) -> float:
        return clamp(
            self.robot_radius_m() + self.robot_body_safety_buffer_m() + float(self.args.desired_clearance),
            0.70,
            1.95,
        )

    def robot_front_stop_clearance(self) -> float:
        return max(float(self.args.min_front_clearance), self.robot_hard_block_margin() + 0.08)

    def robot_side_escape_clearance(self) -> float:
        return max(self.robot_preferred_center_clearance(), self.robot_hard_block_margin() + 0.18)

    def sector_clearance_score(self, info: Dict[str, object]) -> float:
        value = optional_finite_float(info.get("min_distance_m"))
        if value is None:
            return self.args.desired_clearance + 1.0
        return value

    def preferred_exploration_signs(self, snapshot: PerceptionSnapshot) -> List[float]:
        sectors = snapshot.obstacle_metrics.get("sectors", {})
        memory_sectors = snapshot.map_memory_summary.get("sectors", {})
        committed_sign, _ = self.current_commitment_sign(snapshot.pose)
        signs: List[float] = []
        if committed_sign != 0.0:
            signs.append(committed_sign)

        right_score = max(
            self.sector_clearance_score(sectors.get("right", {})),
            self.sector_clearance_score(memory_sectors.get("right", {})),
        )
        left_score = max(
            self.sector_clearance_score(sectors.get("left", {})),
            self.sector_clearance_score(memory_sectors.get("left", {})),
        )
        if right_score > left_score:
            signs.extend([1.0, -1.0])
        elif left_score > right_score:
            signs.extend([-1.0, 1.0])
        else:
            goal_bias = desired_angular_sign(snapshot.goal_local_right)
            if goal_bias != 0.0:
                signs.extend([-goal_bias, goal_bias])
            else:
                signs.extend([1.0, -1.0])

        ordered: List[float] = []
        for sign in signs:
            if sign != 0.0 and sign not in ordered:
                ordered.append(sign)
        return ordered or [1.0, -1.0]

    def choose_exploration_waypoint(
        self,
        snapshot: PerceptionSnapshot,
        max_wp_right: float,
        max_wp_forward: float,
        safe_min_right: float,
        safe_max_right: float,
    ) -> Tuple[Dict[str, float], List[str]]:
        reasons: List[str] = []
        preferred_signs = self.preferred_exploration_signs(snapshot)
        best_candidate: Optional[Dict[str, float]] = None
        best_score = -1e9

        for sign in preferred_signs:
            candidate_right = clamp(
                sign * clamp(self.args.desired_clearance * 1.05, 0.9, max_wp_right),
                safe_min_right,
                safe_max_right,
            )
            candidate_forward = min(max_wp_forward, 1.2)
            blocked, _, _ = self.red_point_path_blocked(
                candidate_right,
                candidate_forward,
                pose=snapshot.pose,
                extra_margin=0.08,
            )
            clearance, _, _ = self.path_min_clearance(candidate_right, candidate_forward, pose=snapshot.pose)
            if blocked:
                candidate_forward = min(max_wp_forward, 0.75)
                blocked, _, _ = self.red_point_path_blocked(
                    candidate_right,
                    candidate_forward,
                    pose=snapshot.pose,
                    extra_margin=0.08,
                )
                clearance, _, _ = self.path_min_clearance(candidate_right, candidate_forward, pose=snapshot.pose)

            score = (clearance if math.isfinite(clearance) else (self.args.desired_clearance + 1.0))
            if blocked:
                score -= 4.0
            if sign == preferred_signs[0]:
                score += 0.3
            if score > best_score and not blocked:
                best_score = score
                best_candidate = {
                    "right_m": candidate_right,
                    "forward_m": candidate_forward,
                    "speed_mps": min(self.args.max_linear, 0.40),
                }

        if best_candidate is not None:
            reasons.append("explore-open-side-corridor")
            return best_candidate, reasons

        rotate_sign = preferred_signs[0]
        reasons.append("explore-rotate-to-find-corridor")
        return {
            "right_m": clamp(rotate_sign * clamp(self.args.desired_clearance, 0.9, max_wp_right), safe_min_right, safe_max_right),
            "forward_m": 0.0,
            "speed_mps": 0.0,
        }, reasons

    def sanitize_local_waypoint(
        self,
        command: Dict[str, object],
        snapshot: PerceptionSnapshot,
    ) -> Tuple[Dict[str, float], List[str]]:
        reasons: List[str] = []
        max_wp_forward = min(self.max_forward * 0.55, 2.5)
        max_wp_right = min(self.max_side * 0.75, 1.8)
        front_clearance = snapshot.obstacle_metrics.get("front_clearance_m")
        corridor = snapshot.obstacle_metrics.get("corridor", {})
        sectors = snapshot.obstacle_metrics.get("sectors", {})
        remaining_global_distance = snapshot.global_goal_distance

        waypoint_right = float(command.get("waypoint_right_m", snapshot.goal_local_right))
        waypoint_forward = float(command.get("waypoint_forward_m", snapshot.goal_local_forward))
        waypoint_speed = float(command.get("waypoint_speed_mps", max(0.0, float(command.get("linear_mps", 0.0)))))

        if not math.isfinite(waypoint_right):
            waypoint_right = 0.0
            reasons.append("waypoint-right-non-finite->0")
        if not math.isfinite(waypoint_forward):
            waypoint_forward = 0.8
            reasons.append("waypoint-forward-non-finite->0.8")
        if not math.isfinite(waypoint_speed):
            waypoint_speed = 0.2
            reasons.append("waypoint-speed-non-finite->0.2")

        waypoint_right = clamp(waypoint_right, -max_wp_right, max_wp_right)
        waypoint_forward = clamp(waypoint_forward, -0.4, max_wp_forward)
        waypoint_speed = clamp(waypoint_speed, 0.0, self.args.max_linear)

        corridor_center = optional_finite_float(corridor.get("center_right_m"))
        corridor_width = optional_finite_float(corridor.get("width_m"))
        left_wall_x = optional_finite_float(corridor.get("left_wall_x_m"))
        right_wall_x = optional_finite_float(corridor.get("right_wall_x_m"))
        left_clearance = optional_finite_float(corridor.get("left_clearance_m"))
        right_clearance = optional_finite_float(corridor.get("right_clearance_m"))
        preferred_center_clearance = self.robot_preferred_center_clearance()
        side_escape_clearance = self.robot_side_escape_clearance()
        wall_margin = side_escape_clearance
        if corridor_width is not None:
            wall_margin = min(wall_margin, max(0.34, corridor_width * 0.40))

        safe_min_right = -max_wp_right
        safe_max_right = max_wp_right
        if left_wall_x is not None:
            safe_min_right = max(safe_min_right, left_wall_x + wall_margin)
        if right_wall_x is not None:
            safe_max_right = min(safe_max_right, right_wall_x - wall_margin)

        wall_is_close = (
            (left_clearance is not None and left_clearance < preferred_center_clearance)
            or (right_clearance is not None and right_clearance < preferred_center_clearance)
        )
        if corridor_center is not None and (wall_is_close or (corridor_width is not None and corridor_width < 2.4)):
            blend = 0.80 if wall_is_close else 0.45
            waypoint_right = ((1.0 - blend) * waypoint_right) + (blend * corridor_center)
            reasons.append("bias-waypoint-to-corridor-center")

        escape_right_sign = self.side_wall_escape_right_sign(left_clearance, right_clearance)
        very_tight_side_clearance = min(
            left_clearance if left_clearance is not None else float("inf"),
            right_clearance if right_clearance is not None else float("inf"),
        )
        if (
            escape_right_sign != 0.0
            and math.isfinite(very_tight_side_clearance)
            and very_tight_side_clearance < side_escape_clearance
        ):
            escape_target = clamp(
                escape_right_sign * clamp(self.args.desired_clearance * 0.95, 0.70, max_wp_right),
                safe_min_right,
                safe_max_right,
            )
            if corridor_center is not None:
                escape_target = clamp((0.55 * escape_target) + (0.45 * corridor_center), safe_min_right, safe_max_right)
            waypoint_right = escape_target
            waypoint_forward = max(waypoint_forward, min(max_wp_forward, 1.0))
            waypoint_speed = max(waypoint_speed, min(self.args.max_linear, 0.60))
            reasons.append("decisive-shift-away-from-side-wall")

        if safe_min_right > safe_max_right:
            fallback_center = corridor_center if corridor_center is not None else clamp(0.5 * (safe_min_right + safe_max_right), -max_wp_right, max_wp_right)
            safe_min_right = fallback_center
            safe_max_right = fallback_center
            reasons.append("narrow-corridor-center-waypoint")

        clipped_waypoint_right = clamp(waypoint_right, safe_min_right, safe_max_right)
        if clipped_waypoint_right != waypoint_right:
            waypoint_right = clipped_waypoint_right
            reasons.append("clamp-waypoint-away-from-side-wall")

        if snapshot.goal_local_forward > 0.6 and waypoint_forward < 0.4:
            waypoint_forward = min(max_wp_forward, max(0.8, waypoint_forward))
            reasons.append("push-waypoint-forward")

        if front_clearance is not None:
            clearance_limit = max(0.35, float(front_clearance) - 0.25)
            if waypoint_forward > clearance_limit:
                waypoint_forward = min(waypoint_forward, clearance_limit)
                reasons.append("limit-waypoint-by-front-clearance")

        if snapshot.goal_local_forward < -0.4 and abs(waypoint_right) < 0.2:
            waypoint_forward = min(waypoint_forward, 0.25)
            waypoint_right = 0.5 * (1.0 if snapshot.goal_local_right > 0.0 else -1.0)
            reasons.append("behind-goal-use-lateral-waypoint")

        path_blocked, block_along, block_side = self.red_point_path_blocked(
            waypoint_right,
            waypoint_forward,
            pose=snapshot.pose,
        )
        if path_blocked:
            if corridor_center is not None and abs(corridor_center) > 0.10:
                waypoint_right = clamp(corridor_center, safe_min_right, safe_max_right)
                reasons.append("redpoint-shift-to-corridor-center")
            else:
                detour_bias = self.sector_rotation_bias(sectors)
                if abs(block_side) > 0.08:
                    shift_sign = -1.0 if block_side > 0.0 else 1.0
                elif detour_bias != 0.0:
                    shift_sign = -detour_bias
                else:
                    shift_sign = -1.0 if snapshot.goal_local_right > 0.0 else 1.0
                shift_amount = clamp(max(0.45, self.args.desired_clearance * 0.80), 0.45, max_wp_right)
                waypoint_right = clamp(waypoint_right + (shift_sign * shift_amount), safe_min_right, safe_max_right)
                reasons.append("redpoint-hard-shift-waypoint")
            if block_along is not None:
                waypoint_forward = min(waypoint_forward, max(0.45, block_along - 0.30))
                reasons.append("redpoint-limit-waypoint-forward")
            waypoint_speed = min(waypoint_speed, min(self.args.max_linear, 0.35))
            still_blocked, still_block_along, _ = self.red_point_path_blocked(
                waypoint_right,
                waypoint_forward,
                pose=snapshot.pose,
                extra_margin=0.05,
            )
            if still_blocked and still_block_along is not None and still_block_along < 0.90:
                waypoint_forward = min(waypoint_forward, max(0.25, still_block_along - 0.40))
                waypoint_speed = min(waypoint_speed, 0.25)
                reasons.append("redpoint-hard-cap-before-wall")

        current_clearance, current_along, current_side = self.path_min_clearance(
            waypoint_right,
            waypoint_forward,
            pose=snapshot.pose,
        )
        if math.isfinite(current_clearance) and current_clearance < side_escape_clearance:
            target_right = corridor_center if corridor_center is not None else waypoint_right
            if escape_right_sign != 0.0:
                escape_target = clamp(
                    escape_right_sign * clamp(self.args.desired_clearance * 0.95, 0.70, max_wp_right),
                    safe_min_right,
                    safe_max_right,
                )
                if corridor_center is not None:
                    target_right = clamp((0.55 * escape_target) + (0.45 * corridor_center), safe_min_right, safe_max_right)
                else:
                    target_right = escape_target
            elif abs(current_side) > 0.06:
                shift_sign = -1.0 if current_side > 0.0 else 1.0
                shift_amount = clamp((preferred_center_clearance - current_clearance) + 0.18, 0.18, 0.75)
                target_right = clamp(waypoint_right + (shift_sign * shift_amount), safe_min_right, safe_max_right)

            shift_blend = clamp(
                (side_escape_clearance - current_clearance) / max(0.12, side_escape_clearance),
                0.30,
                0.88,
            )
            waypoint_right = clamp(
                ((1.0 - shift_blend) * waypoint_right) + (shift_blend * target_right),
                safe_min_right,
                safe_max_right,
            )
            waypoint_forward = min(max_wp_forward, max(waypoint_forward, 0.85))
            if current_clearance < max(self.robot_hard_block_margin(), side_escape_clearance - 0.16):
                waypoint_speed = min(waypoint_speed, min(self.args.max_linear, 0.32))
            else:
                waypoint_speed = min(waypoint_speed, min(self.args.max_linear, 0.48))
            reasons.append("soft-clearance-shift-away-from-wall")

        final_waypoint_right = clamp(waypoint_right, safe_min_right, safe_max_right)
        if final_waypoint_right != waypoint_right:
            waypoint_right = final_waypoint_right
            reasons.append("final-clamp-waypoint-away-from-side-wall")

        current_clearance, current_along, current_side = self.path_min_clearance(
            waypoint_right,
            waypoint_forward,
            pose=snapshot.pose,
        )

        long_waypoint_clear = (
            remaining_global_distance > 1.0
            and snapshot.goal_local_forward > 0.8
            and (front_clearance is None or float(front_clearance) > (self.args.desired_clearance + 0.45))
            and not self.red_point_path_blocked(waypoint_right, waypoint_forward, pose=snapshot.pose)[0]
        )
        if long_waypoint_clear:
            target_forward = clamp(snapshot.goal_local_forward, 1.2, 2.0)
            candidate_forward = max(waypoint_forward, min(max_wp_forward, target_forward))
            if not self.red_point_path_blocked(waypoint_right, candidate_forward, pose=snapshot.pose)[0]:
                waypoint_forward = candidate_forward
                waypoint_speed = max(
                    waypoint_speed,
                    min(self.args.max_linear, 1.15 if corridor_width is None or corridor_width > 1.8 else 0.90),
                )
                reasons.append("longer-faster-waypoint")

        if corridor_width is not None and corridor_width < max(1.35, side_escape_clearance * 1.55):
            waypoint_speed = min(waypoint_speed, min(self.args.max_linear, 0.38))
            reasons.append("narrow-corridor-limit-waypoint-speed")

        tight_side_clearance = min(
            left_clearance if left_clearance is not None else float("inf"),
            right_clearance if right_clearance is not None else float("inf"),
        )
        if math.isfinite(tight_side_clearance) and tight_side_clearance < side_escape_clearance:
            waypoint_speed = min(waypoint_speed, 0.22)
            waypoint_forward = min(waypoint_forward, 0.85)
            reasons.append("tight-side-clearance-slow-short-waypoint")

        reject_short_forward = (
            snapshot.goal_local_forward > 0.8
            and waypoint_forward < min(max_wp_forward, 0.9)
            and (
                (path_blocked and (block_along is None or block_along < 1.15))
                or (math.isfinite(tight_side_clearance) and tight_side_clearance < side_escape_clearance)
            )
        )
        if reject_short_forward:
            if abs(block_side) > 0.08:
                detour_right_sign = -1.0 if block_side > 0.0 else 1.0
            elif right_clearance is not None and left_clearance is not None and abs(right_clearance - left_clearance) > 0.05:
                detour_right_sign = 1.0 if right_clearance > left_clearance else -1.0
            else:
                detour_bias = self.sector_rotation_bias(sectors)
                if detour_bias != 0.0:
                    detour_right_sign = -detour_bias
                else:
                    detour_right_sign = -1.0 if snapshot.goal_local_right > 0.0 else 1.0

            detour_right = clamp(
                detour_right_sign * clamp(self.args.desired_clearance, 0.8, max_wp_right),
                safe_min_right,
                safe_max_right,
            )
            detour_forward = min(max_wp_forward, 1.0)
            detour_blocked, _, _ = self.red_point_path_blocked(
                detour_right,
                detour_forward,
                pose=snapshot.pose,
                extra_margin=0.05,
            )
            if not detour_blocked:
                waypoint_right = detour_right
                waypoint_forward = detour_forward
                waypoint_speed = min(max(waypoint_speed, 0.28), 0.35)
                reasons.append("reject-short-waypoint-use-detour")
            else:
                waypoint_right = detour_right
                waypoint_forward = 0.0
                waypoint_speed = 0.0
                reasons.append("reject-short-waypoint-rotate-only")

        planner_best = snapshot.planner_hint.get("best", {})
        planner_commitment_sign = float(snapshot.planner_hint.get("commitment_sign", 0.0) or 0.0)
        planner_right = optional_finite_float(planner_best.get("right_m"))
        planner_forward = optional_finite_float(planner_best.get("forward_m"))
        planner_speed = optional_finite_float(planner_best.get("speed_mps"))
        planner_clearance = optional_finite_float(planner_best.get("min_clearance_m"))
        if planner_clearance is None:
            planner_clearance = self.args.desired_clearance + 1.0
        planner_blocked = bool(planner_best.get("blocked", False))
        current_clearance, _, _ = self.path_min_clearance(waypoint_right, waypoint_forward, pose=snapshot.pose)
        if not math.isfinite(current_clearance):
            current_clearance = self.args.desired_clearance + 1.0

        if (
            planner_right is not None
            and planner_forward is not None
            and planner_speed is not None
            and not planner_blocked
        ):
            replace_with_planner = False
            if path_blocked:
                replace_with_planner = True
            elif planner_clearance > (current_clearance + 0.22):
                replace_with_planner = True
            elif math.isfinite(current_clearance) and current_clearance < side_escape_clearance and planner_clearance > (current_clearance + 0.08):
                replace_with_planner = True
            elif waypoint_forward < 0.75 and planner_forward > (waypoint_forward + 0.35) and remaining_global_distance > 1.0:
                replace_with_planner = True

            if replace_with_planner:
                if planner_commitment_sign != 0.0:
                    planner_sign = self.waypoint_commit_sign(planner_right, planner_forward)
                    current_sign = self.waypoint_commit_sign(waypoint_right, waypoint_forward)
                    if (
                        planner_sign != 0.0
                        and current_sign == planner_commitment_sign
                        and planner_sign != planner_commitment_sign
                        and planner_clearance < (current_clearance + self.args.flip_clearance_margin)
                        and not path_blocked
                    ):
                        replace_with_planner = False
                        reasons.append("keep-committed-detour-side")

            if replace_with_planner:
                waypoint_right = clamp(planner_right, safe_min_right, safe_max_right)
                waypoint_forward = clamp(planner_forward, -0.2, max_wp_forward)
                waypoint_speed = clamp(planner_speed, 0.0, self.args.max_linear)
                reasons.append("memory-guided-planner-replace-waypoint")

        center_label = str(sectors.get("center", {}).get("label", "clear"))
        fully_blocked = (
            remaining_global_distance > 0.8
            and (
                (front_clearance is not None and float(front_clearance) < max(self.args.min_front_clearance + 0.05, self.args.desired_clearance * 0.85))
                or center_label in ("blocked", "tight")
            )
            and (
                self.red_point_path_blocked(waypoint_right, max(0.4, waypoint_forward), pose=snapshot.pose, extra_margin=0.08)[0]
                or waypoint_forward < 0.35
                or planner_blocked
            )
        )
        if fully_blocked:
            exploration_waypoint, exploration_reasons = self.choose_exploration_waypoint(
                snapshot,
                max_wp_right=max_wp_right,
                max_wp_forward=max_wp_forward,
                safe_min_right=safe_min_right,
                safe_max_right=safe_max_right,
            )
            waypoint_right = exploration_waypoint["right_m"]
            waypoint_forward = exploration_waypoint["forward_m"]
            waypoint_speed = exploration_waypoint["speed_mps"]
            reasons.extend(exploration_reasons)

        if waypoint_speed <= 0.05 and remaining_global_distance > 0.4 and waypoint_forward > 0.35:
            waypoint_speed = min(self.args.max_linear, 0.35)
            reasons.append("raise-waypoint-speed")

        return {
            "right_m": waypoint_right,
            "forward_m": waypoint_forward,
            "speed_mps": waypoint_speed,
        }, reasons

    def controller_command_for_waypoint(
        self,
        waypoint: Dict[str, float],
        obstacle_metrics: Dict[str, object],
        requested_duration: float,
        current_applied: Optional[Dict[str, float]] = None,
    ) -> Tuple[Dict[str, float], List[str]]:
        reasons: List[str] = []
        right = float(waypoint["right_m"])
        forward = float(waypoint["forward_m"])
        speed = float(waypoint["speed_mps"])
        corridor = obstacle_metrics.get("corridor", {})
        left_clearance = optional_finite_float(corridor.get("left_clearance_m"))
        right_clearance = optional_finite_float(corridor.get("right_clearance_m"))
        preferred_center_clearance = self.robot_preferred_center_clearance()
        side_escape_clearance = self.robot_side_escape_clearance()

        heading_for_turn = math.atan2(right, max(forward, 0.12))
        angular_target = clamp(-0.95 * heading_for_turn, -self.args.max_angular, self.args.max_angular)
        linear_target = speed

        if forward <= 0.15:
            linear_target = min(linear_target, 0.08)
            angular_target = clamp(angular_target, -0.20, 0.20)
            reasons.append("near-turn-in-place-waypoint")
        else:
            heading_scale = max(0.2, math.cos(min(abs(heading_for_turn), math.pi / 2.0)))
            linear_target = min(linear_target * heading_scale, max(0.18, 0.85 * forward))

        if abs(heading_for_turn) > math.radians(28.0):
            angular_target = clamp(angular_target, -0.18, 0.18)
            linear_target = min(linear_target, 0.38)
            reasons.append("cautious-turn-to-waypoint")
        elif abs(heading_for_turn) > math.radians(16.0):
            angular_target = clamp(angular_target, -0.13, 0.13)
            linear_target = min(linear_target, 0.58)
            reasons.append("moderate-turn-to-waypoint")
        else:
            angular_target = clamp(angular_target, -0.10, 0.10)
            reasons.append("small-steering-to-waypoint")

        path_clearance, _, _ = self.path_min_clearance(right, forward, pose=self.current_pose)
        if math.isfinite(path_clearance):
            hard_margin = self.robot_hard_block_margin()
            if path_clearance < preferred_center_clearance:
                clearance_ratio = clamp(
                    (path_clearance - hard_margin) / max(0.05, preferred_center_clearance - hard_margin),
                    0.0,
                    1.0,
                )
                linear_cap = 0.18 + (0.55 * clearance_ratio)
                linear_target = min(linear_target, linear_cap)
                reasons.append("clearance-shaped-speed")
            elif forward > 0.9 and abs(heading_for_turn) <= math.radians(14.0):
                linear_target = max(linear_target, min(self.args.max_linear, speed))
                reasons.append("clearance-allows-brisk-track")

        front_clearance = obstacle_metrics.get("front_clearance_m")
        side_is_comfortable = (
            (left_clearance is None or left_clearance > preferred_center_clearance)
            and (right_clearance is None or right_clearance > preferred_center_clearance)
        )
        if (
            front_clearance is not None
            and float(front_clearance) > (side_escape_clearance + 0.10)
            and forward > 0.8
            and side_is_comfortable
        ):
            linear_target = min(self.args.max_linear, max(linear_target, min(speed, 1.10)))
            reasons.append("safe-front-keep-forward")

        tight_side_clearance = min(
            left_clearance if left_clearance is not None else float("inf"),
            right_clearance if right_clearance is not None else float("inf"),
        )
        escape_right_sign = self.side_wall_escape_right_sign(left_clearance, right_clearance)
        if math.isfinite(tight_side_clearance) and tight_side_clearance < side_escape_clearance:
            linear_target = min(linear_target, 0.16)
            if abs(angular_target) < 0.16:
                angular_target = math.copysign(0.16, angular_target if abs(angular_target) > 1e-6 else (-1.0 if (right_clearance or 99.0) < (left_clearance or 99.0) else 1.0))
            reasons.append("tight-side-clearance-hard-slow")

        if (
            escape_right_sign != 0.0
            and math.isfinite(tight_side_clearance)
            and tight_side_clearance < side_escape_clearance
        ):
            escape_turn = -0.28 * escape_right_sign
            if abs(angular_target) < abs(escape_turn) or math.copysign(1.0, angular_target or escape_turn) != math.copysign(1.0, escape_turn):
                angular_target = escape_turn
            if front_clearance is not None and float(front_clearance) > (self.robot_front_stop_clearance() + 0.18):
                linear_target = min(max(linear_target, 0.16), min(self.args.max_linear, 0.24))
            else:
                linear_target = min(linear_target, 0.10)
            reasons.append("decisive-side-wall-escape")

        path_blocked, block_along, block_side = self.red_point_path_blocked(right, forward, pose=self.current_pose)
        if path_blocked:
            avoid_turn = 0.0
            if abs(block_side) > 0.08:
                avoid_turn = 1.0 if block_side > 0.0 else -1.0
            elif right != 0.0:
                avoid_turn = 1.0 if right > 0.0 else -1.0

            if block_along is not None and block_along < 0.80:
                linear_target = min(linear_target, 0.08)
            else:
                linear_target = min(linear_target, 0.18)
            if avoid_turn != 0.0:
                angular_target = math.copysign(max(abs(angular_target), 0.18), avoid_turn)
            reasons.append("redpoint-hard-avoidance")

        if path_blocked and (block_along is None or block_along < 1.15) and forward < 0.9:
            linear_target = 0.0
            if abs(angular_target) < 0.18:
                angular_target = math.copysign(
                    0.18,
                    angular_target if abs(angular_target) > 1e-6 else (-1.0 if block_side > 0.0 else 1.0),
                )
            reasons.append("reject-short-blocked-command")

        if current_applied is not None:
            linear_target = clamp(
                (0.68 * float(current_applied["linear_mps"])) + (0.32 * linear_target),
                float(current_applied["linear_mps"]) - self.args.max_linear_step,
                float(current_applied["linear_mps"]) + self.args.max_linear_step,
            )
            angular_target = clamp(
                (0.72 * float(current_applied["angular_radps"])) + (0.28 * angular_target),
                float(current_applied["angular_radps"]) - self.args.max_angular_step,
                float(current_applied["angular_radps"]) + self.args.max_angular_step,
            )
            reasons.append("rate-limit-cmd")

        duration_target = clamp(requested_duration, 0.0, self.args.max_duration)
        return {
            "linear_mps": max(0.0, linear_target),
            "angular_radps": angular_target,
            "duration_s": duration_target,
        }, reasons

    def waypoint_to_command(
        self,
        waypoint: Dict[str, float],
        snapshot: PerceptionSnapshot,
        requested_duration: float,
    ) -> Tuple[Dict[str, float], List[str]]:
        current_applied = self.active_execution.applied if self.active_execution is not None else None
        return self.controller_command_for_waypoint(
            waypoint,
            snapshot.obstacle_metrics,
            requested_duration=requested_duration,
            current_applied=current_applied,
        )

    def launch_planning_request(self):
        if not self.auto_enabled:
            return
        if self.goal_completed:
            return
        if self.bootstrap_active is not None:
            return
        if self.pending_future is not None:
            return
        if len(self.execution_queue) >= self.args.max_waypoint_queue:
            return
        now = time.monotonic()
        dynamic_next_query_time = self.next_query_time
        if self.active_execution is not None:
            remaining = max(0.0, self.active_execution.end_monotonic - now)
            base_interval = 1.0 / max(0.1, self.args.inference_hz)
            if len(self.execution_queue) == 0 and remaining <= self.args.prefetch_lead_s:
                dynamic_next_query_time = min(dynamic_next_query_time, now + (0.35 * base_interval))
            elif len(self.execution_queue) <= 1 and remaining <= (self.args.prefetch_lead_s * 1.5):
                dynamic_next_query_time = min(dynamic_next_query_time, now + (0.60 * base_interval))
        if now < dynamic_next_query_time:
            return

        snapshot = self.capture_snapshot()
        if snapshot is None:
            if self.args.goal_frame == "start_local" and not self.start_local_goal_anchor_ready(self.current_pose):
                self.api_status = "waiting-start-anchor"
                self.last_error = "waiting for IMU heading to anchor start_local goal"
            if self.active_execution is None:
                self.maybe_start_bootstrap_localization()
            return

        if self.goal_is_complete(snapshot.global_goal_distance):
            self.maybe_mark_goal_complete(snapshot.pose, reason="goal-complete-before-query")
            return

        self.pending_snapshot = snapshot
        self.pending_future = self.executor_pool.submit(self.request_drive_command, snapshot)
        self.api_status = "querying-next" if self.active_execution is not None else "querying"
        self.last_error = ""
        base_interval = 1.0 / max(0.1, self.args.inference_hz)
        if self.active_execution is not None and len(self.execution_queue) == 0:
            self.next_query_time = now + (0.45 * base_interval)
        elif self.active_execution is not None and len(self.execution_queue) <= 1:
            self.next_query_time = now + (0.70 * base_interval)
        else:
            self.next_query_time = now + base_interval

    def poll_planning_result(self):
        if self.pending_future is None:
            return
        if not self.pending_future.done():
            return

        snapshot = self.pending_snapshot
        future = self.pending_future
        self.pending_snapshot = None
        self.pending_future = None

        try:
            result = future.result()
            parsed = result["parsed"]
            self.latest_reasoning = parsed["reasoning_summary"]
            self.latest_risk = parsed["risk_level"]
            self.latest_action_text = parsed["action_text"]
            self.last_error = ""
        except Exception as exc:
            self.api_status = "error"
            self.last_error = f"api failure: {exc}"
            self.latest_action_text = "ACTION: [0.0, 0.0, 0.0]"
            self.get_logger().warning(self.last_error)
            if snapshot is not None:
                self.log_step_event(
                    {
                        "kind": "error",
                        "timestamp": time.time(),
                        "step_index": snapshot.step_index,
                        "error": str(exc),
                        "goal_local_right_m": snapshot.goal_local_right,
                        "goal_local_forward_m": snapshot.goal_local_forward,
                    }
                )
            return

        if self.ignore_next_result:
            self.ignore_next_result = False
            if self.goal_completed:
                self.api_status = "complete"
                self.last_error = ""
            else:
                self.api_status = "stopped"
                self.last_error = "pending action ignored after manual stop"
            return

        if snapshot is None:
            return

        execution = self.build_execution_state(parsed, result, snapshot)
        if self.active_execution is not None:
            current_mode = str(self.active_execution.snapshot.goal_state.get("local_mode", "translate"))
            next_mode = str(execution.snapshot.goal_state.get("local_mode", "translate"))
            if (
                next_mode == "rotate_to_global"
                and current_mode != "rotate_to_global"
                and float(self.active_execution.applied.get("linear_mps", 0.0)) > 0.05
            ):
                self.execution_queue.clear()
                self.stop_ramp = None
                self.finalize_execution("superseded-for-heading-alignment")
                self.activate_execution_state(execution)
                self.api_status = "heading-alignment"
                self.last_error = ""
                return
            self.enqueue_execution(execution)
            self.api_status = "streaming-waypoints"
            self.last_error = ""
            return

        self.activate_execution_state(execution)

    def finalize_execution(self, status: str):
        execution = self.active_execution
        if execution is None:
            return

        end_pose = self.current_pose
        if end_pose is None:
            end_pose = execution.start_pose
        end_pose_copy = Pose2D(end_pose.stamp, end_pose.x, end_pose.y, end_pose.yaw)
        delta_right, delta_forward, delta_yaw = pose_delta_local(execution.start_pose, end_pose_copy)
        obstacle_memory_before = obstacle_memory_summary(execution.snapshot.obstacle_metrics)
        obstacle_memory_after = obstacle_memory_summary(self.last_obstacle_metrics)

        record = {
            "step_index": execution.step_index,
            "timestamp": time.time(),
            "status": status,
            "risk_level": execution.risk_level,
            "reasoning_summary": execution.reasoning_summary,
            "action_text": execution.action_text,
            "waypoint": dict(execution.waypoint),
            "world_waypoint": dict(execution.world_waypoint),
            "requested": dict(execution.requested),
            "applied": dict(execution.applied),
            "safety_override": execution.safety_override,
            "start_pose": asdict(execution.start_pose),
            "end_pose": asdict(end_pose_copy),
            "goal_local_right_m": execution.snapshot.goal_local_right,
            "goal_local_forward_m": execution.snapshot.goal_local_forward,
            "goal_distance_m": execution.snapshot.goal_distance,
            "goal_bearing_deg": execution.snapshot.goal_bearing_deg,
            "global_goal_right_m": execution.snapshot.global_goal_right,
            "global_goal_forward_m": execution.snapshot.global_goal_forward,
            "global_goal_distance_m": execution.snapshot.global_goal_distance,
            "global_goal_bearing_deg": execution.snapshot.global_goal_bearing_deg,
            "goal_frame": self.args.goal_frame,
            "goal_input_x": self.goal_input_x,
            "goal_input_y": self.goal_input_y,
            "goal_world_x": self.goal_x,
            "goal_world_y": self.goal_y,
            "goal_state": copy.deepcopy(execution.snapshot.goal_state),
            "delta_local_right_m": delta_right,
            "delta_local_forward_m": delta_forward,
            "delta_yaw_deg": math.degrees(delta_yaw),
            "front_clearance_before_m": execution.snapshot.obstacle_metrics.get("front_clearance_m"),
            "front_clearance_after_m": self.last_obstacle_metrics.get("front_clearance_m"),
            "obstacle_memory_before": obstacle_memory_before,
            "obstacle_memory_after": obstacle_memory_after,
            "map_memory_summary": copy.deepcopy(execution.snapshot.map_memory_summary),
            "planner_hint": copy.deepcopy(execution.snapshot.planner_hint),
            "route_plan": copy.deepcopy(execution.snapshot.route_plan),
            "pose_diagnostics": copy.deepcopy(execution.snapshot.pose_diagnostics),
        }
        self.command_history.append(record)
        self.previous_step_context = {
            "rgb_bgr": execution.snapshot.rgb_bgr.copy(),
            "depth_vis": execution.snapshot.depth_vis.copy(),
            "bev_img": execution.snapshot.bev_img.copy(),
            "pose": Pose2D(
                execution.snapshot.pose.stamp,
                execution.snapshot.pose.x,
                execution.snapshot.pose.y,
                execution.snapshot.pose.yaw,
            ),
            "goal_local_right": execution.snapshot.goal_local_right,
            "goal_local_forward": execution.snapshot.goal_local_forward,
            "goal_distance": execution.snapshot.goal_distance,
            "goal_bearing_deg": execution.snapshot.goal_bearing_deg,
            "global_goal_right": execution.snapshot.global_goal_right,
            "global_goal_forward": execution.snapshot.global_goal_forward,
            "global_goal_distance": execution.snapshot.global_goal_distance,
            "global_goal_bearing_deg": execution.snapshot.global_goal_bearing_deg,
            "goal_state": copy.deepcopy(execution.snapshot.goal_state),
            "waypoint": dict(execution.waypoint),
            "world_waypoint": dict(execution.world_waypoint),
            "applied": dict(execution.applied),
            "requested": dict(execution.requested),
            "status": status,
            "delta_local_right_m": delta_right,
            "delta_local_forward_m": delta_forward,
            "delta_yaw_deg": math.degrees(delta_yaw),
            "safety_override": execution.safety_override,
            "reasoning_summary": execution.reasoning_summary,
            "action_text": execution.action_text,
            "front_clearance_before_m": execution.snapshot.obstacle_metrics.get("front_clearance_m"),
            "front_clearance_after_m": self.last_obstacle_metrics.get("front_clearance_m"),
            "obstacle_memory_before": obstacle_memory_before,
            "obstacle_memory_after": obstacle_memory_after,
            "map_memory_summary": copy.deepcopy(execution.snapshot.map_memory_summary),
            "planner_hint": copy.deepcopy(execution.snapshot.planner_hint),
            "route_plan": copy.deepcopy(execution.snapshot.route_plan),
            "pose_diagnostics": copy.deepcopy(execution.snapshot.pose_diagnostics),
        }
        self.previous_step_contexts.appendleft(self.previous_step_context)
        self.save_step_bundle(record, execution)
        self.log_step_event(
            {
                "kind": "step",
                "record": record,
                "raw_response": execution.raw_response,
            }
        )

        self.active_execution = None
        self.api_status = "idle" if self.auto_enabled else "paused"
        self.latest_action_text = record["action_text"]

    def log_step_event(self, payload: Dict[str, object]):
        with self.session_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def draw_text_block(
        self,
        canvas: np.ndarray,
        lines: List[str],
        x: int,
        y: int,
        line_h: int = 20,
        color: Tuple[int, int, int] = (220, 220, 220),
        scale: float = 0.5,
        max_width: Optional[int] = None,
        max_lines: Optional[int] = None,
        max_bottom: Optional[int] = None,
    ):
        drawn = 0
        for i, line in enumerate(lines):
            wrapped = [line]
            if max_width is not None:
                wrapped = self.wrap_text_to_width(line, scale, max_width)
            for wrapped_line in wrapped:
                if max_lines is not None and drawn >= max_lines:
                    return drawn
                baseline_y = y + (drawn * line_h)
                if max_bottom is not None and baseline_y > max_bottom:
                    return drawn
                cv2.putText(
                    canvas,
                    wrapped_line,
                    (x, baseline_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    scale,
                    color,
                    1,
                    cv2.LINE_AA,
                )
                drawn += 1
        return drawn

    def wrap_text_to_width(self, text: str, scale: float, max_width: int) -> List[str]:
        if max_width <= 0:
            return [text]
        if not text:
            return [""]

        wrapped: List[str] = []
        paragraphs = textwrap.wrap(text, width=120) or [text]
        for paragraph in paragraphs:
            words = paragraph.split()
            if not words:
                wrapped.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                width_px = cv2.getTextSize(candidate, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0]
                if width_px <= max_width:
                    current = candidate
                else:
                    wrapped.append(current)
                    current = word
            wrapped.append(current)
        return wrapped

    def compose_top_scene_from_images(self, rgb_bgr: np.ndarray, depth_vis: np.ndarray, bev_img: np.ndarray) -> np.ndarray:
        right = bev_img
        right_h = right.shape[0]
        top_h = right_h // 2
        bottom_h = right_h - top_h
        left_top = self._make_labeled_panel(rgb_bgr, "RGB", self.left_panel_width, top_h)
        left_bottom = self._make_labeled_panel(depth_vis, "DEPTH", self.left_panel_width, bottom_h)
        left = np.vstack((left_top, left_bottom))
        canvas = np.hstack((left, right))
        cv2.rectangle(canvas, (0, 0), (canvas.shape[1] - 1, canvas.shape[0] - 1), (90, 90, 90), 1)
        return canvas

    def draw_info_panel(
        self,
        width: int,
        height: int,
        pose: Optional[Pose2D],
        local_goal: Tuple[float, float, float, float],
        global_goal: Tuple[float, float, float, float],
        obstacle_metrics: Dict[str, object],
        current_cmd: Dict[str, float],
    ) -> np.ndarray:
        panel = np.zeros((height, width, 3), dtype=np.uint8)
        panel[:] = (24, 24, 24)
        cv2.rectangle(panel, (0, 0), (width - 1, height - 1), (80, 80, 80), 1)
        cv2.putText(panel, "Status", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (235, 235, 235), 2, cv2.LINE_AA)

        db_line = f"DB: {'ready' if self.db_exists else 'missing'} ({human_bytes(self.db_size) if self.db_exists else 'n/a'})"
        header_lines = [
            f"API: {self.api_status}",
            f"Auto: {'on' if self.auto_enabled else 'paused'}",
            f"Model: {self.args.model}",
            f"Control: {self.args.control_mode}",
            f"Pose source: {self.args.pose_source}",
            f"Yaw source: {self.args.yaw_source}",
            db_line,
        ]
        goal_lines = []
        local_goal_right, local_goal_forward, local_goal_distance, local_goal_bearing_deg = local_goal
        global_goal_right, global_goal_forward, global_goal_distance, global_goal_bearing_deg = global_goal
        if pose is not None:
            goal_lines.extend(
                [
                    f"Pose: x={pose.x:.3f} y={pose.y:.3f} yaw={math.degrees(pose.yaw):.1f}deg",
                    f"Local goal: r={local_goal_right:.3f} f={local_goal_forward:.3f} d={local_goal_distance:.3f} b={local_goal_bearing_deg:.1f}deg",
                    f"Global goal: r={global_goal_right:.3f} f={global_goal_forward:.3f} d={global_goal_distance:.3f} b={global_goal_bearing_deg:.1f}deg",
                ]
            )
        else:
            goal_lines.append("Pose: waiting")

        front_clearance = obstacle_metrics.get("front_clearance_m")
        nearest_distance = obstacle_metrics.get("nearest_distance_m")
        nearest_heading = obstacle_metrics.get("nearest_heading_deg")
        sectors = obstacle_metrics.get("sectors", {})
        corridor = obstacle_metrics.get("corridor", {})
        memory_summary = self.build_map_memory_summary(pose) if pose is not None else {"point_count": 0, "front_memory_clearance_m": None}
        planner_best = None
        if pose is not None:
            planner_best = self.build_planner_hint(
                pose,
                goal_right=global_goal_right,
                goal_forward=global_goal_forward,
                goal_distance=global_goal_distance,
                obstacle_metrics=obstacle_metrics,
            ).get("best")
        active_waypoint = {"right_m": 0.0, "forward_m": 0.0, "speed_mps": 0.0}
        if self.active_execution is not None and pose is not None:
            active_waypoint = self.execution_waypoint_local(self.active_execution, pose)
        body_lines = [
            [
                f"Nearest: {nearest_distance} m @ {nearest_heading} deg",
                f"Front clearance: {front_clearance}",
                f"Sectors: L={sectors.get('left', {}).get('label', 'n/a')}, "
                f"C={sectors.get('center', {}).get('label', 'n/a')}, "
                f"R={sectors.get('right', {}).get('label', 'n/a')}",
                f"Corridor: {corridor.get('status', 'n/a')} ctr={corridor.get('center_right_m')} width={corridor.get('width_m')}",
                f"Memory: pts={memory_summary.get('point_count')} front={memory_summary.get('front_memory_clearance_m')}",
                (
                    f"Planner: {planner_best.get('label')} r={planner_best.get('right_m'):.2f} "
                    f"f={planner_best.get('forward_m'):.2f} clear={planner_best.get('min_clearance_m')}"
                    if planner_best is not None
                    else "Planner: n/a"
                ),
                f"Queue: {len(self.execution_queue)} waypoint(s)",
                f"Waypoint: r={active_waypoint['right_m']:.2f} f={active_waypoint['forward_m']:.2f} s={active_waypoint['speed_mps']:.2f}",
                f"Goal state: src={getattr(self, 'local_goal_source', 'pending')} reason={truncate(getattr(self, 'local_goal_reason', ''), 44)}",
                f"Cmd: [{current_cmd['linear_mps']:.3f}, {current_cmd['angular_radps']:.3f}, {current_cmd['duration_s']:.3f}]",
                f"Reason: {truncate(self.latest_reasoning, 90) or 'n/a'}",
                f"Error: {truncate(self.last_error, 95) or 'none'}",
            ]
        ][0]
        body_y = 54
        footer_y = height - 66
        used = self.draw_text_block(
            panel,
            header_lines,
            12,
            body_y,
            line_h=18,
            max_width=width - 24,
            max_lines=7,
            max_bottom=footer_y - 178,
        )
        goal_y = body_y + (used * 18) + 6
        used += self.draw_text_block(
            panel,
            goal_lines,
            12,
            goal_y,
            line_h=19,
            scale=0.5,
            color=(120, 240, 120),
            max_width=width - 24,
            max_lines=3,
            max_bottom=footer_y - 140,
        )
        section_y = body_y + (used * 18) + 10
        used += self.draw_text_block(
            panel,
            body_lines[:-2],
            12,
            section_y,
            line_h=18,
            scale=0.47,
            max_width=width - 24,
            max_lines=8,
            max_bottom=footer_y - 94,
        )
        reason_y = body_y + (used * 18) + 8
        used += self.draw_text_block(
            panel,
            [f"Reason: {self.latest_reasoning or 'n/a'}"],
            12,
            reason_y,
            line_h=18,
            scale=0.46,
            color=(210, 210, 210),
            max_width=width - 24,
            max_lines=4,
            max_bottom=footer_y - 62,
        )
        error_y = body_y + (used * 21) + 12
        self.draw_text_block(
            panel,
            [f"Error: {self.last_error or 'none'}"],
            12,
            error_y,
            line_h=18,
            scale=0.46,
            color=(180, 180, 180),
            max_width=width - 24,
            max_lines=4,
            max_bottom=footer_y - 24,
        )
        self.draw_text_block(
            panel,
            ["Keys: q/ESC quit", "space stop", "p auto pause", "s snapshot"],
            12,
            footer_y,
            line_h=18,
            color=(180, 180, 180),
            max_bottom=height - 12,
        )
        return panel

    def draw_trajectory_panel(self, width: int, height: int, pose: Optional[Pose2D]) -> np.ndarray:
        panel = np.zeros((height, width, 3), dtype=np.uint8)
        panel[:] = (18, 18, 18)
        cv2.rectangle(panel, (0, 0), (width - 1, height - 1), (80, 80, 80), 1)
        cv2.putText(panel, "Local Trajectory", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (235, 235, 235), 2, cv2.LINE_AA)

        origin_x = width // 2
        origin_y = height - 32
        ppm = 50.0

        for meter in range(1, 6):
            y = int(origin_y - meter * ppm)
            if y > 28:
                cv2.line(panel, (30, y), (width - 30, y), (45, 45, 45), 1)
                cv2.putText(panel, f"{meter}m", (6, y + 4), cv2.FONT_HERSHEY_PLAIN, 0.9, (140, 140, 140), 1)
            x_left = int(origin_x - meter * ppm)
            x_right = int(origin_x + meter * ppm)
            if x_left > 30:
                cv2.line(panel, (x_left, 28), (x_left, origin_y), (38, 38, 38), 1)
            if x_right < width - 30:
                cv2.line(panel, (x_right, 28), (x_right, origin_y), (38, 38, 38), 1)

        cv2.circle(panel, (origin_x, origin_y), 6, (0, 255, 255), -1)
        cv2.arrowedLine(panel, (origin_x, origin_y), (origin_x, origin_y - 38), (0, 255, 255), 2, tipLength=0.2)

        if pose is not None:
            local_goal_right, local_goal_forward, _, _ = self.compute_goal_local(pose)
            global_goal_right, global_goal_forward, _, _ = self.compute_global_goal_local(pose)
            local_x = int(origin_x + local_goal_right * ppm)
            local_y = int(origin_y - local_goal_forward * ppm)
            if 0 <= local_x < width and 28 <= local_y < height:
                cv2.circle(panel, (local_x, local_y), 7, (0, 165, 255), -1)
                cv2.putText(panel, "local", (local_x + 8, local_y - 4), cv2.FONT_HERSHEY_PLAIN, 1.0, (0, 210, 255), 1)
            gx = int(origin_x + global_goal_right * ppm)
            gy = int(origin_y - global_goal_forward * ppm)
            if 0 <= gx < width and 28 <= gy < height:
                cv2.circle(panel, (gx, gy), 7, (80, 220, 80), -1)
                cv2.putText(panel, "global", (gx + 8, gy - 4), cv2.FONT_HERSHEY_PLAIN, 1.0, (120, 240, 120), 1)

            points: List[Tuple[int, int]] = [(origin_x, origin_y)]
            for record in self.command_history:
                end_pose = record["end_pose"]
                dx = float(end_pose["x"]) - pose.x
                dy = float(end_pose["y"]) - pose.y
                right, forward = world_to_robot(dx, dy, pose.yaw)
                px = int(origin_x + right * ppm)
                py = int(origin_y - forward * ppm)
                points.append((px, py))
            if len(points) > 1:
                for point in points[1:]:
                    cv2.circle(panel, point, 4, (0, 180, 255), -1)
                cv2.polylines(panel, [np.asarray(points, dtype=np.int32)], False, (0, 180, 255), 2, cv2.LINE_AA)
        return panel

    def draw_history_panel(self, width: int, height: int) -> np.ndarray:
        panel = np.zeros((height, width, 3), dtype=np.uint8)
        panel[:] = (22, 22, 22)
        cv2.rectangle(panel, (0, 0), (width - 1, height - 1), (80, 80, 80), 1)
        cv2.putText(panel, "Recent Commands", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (235, 235, 235), 2, cv2.LINE_AA)
        if not self.command_history:
            self.draw_text_block(panel, ["No completed steps yet."], 12, 58)
            return panel

        y = 54
        for record in list(self.command_history)[-HISTORY_WINDOW:]:
            applied = record["applied"]
            waypoint = record.get("waypoint", {})
            line_1 = (
                f"#{record['step_index']} {record['status']} "
                f"[{applied['linear_mps']:.2f}, {applied['angular_radps']:.2f}, {applied['duration_s']:.2f}] "
                f"{record['risk_level']}"
            )
            line_2 = (
                f"wp r={waypoint.get('right_m', 0.0):.2f} "
                f"f={waypoint.get('forward_m', 0.0):.2f} "
                f"s={waypoint.get('speed_mps', 0.0):.2f}"
            )
            line_3 = (
                f"delta r={record['delta_local_right_m']:.2f} "
                f"f={record['delta_local_forward_m']:.2f} "
                f"yaw={record['delta_yaw_deg']:.1f}deg"
            )
            line_4 = f"safety={record['safety_override']}"
            line_5 = f"reason={record['reasoning_summary']}"
            used = self.draw_text_block(
                panel,
                [line_1, line_2, line_3, line_4, line_5],
                12,
                y,
                line_h=16,
                scale=0.43,
                max_width=width - 24,
                max_lines=7,
                max_bottom=height - 18,
            )
            y += max(56, used * 16 + 12)
            if y > height - 56:
                break
        return panel

    def compose_dashboard(
        self,
        rgb_bgr: np.ndarray,
        depth_vis: np.ndarray,
        bev_img: np.ndarray,
        pose: Optional[Pose2D],
        obstacle_metrics: Dict[str, object],
    ) -> np.ndarray:
        top = self.compose_top_scene_from_images(rgb_bgr, depth_vis, bev_img)
        width = top.shape[1]
        bottom_h = 430

        if pose is not None:
            local_goal = self.compute_goal_local(pose)
            global_goal = self.compute_global_goal_local(pose)
        else:
            local_goal = (0.0, 0.0, 0.0, 0.0)
            global_goal = (0.0, 0.0, 0.0, 0.0)

        current_cmd = {"linear_mps": 0.0, "angular_radps": 0.0, "duration_s": 0.0}
        if self.stop_ramp is not None:
            current_cmd = {
                "linear_mps": float(self.last_published_linear_mps),
                "angular_radps": float(self.last_published_angular_radps),
                "duration_s": 0.0,
            }
        elif self.active_execution is not None:
            current_cmd = dict(self.active_execution.applied)
        elif self.bootstrap_active is not None:
            current_cmd = dict(self.bootstrap_active.applied)

        info_w = int(width * 0.38)
        traj_w = int(width * 0.27)
        hist_w = width - info_w - traj_w
        info = self.draw_info_panel(info_w, bottom_h, pose, local_goal, global_goal, obstacle_metrics, current_cmd)
        traj = self.draw_trajectory_panel(traj_w, bottom_h, pose)
        hist = self.draw_history_panel(hist_w, bottom_h)
        bottom = np.hstack((info, traj, hist))
        return np.vstack((top, bottom))

    def save_image(self, path: Path, image: np.ndarray):
        cv2.imwrite(str(path), image)

    def save_markdown(self, path: Path, text: str):
        path.write_text(text, encoding="utf-8")

    def build_prompt_markdown(
        self,
        execution: ExecutionState,
        image_paths: Dict[str, Path],
    ) -> str:
        prompt_debug = execution.prompt_debug
        image_notes = prompt_debug.get("image_notes", [])
        image_lines = "\n".join(f"- {line}" for line in image_notes) if image_notes else "- none"
        return textwrap.dedent(
            f"""\
            # Prompt Debug

            - step: {execution.step_index}
            - model: {self.args.model}
            - control_mode: {self.args.control_mode}
            - attempt: {prompt_debug.get('attempt')}
            - compact_prompt: {prompt_debug.get('compact_prompt')}
            - include_previous_bev: {prompt_debug.get('include_previous_bev')}

            ## Attached Images

            - current_rgb: {image_paths['rgb']}
            - current_depth: {image_paths['depth']}
            - current_bev: {image_paths['bev']}
            {image_lines}

            ## System Prompt

            ```text
            {prompt_debug.get('system_prompt', '')}
            ```

            ## User Prompt

            ```text
            {prompt_debug.get('prompt_text', '')}
            ```
            """
        )

    def build_response_markdown(self, execution: ExecutionState, record: Dict[str, object]) -> str:
        return textwrap.dedent(
            f"""\
            # Response Debug

            - step: {execution.step_index}
            - model: {self.args.model}
            - action_text: {execution.action_text}
            - safety_override: {execution.safety_override}

            ## Parsed Command

            ```json
            {json.dumps(execution.requested, indent=2, ensure_ascii=False)}
            ```

            ## Applied Command

            ```json
            {json.dumps(execution.applied, indent=2, ensure_ascii=False)}
            ```

            ## Raw Output Text

            ```text
            {execution.raw_output_text}
            ```

            ## Response Metadata

            ```json
            {json.dumps(execution.raw_response, indent=2, ensure_ascii=False)}
            ```

            ## Step Record

            ```json
            {json.dumps(record, indent=2, ensure_ascii=False)}
            ```
            """
        )

    def save_step_bundle(self, record: Dict[str, object], execution: ExecutionState):
        prefix = f"step_{execution.step_index:04d}"
        rgb_path = self.session_dir / f"{prefix}_rgb.png"
        depth_path = self.session_dir / f"{prefix}_depth.png"
        bev_path = self.session_dir / f"{prefix}_bev.png"
        dashboard_path = self.session_dir / f"{prefix}_dashboard.png"
        prompt_md_path = self.session_dir / f"{prefix}_prompt.md"
        response_md_path = self.session_dir / f"{prefix}_response.md"
        json_path = self.session_dir / f"{prefix}.json"

        dashboard = self.compose_dashboard(
            execution.snapshot.rgb_bgr,
            execution.snapshot.depth_vis,
            execution.snapshot.bev_img,
            execution.snapshot.pose,
            execution.snapshot.obstacle_metrics,
        )

        self.save_image(rgb_path, execution.snapshot.rgb_bgr)
        self.save_image(depth_path, execution.snapshot.depth_vis)
        self.save_image(bev_path, execution.snapshot.bev_img)
        self.save_image(dashboard_path, dashboard)
        self.save_markdown(
            prompt_md_path,
            self.build_prompt_markdown(
                execution,
                {
                    "rgb": rgb_path,
                    "depth": depth_path,
                    "bev": bev_path,
                    "dashboard": dashboard_path,
                },
            ),
        )
        self.save_markdown(response_md_path, self.build_response_markdown(execution, record))

        payload = {
            "timestamp": record["timestamp"],
            "model": self.args.model,
            "raw_output_text": execution.raw_output_text,
            "raw_response": execution.raw_response,
            "prompt_debug": execution.prompt_debug,
            "record": record,
            "snapshot": {
                "capture_time": execution.snapshot.capture_time,
                "pose": asdict(execution.snapshot.pose),
                "goal_frame": self.args.goal_frame,
                "goal_input_x": self.goal_input_x,
                "goal_input_y": self.goal_input_y,
                "goal_world_x": self.goal_x,
                "goal_world_y": self.goal_y,
                "goal_local_right_m": execution.snapshot.goal_local_right,
                "goal_local_forward_m": execution.snapshot.goal_local_forward,
                "goal_distance_m": execution.snapshot.goal_distance,
                "goal_bearing_deg": execution.snapshot.goal_bearing_deg,
                "global_goal_right_m": execution.snapshot.global_goal_right,
                "global_goal_forward_m": execution.snapshot.global_goal_forward,
                "global_goal_distance_m": execution.snapshot.global_goal_distance,
                "global_goal_bearing_deg": execution.snapshot.global_goal_bearing_deg,
                "goal_state": execution.snapshot.goal_state,
                "obstacle_metrics": execution.snapshot.obstacle_metrics,
                "map_memory_summary": execution.snapshot.map_memory_summary,
                "planner_hint": execution.snapshot.planner_hint,
                "pose_diagnostics": execution.snapshot.pose_diagnostics,
                "stale_info": execution.snapshot.stale_info,
                "history_summary": execution.snapshot.history_summary,
            },
            "files": {
                "rgb": str(rgb_path),
                "depth": str(depth_path),
                "bev": str(bev_path),
                "dashboard": str(dashboard_path),
                "prompt_md": str(prompt_md_path),
                "response_md": str(response_md_path),
            },
        }
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

    def save_manual_snapshot(self):
        snapshot = self.capture_snapshot()
        if snapshot is None:
            self.last_error = "snapshot skipped: data not ready"
            return
        self.manual_snapshot_counter += 1
        prefix = f"manual_{self.manual_snapshot_counter:04d}"
        dashboard = self.compose_dashboard(snapshot.rgb_bgr, snapshot.depth_vis, snapshot.bev_img, snapshot.pose, snapshot.obstacle_metrics)
        rgb_path = self.session_dir / f"{prefix}_rgb.png"
        depth_path = self.session_dir / f"{prefix}_depth.png"
        bev_path = self.session_dir / f"{prefix}_bev.png"
        dashboard_path = self.session_dir / f"{prefix}_dashboard.png"
        json_path = self.session_dir / f"{prefix}.json"
        self.save_image(rgb_path, snapshot.rgb_bgr)
        self.save_image(depth_path, snapshot.depth_vis)
        self.save_image(bev_path, snapshot.bev_img)
        self.save_image(dashboard_path, dashboard)
        payload = {
            "kind": "manual_snapshot",
            "timestamp": time.time(),
            "pose": asdict(snapshot.pose),
            "goal_frame": self.args.goal_frame,
            "goal_input_x": self.goal_input_x,
            "goal_input_y": self.goal_input_y,
            "goal_world_x": self.goal_x,
            "goal_world_y": self.goal_y,
            "goal_local_right_m": snapshot.goal_local_right,
            "goal_local_forward_m": snapshot.goal_local_forward,
            "goal_distance_m": snapshot.goal_distance,
            "goal_bearing_deg": snapshot.goal_bearing_deg,
            "global_goal_right_m": snapshot.global_goal_right,
            "global_goal_forward_m": snapshot.global_goal_forward,
            "global_goal_distance_m": snapshot.global_goal_distance,
            "global_goal_bearing_deg": snapshot.global_goal_bearing_deg,
            "goal_state": snapshot.goal_state,
            "obstacle_metrics": snapshot.obstacle_metrics,
            "map_memory_summary": snapshot.map_memory_summary,
            "planner_hint": snapshot.planner_hint,
            "pose_diagnostics": snapshot.pose_diagnostics,
            "files": {
                "rgb": str(rgb_path),
                "depth": str(depth_path),
                "bev": str(bev_path),
                "dashboard": str(dashboard_path),
            },
        }
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        self.log_step_event(payload)
        self.last_error = ""

    def process_key(self, key: int):
        if key in (27, ord("q"), ord("Q")):
            self.running = False
        elif key == ord(" "):
            self.request_emergency_stop("keyboard-stop")
        elif key in (ord("p"), ord("P")):
            self.auto_enabled = not self.auto_enabled
            self.api_status = "paused" if not self.auto_enabled else "idle"
        elif key in (ord("s"), ord("S")):
            self.save_manual_snapshot()

    def current_dashboard(self) -> np.ndarray:
        bev_img = self.build_bev()
        obstacle_metrics = self.analyze_obstacles()
        self.last_obstacle_metrics = obstacle_metrics
        if self.rgb_bgr is None:
            rgb_bgr = np.zeros((480, 640, 3), dtype=np.uint8)
        else:
            rgb_bgr = self.rgb_bgr
        if self.depth_vis is None:
            depth_vis = np.zeros_like(rgb_bgr)
        else:
            depth_vis = self.depth_vis
        return self.compose_dashboard(rgb_bgr, depth_vis, bev_img, self.current_pose, obstacle_metrics)

    def shutdown(self):
        self.running = False
        if self.pending_future is not None:
            self.pending_future.cancel()
            self.pending_future = None
        self.execution_queue.clear()
        self.stop_robot(immediate=True)
        self.executor_pool.shutdown(wait=False, cancel_futures=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenAI BEV zero-shot autodrive dashboard for Isaac Sim")
    parser.add_argument("--rgb-topic", default=os.getenv("RGB_TOPIC", DEFAULT_RGB_TOPIC))
    parser.add_argument("--depth-topic", default=os.getenv("DEPTH_TOPIC", DEFAULT_DEPTH_TOPIC))
    parser.add_argument("--camera-info-topic", default=os.getenv("CAMERA_INFO_TOPIC", DEFAULT_CAMERA_INFO_TOPIC))
    parser.add_argument("--depth-scale", type=float, default=float(os.getenv("DEPTH_SCALE", "0.001")))
    parser.add_argument("--depth-min", type=float, default=float(os.getenv("DEPTH_MIN", "0.2")))
    parser.add_argument("--depth-max", type=float, default=float(os.getenv("DEPTH_MAX", "8.0")))
    parser.add_argument("--max-forward", type=float, default=float(os.getenv("BEV_MAX_FORWARD", "6.0")))
    parser.add_argument("--max-side", type=float, default=float(os.getenv("BEV_MAX_SIDE", "3.0")))
    parser.add_argument("--stride", type=int, default=int(os.getenv("BEV_STRIDE", "4")))
    parser.add_argument("--camera-height", type=float, default=float(os.getenv("CAMERA_HEIGHT", "0.0")))
    parser.add_argument("--floor-tolerance", type=float, default=float(os.getenv("FLOOR_TOLERANCE", "0.08")))
    parser.add_argument("--auto-floor-bottom-ratio", type=float, default=float(os.getenv("AUTO_FLOOR_BOTTOM_RATIO", "0.22")))
    parser.add_argument("--auto-floor-percentile", type=float, default=float(os.getenv("AUTO_FLOOR_PERCENTILE", "85")))
    parser.add_argument("--grid-step", type=float, default=float(os.getenv("BEV_GRID_STEP", "0.5")))
    parser.add_argument("--ppm", type=float, default=float(os.getenv("BEV_PPM", "90")))
    parser.add_argument("--left-panel-width", type=int, default=int(os.getenv("LEFT_PANEL_WIDTH", "480")))
    parser.add_argument("--bev-render-mode", choices=["dots", "cloud"], default=os.getenv("BEV_RENDER_MODE", "dots"))
    parser.add_argument("--cloud-point-size", type=int, default=int(os.getenv("CLOUD_POINT_SIZE", "2")))
    parser.add_argument("--ego-radius", type=float, default=float(os.getenv("EGO_RADIUS", "0.30")))
    parser.add_argument("--fps", type=float, default=float(os.getenv("BEV_FPS", "15")))
    parser.add_argument("--goal-x", type=float, help="world x, or legacy start_local robot-right")
    parser.add_argument("--goal-y", type=float, help="world y, or legacy start_local robot-forward")
    parser.add_argument("--goal-right", type=float, help="start_local robot-right in meters")
    parser.add_argument("--goal-forward", type=float, help="start_local robot-forward in meters")
    parser.add_argument("--goal-frame", choices=["world", "start_local"], default=os.getenv("GOAL_FRAME", "start_local"))
    parser.add_argument("--pose-source", choices=["cmd_vel", "imu_cmd_vel", "odom"], default=os.getenv("POSE_SOURCE", "imu_cmd_vel"))
    parser.add_argument("--odom-topic", default="/rtabmap/odom")
    parser.add_argument("--odom-yaw-sign", type=int, choices=[-1, 1], default=int(os.getenv("ODOM_YAW_SIGN", "-1")))
    parser.add_argument("--cmd-linear-sign", type=int, choices=[-1, 1], default=int(os.getenv("CMD_LINEAR_SIGN", "-1")))
    parser.add_argument("--yaw-source", choices=["odom", "imu", "cmd_vel", "hybrid"], default=os.getenv("YAW_SOURCE", "hybrid"))
    parser.add_argument("--imu-topic", default=os.getenv("IMU_TOPIC", "/imu"))
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel")
    parser.add_argument("--database-path", default=str(CURRENT_DIR / "merged.db"))
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument("--control-mode", choices=["waypoint", "direct_cmd_vel"], default=os.getenv("CONTROL_MODE", "direct_cmd_vel"))
    parser.add_argument("--api-timeout", type=float, default=20.0)
    parser.add_argument("--api-max-output-tokens", type=int, default=480)
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "none", "low", "medium", "high", "xhigh"],
        default="none",
    )
    parser.add_argument("--inference-hz", type=float, default=10.0)
    parser.add_argument("--max-linear", type=float, default=1.15)
    parser.add_argument("--max-angular", type=float, default=0.45)
    parser.add_argument("--max-duration", type=float, default=3.6)
    parser.add_argument("--min-motion-duration", type=float, default=1.8)
    parser.add_argument("--prefetch-lead-s", type=float, default=1.2)
    parser.add_argument("--command-hold-s", type=float, default=1.5)
    parser.add_argument("--stop-ramp-s", type=float, default=0.4)
    parser.add_argument("--max-linear-step", type=float, default=0.16)
    parser.add_argument("--max-angular-step", type=float, default=0.08)
    parser.add_argument("--max-waypoint-queue", type=int, default=8)
    parser.add_argument("--waypoint-reach-m", type=float, default=0.45)
    parser.add_argument("--goal-complete-distance", type=float, default=1.0)
    parser.add_argument("--local-goal-lookahead-m", type=float, default=1.6)
    parser.add_argument("--local-goal-reach-m", type=float, default=0.45)
    parser.add_argument("--local-goal-hold-steps", type=int, default=6)
    parser.add_argument("--local-goal-min-forward-m", type=float, default=0.8)
    parser.add_argument("--rotate-local-goal-bearing-deg", type=float, default=95.0)
    parser.add_argument("--rotate-local-goal-radius-m", type=float, default=0.9)
    parser.add_argument("--rotate-release-bearing-deg", type=float, default=42.0)
    parser.add_argument("--rotate-release-forward-m", type=float, default=0.55)
    parser.add_argument("--robot-radius", type=float, default=0.35)
    parser.add_argument("--body-safety-buffer", type=float, default=0.18)
    parser.add_argument("--desired-clearance", type=float, default=1.0)
    parser.add_argument("--min-front-clearance", type=float, default=0.6)
    parser.add_argument("--stale-timeout", type=float, default=0.7)
    parser.add_argument("--execution-stale-grace-s", type=float, default=0.6)
    parser.add_argument("--memory-horizon-s", type=float, default=20.0)
    parser.add_argument("--memory-range-m", type=float, default=10.0)
    parser.add_argument("--memory-voxel-m", type=float, default=0.15)
    parser.add_argument("--detour-commit-s", type=float, default=4.5)
    parser.add_argument("--flip-clearance-margin", type=float, default=0.35)
    parser.add_argument("--reverse-escape-speed", type=float, default=0.12)
    parser.add_argument("--reverse-escape-duration", type=float, default=0.7)
    parser.add_argument("--reverse-escape-turn", type=float, default=0.18)
    parser.add_argument("--save-root", default=str(CURRENT_DIR / "runs"))
    return parser


def normalize_goal_args(args: argparse.Namespace, parser: argparse.ArgumentParser):
    if args.goal_frame == "start_local":
        if args.goal_right is not None or args.goal_forward is not None:
            if args.goal_right is None or args.goal_forward is None:
                parser.error("--goal-right and --goal-forward must be provided together for --goal-frame start_local")
            args.goal_x = float(args.goal_right)
            args.goal_y = float(args.goal_forward)
        else:
            if args.goal_x is None or args.goal_y is None:
                parser.error(
                    "--goal-frame start_local requires either --goal-right/--goal-forward or legacy --goal-x/--goal-y"
                )
        return

    if args.goal_x is None or args.goal_y is None:
        parser.error("--goal-frame world requires --goal-x and --goal-y")
    if args.goal_right is not None or args.goal_forward is not None:
        parser.error("--goal-right/--goal-forward can only be used with --goal-frame start_local")


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    normalize_goal_args(args, parser)

    if not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY environment variable is required")

    rclpy.init()
    node = OpenAIDriveNode(args)
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    frame_period = 1.0 / max(args.fps, 1.0)
    last_frame = 0.0

    try:
        while rclpy.ok() and node.running:
            executor.spin_once(timeout_sec=0.01)
            node.poll_planning_result()
            node.launch_planning_request()

            now = time.time()
            if now - last_frame >= frame_period:
                dashboard = node.current_dashboard()
                cv2.imshow(WINDOW_NAME, dashboard)
                last_frame = now

            key = cv2.waitKey(1) & 0xFF
            if key != 255:
                node.process_key(key)
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
