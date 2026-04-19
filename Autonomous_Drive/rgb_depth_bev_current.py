#!/usr/bin/env python3
import argparse
import math
import os
import sys
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image


DEFAULT_RGB_TOPIC = "/rgb"
DEFAULT_DEPTH_TOPIC = "/depth"
DEFAULT_CAMERA_INFO_TOPIC = "/camera_info"


def parse_rgb_image(msg: Image):
    enc = msg.encoding.lower()
    if enc in ("rgb8", "bgr8"):
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
        if enc == "rgb8":
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return arr
    if enc in ("rgba8", "bgra8"):
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 4)
        if enc == "rgba8":
            arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        else:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        return arr
    if enc in ("mono8", "8uc1"):
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width)
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    raise ValueError(f"unsupported rgb encoding: {msg.encoding}")


def parse_depth_to_meters(msg: Image, depth_scale: float):
    enc = msg.encoding.lower()
    if enc in ("16uc1", "mono16"):
        depth = np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width)
        return depth.astype(np.float32) * depth_scale
    if enc in ("32fc1",):
        return np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
    raise ValueError(f"unsupported depth encoding: {msg.encoding}")


def depth_to_colormap(depth_m: np.ndarray, depth_min: float, depth_max: float):
    depth = np.nan_to_num(depth_m, nan=0.0, posinf=0.0, neginf=0.0)
    depth = np.clip(depth, depth_min, depth_max)
    if depth_max <= depth_min:
        depth_max = depth_min + 1.0
    norm = (depth - depth_min) / (depth_max - depth_min)
    u8 = (norm * 255.0).astype(np.uint8)
    return cv2.applyColorMap(u8, cv2.COLORMAP_TURBO)


class BirdEyeNode(Node):
    def __init__(
        self,
        rgb_topic: str,
        depth_topic: str,
        camera_info_topic: str,
        depth_scale: float,
        depth_min: float,
        depth_max: float,
        max_forward: float,
        max_side: float,
        stride: int,
        camera_height: float,
        floor_tolerance: float,
        auto_floor_bottom_ratio: float,
        auto_floor_percentile: float,
        grid_step: float,
        ppm: float,
        left_panel_width: int,
        bev_render_mode: str,
        cloud_point_size: int,
        ego_radius_m: float = 0.30,
    ):
        super().__init__("birdseye_depth_view_current")

        self.depth_scale = depth_scale
        self.depth_min = depth_min
        self.depth_max = depth_max
        self.max_forward = max_forward
        self.max_side = max_side
        self.stride = max(1, stride)
        self.camera_height = camera_height
        self.floor_tolerance = floor_tolerance
        self.auto_floor_bottom_ratio = min(max(auto_floor_bottom_ratio, 0.0), 0.8)
        self.auto_floor_percentile = min(max(auto_floor_percentile, 50.0), 99.0)
        self.grid_step = grid_step
        self.ppm = ppm
        self.left_panel_width = max(220, left_panel_width)
        self.bev_render_mode = bev_render_mode if bev_render_mode in ("dots", "cloud") else "dots"
        self.cloud_point_size = max(1, cloud_point_size)
        self.ego_radius_m = max(0.05, float(ego_radius_m))

        self.fx = None
        self.fy = None
        self.cx = None
        self.cy = None
        self.cam_width = None

        self.rgb_bgr = None
        self.depth_m = None
        self.depth_vis = None
        self.depth_shape = None

        self.ray_x = None
        self.ray_y = None
        self.ray_shape = None

        self._rgb_encoding_logged = False
        self._depth_encoding_logged = False

        self.create_subscription(CameraInfo, camera_info_topic, self.on_camera_info, qos_profile_sensor_data)
        self.create_subscription(Image, rgb_topic, self.on_rgb, qos_profile_sensor_data)
        self.create_subscription(Image, depth_topic, self.on_depth, qos_profile_sensor_data)

        self.get_logger().info(f"rgb topic: {rgb_topic}")
        self.get_logger().info(f"depth topic: {depth_topic}")
        self.get_logger().info(f"camera_info topic: {camera_info_topic}")

    def on_camera_info(self, msg: CameraInfo):
        if len(msg.k) < 9:
            return
        self.fx = float(msg.k[0])
        self.fy = float(msg.k[4])
        self.cx = float(msg.k[2])
        self.cy = float(msg.k[5])
        if msg.width > 0:
            self.cam_width = int(msg.width)

    def on_rgb(self, msg: Image):
        try:
            self.rgb_bgr = parse_rgb_image(msg)
            if not self._rgb_encoding_logged:
                self.get_logger().info(f"detected rgb encoding: {msg.encoding}")
                self._rgb_encoding_logged = True
        except Exception as exc:
            self.get_logger().warn(f"rgb decode failed: {exc}")

    def on_depth(self, msg: Image):
        try:
            depth_m = parse_depth_to_meters(msg, self.depth_scale)
            depth_m = np.nan_to_num(depth_m, nan=0.0, posinf=0.0, neginf=0.0)
            self.depth_m = depth_m
            self.depth_shape = depth_m.shape
            self.depth_vis = depth_to_colormap(depth_m, self.depth_min, self.depth_max)
            if not self._depth_encoding_logged:
                self.get_logger().info(f"detected depth encoding: {msg.encoding}")
                self._depth_encoding_logged = True
        except Exception as exc:
            self.get_logger().warn(f"depth decode failed: {exc}")

    def ensure_ray_table(self):
        if self.depth_shape is None:
            return False
        if self.fx is None or self.fy is None or self.cx is None or self.cy is None:
            return False

        h, w = self.depth_shape
        key = (h, w, self.stride, self.fx, self.fy, self.cx, self.cy)
        if self.ray_shape == key:
            return True

        ys = np.arange(0, h, self.stride, dtype=np.float32)
        xs = np.arange(0, w, self.stride, dtype=np.float32)
        xx, yy = np.meshgrid(xs, ys)

        self.ray_x = (xx - self.cx) / self.fx
        self.ray_y = (yy - self.cy) / self.fy
        self.ray_shape = key
        return True

    def build_bev(self):
        if self.depth_m is None:
            return self.render_base_map(None, None, None, None, None, "waiting-depth")
        if not self.ensure_ray_table():
            return self.render_base_map(None, None, None, None, None, "waiting-camera-info")

        depth_sub = self.depth_m[:: self.stride, :: self.stride]
        if depth_sub.shape != self.ray_x.shape:
            h = min(depth_sub.shape[0], self.ray_x.shape[0])
            w = min(depth_sub.shape[1], self.ray_x.shape[1])
            if h <= 0 or w <= 0:
                return self.render_base_map(None, None, None, None, None, "shape-mismatch")
            depth_sub = depth_sub[:h, :w]
            ray_x = self.ray_x[:h, :w]
            ray_y = self.ray_y[:h, :w]
        else:
            ray_x = self.ray_x
            ray_y = self.ray_y

        z = depth_sub
        valid = np.isfinite(z) & (z >= self.depth_min) & (z <= self.depth_max)
        if not np.any(valid):
            return self.render_base_map(None, None, None, None, None, "no-valid-depth")

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

        if not np.any(valid):
            return self.render_base_map(None, None, None, None, None, floor_mode)

        x_obs = x[valid]
        z_obs = z[valid]
        y_obs = y[valid]

        distances = np.sqrt(x_obs * x_obs + z_obs * z_obs)
        nearest_distance = float(np.min(distances)) if distances.size > 0 else None

        nearest_heading = None
        if distances.size > 0:
            i = int(np.argmin(distances))
            nearest_heading = float(np.degrees(np.arctan2(x_obs[i], z_obs[i])))

        return self.render_base_map(x_obs, z_obs, y_obs, nearest_distance, nearest_heading, floor_mode)

    def render_base_map(self, x_obs, z_obs, y_obs, nearest_distance, nearest_heading=None, floor_mode="none"):
        width = int((2.0 * self.max_side * self.ppm)) + 160
        height = int((self.max_forward * self.ppm)) + 120
        width = max(width, 640)
        height = max(height, 480)
        header_h = 186
        footer_h = 36

        img = np.zeros((height, width, 3), dtype=np.uint8)
        img[:] = (20, 20, 20)

        origin_x = width // 2
        origin_y = height - 50

        self.draw_grid(img, origin_x, origin_y)
        self.draw_fov_guides(img, origin_x, origin_y)

        cv2.line(img, (40, origin_y), (width - 40, origin_y), (80, 180, 80), 1)
        cv2.line(img, (origin_x, origin_y), (origin_x, 20), (80, 180, 80), 1)
        cv2.putText(img, "x (right +)", (width - 190, origin_y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 220, 120), 1)
        cv2.putText(img, "z (forward +)", (origin_x + 8, header_h + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 220, 120), 1)

        self.draw_ego_footprint(img, origin_x, origin_y)

        point_count = 0
        shadow_bin_count = 0
        if x_obs is not None and z_obs is not None and x_obs.size > 0:
            px = (origin_x + (x_obs * self.ppm)).astype(np.int32)
            py = (origin_y - (z_obs * self.ppm)).astype(np.int32)

            in_map = (px >= 40) & (px < width - 40) & (py >= 20) & (py < origin_y)
            px = px[in_map]
            py = py[in_map]
            x_obs = x_obs[in_map]
            z_obs = z_obs[in_map]
            if y_obs is not None and y_obs.size == in_map.size:
                y_obs = y_obs[in_map]

            if px.size > 0:
                shadow_bin_count = self.draw_occlusion_shadow(img, origin_x, origin_y, x_obs, z_obs)
                if self.bev_render_mode == "cloud":
                    idx = np.arange(px.size)
                    if px.size > 25000:
                        idx = np.random.choice(px.size, 25000, replace=False)
                    pxs = px[idx]
                    pys = py[idx]
                    d = np.sqrt(x_obs[idx] * x_obs[idx] + z_obs[idx] * z_obs[idx])
                    d = np.clip(d / max(self.max_forward, 0.1), 0.0, 1.0)
                    color_index = (255.0 * (1.0 - d)).astype(np.uint8)
                    bgr = cv2.applyColorMap(color_index.reshape(-1, 1), cv2.COLORMAP_TURBO).reshape(-1, 3)
                    for i in range(pxs.size):
                        c = (int(bgr[i, 0]), int(bgr[i, 1]), int(bgr[i, 2]))
                        cv2.circle(img, (int(pxs[i]), int(pys[i])), self.cloud_point_size, c, -1, lineType=cv2.LINE_AA)
                    point_count = int(pxs.size)
                else:
                    img[py, px] = (0, 0, 255)
                    point_count = int(px.size)

        cv2.rectangle(img, (0, 0), (width - 1, header_h), (14, 14, 14), -1)
        cv2.rectangle(img, (0, height - footer_h), (width - 1, height - 1), (14, 14, 14), -1)
        cv2.line(img, (0, header_h), (width - 1, header_h), (70, 70, 70), 1)
        cv2.line(img, (0, height - footer_h), (width - 1, height - footer_h), (70, 70, 70), 1)

        if nearest_distance is not None:
            txt = f"nearest obstacle: {nearest_distance:.2f} m"
            if nearest_heading is not None:
                txt += f"  heading: {nearest_heading:+.1f} deg"
            cv2.putText(img, txt, (24, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
        else:
            cv2.putText(img, "nearest obstacle: N/A", (24, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (120, 120, 120), 2)

        cv2.putText(img, f"obstacle points: {point_count}", (24, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 210, 210), 1)
        cv2.putText(img, f"shadow bins: {shadow_bin_count}", (24, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (170, 170, 220), 1)
        cv2.putText(img, f"floor filter: {floor_mode}", (24, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (180, 180, 180), 1)
        if self.bev_render_mode == "cloud":
            cv2.putText(img, "cloud: depth-colored point cloud", (24, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 220, 220), 1)
        else:
            cv2.putText(img, "red: obstacle points + blocked shadow behind them", (24, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 120, 255), 1)
        cv2.putText(img, f"cyan circle: ego footprint r={self.ego_radius_m:.2f} m", (24, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 240, 240), 1)
        cv2.putText(img, "yellow: camera FOV boundary", (24, 158), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (190, 190, 190), 1)
        cv2.putText(img, "bird-eye view from depth", (24, height - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (170, 170, 170), 1)

        return img

    def draw_occlusion_shadow(self, img, origin_x, origin_y, x_obs, z_obs):
        if x_obs is None or z_obs is None or x_obs.size == 0 or z_obs.size == 0:
            return 0

        distances = np.sqrt((x_obs * x_obs) + (z_obs * z_obs))
        headings = np.arctan2(x_obs, z_obs)
        theta_min = -math.atan2(self.max_side, max(self.max_forward, 0.1))
        theta_max = +math.atan2(self.max_side, max(self.max_forward, 0.1))
        if theta_max <= theta_min:
            return 0

        num_bins = max(160, int(math.degrees(theta_max - theta_min) * 4.0))
        bin_pos = (headings - theta_min) / (theta_max - theta_min)
        bin_idx = np.floor(bin_pos * num_bins).astype(np.int32)
        valid_bins = (bin_idx >= 0) & (bin_idx < num_bins)
        if not np.any(valid_bins):
            return 0

        x_sel = x_obs[valid_bins]
        z_sel = z_obs[valid_bins]
        d_sel = distances[valid_bins]
        bins_sel = bin_idx[valid_bins]
        order = np.argsort(d_sel)

        nearest_x = np.full(num_bins, np.nan, dtype=np.float32)
        nearest_z = np.full(num_bins, np.nan, dtype=np.float32)
        assigned = np.zeros(num_bins, dtype=bool)
        for order_idx in order:
            b = int(bins_sel[order_idx])
            if assigned[b]:
                continue
            nearest_x[b] = float(x_sel[order_idx])
            nearest_z[b] = float(z_sel[order_idx])
            assigned[b] = True

        if not np.any(assigned):
            return 0

        overlay = np.zeros_like(img)
        theta_step = (theta_max - theta_min) / float(num_bins)
        drawn = 0
        for b in np.where(assigned)[0]:
            start_x_m = float(nearest_x[b])
            start_z_m = float(nearest_z[b])
            start_px = int(origin_x + (start_x_m * self.ppm))
            start_py = int(origin_y - (start_z_m * self.ppm))
            theta = theta_min + ((b + 0.5) * theta_step)
            tan_t = math.tan(theta)
            end_z = self.max_forward
            if abs(tan_t) > 1e-6:
                end_z = min(end_z, self.max_side / abs(tan_t))
            end_x = end_z * tan_t
            end_px = int(origin_x + (end_x * self.ppm))
            end_py = int(origin_y - (end_z * self.ppm))
            cv2.line(overlay, (start_px, start_py), (end_px, end_py), (0, 0, 120), 4, lineType=cv2.LINE_AA)
            drawn += 1

        cv2.addWeighted(overlay, 0.55, img, 1.0, 0.0, dst=img)
        return drawn

    def draw_grid(self, img, origin_x, origin_y):
        h, w = img.shape[:2]

        step = max(self.grid_step, 0.1)
        x_vals = np.arange(-self.max_side, self.max_side + 0.001, step)
        z_vals = np.arange(0.0, self.max_forward + 0.001, step)

        for xm in x_vals:
            px = int(origin_x + xm * self.ppm)
            if px < 40 or px >= w - 40:
                continue
            color = (55, 55, 55)
            if abs((xm / step) % 5) < 1e-6:
                color = (80, 80, 80)
            cv2.line(img, (px, 20), (px, origin_y), color, 1)
            if abs(round(xm) - xm) < 1e-6:
                cv2.putText(img, f"{xm:.0f}", (px - 8, origin_y + 16), cv2.FONT_HERSHEY_PLAIN, 0.9, (130, 130, 130), 1)

        for zm in z_vals:
            py = int(origin_y - zm * self.ppm)
            if py < 20 or py > origin_y:
                continue
            color = (55, 55, 55)
            if abs((zm / step) % 5) < 1e-6:
                color = (80, 80, 80)
            cv2.line(img, (40, py), (w - 40, py), color, 1)
            if abs(round(zm) - zm) < 1e-6:
                cv2.putText(img, f"{zm:.0f}", (8, py + 4), cv2.FONT_HERSHEY_PLAIN, 0.9, (130, 130, 130), 1)

    def _ray_endpoint_px(self, theta_rad, origin_x, origin_y):
        tan_t = math.tan(theta_rad)
        z_end = self.max_forward
        if abs(tan_t) > 1e-6:
            z_end = min(z_end, self.max_side / abs(tan_t))
        x_end = z_end * tan_t
        px = int(origin_x + x_end * self.ppm)
        py = int(origin_y - z_end * self.ppm)
        return px, py

    def draw_fov_guides(self, img, origin_x, origin_y):
        if self.fx is None:
            return

        width_px = self.cam_width
        if width_px is None and self.depth_shape is not None:
            width_px = int(self.depth_shape[1])
        if not width_px or width_px <= 0:
            return

        hfov = 2.0 * math.atan(width_px / (2.0 * self.fx))
        half = hfov * 0.5

        left_outer = self._ray_endpoint_px(-half, origin_x, origin_y)
        right_outer = self._ray_endpoint_px(+half, origin_x, origin_y)

        cv2.line(img, (origin_x, origin_y), left_outer, (0, 220, 220), 1, lineType=cv2.LINE_AA)
        cv2.line(img, (origin_x, origin_y), right_outer, (0, 220, 220), 1, lineType=cv2.LINE_AA)
        cv2.line(img, (origin_x, origin_y), (origin_x, origin_y - 45), (0, 220, 220), 1, lineType=cv2.LINE_AA)

        hfov_deg = math.degrees(hfov)
        cv2.putText(img, f"HFOV: {hfov_deg:.1f} deg", (24, 176), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 210, 210), 1)

    def draw_ego_footprint(self, img, origin_x, origin_y):
        radius_px = max(4, int(round(self.ego_radius_m * self.ppm)))
        overlay = img.copy()
        cv2.circle(overlay, (origin_x, origin_y), radius_px, (40, 170, 170), -1, lineType=cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.30, img, 0.70, 0.0, dst=img)
        cv2.circle(img, (origin_x, origin_y), radius_px, (140, 255, 255), 2, lineType=cv2.LINE_AA)
        cv2.circle(img, (origin_x, origin_y), 5, (0, 255, 255), -1, lineType=cv2.LINE_AA)
        cv2.arrowedLine(img, (origin_x, origin_y), (origin_x, origin_y - max(28, radius_px + 8)), (0, 255, 255), 2, tipLength=0.25)
        cv2.putText(img, "ego", (origin_x + radius_px + 10, origin_y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 255, 255), 1)

    def _make_labeled_panel(self, src, label, out_w, out_h):
        panel = np.zeros((out_h, out_w, 3), dtype=np.uint8)
        panel[:] = (28, 28, 28)

        if src is not None and src.size > 0:
            resized = cv2.resize(src, (out_w, out_h), interpolation=cv2.INTER_AREA)
            panel = resized
        else:
            cv2.putText(panel, "no data", (20, out_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (160, 160, 160), 2)

        cv2.rectangle(panel, (0, 0), (out_w - 1, 28), (0, 0, 0), -1)
        cv2.putText(panel, label, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 2)
        return panel

    def compose_scene(self, bev_img):
        if bev_img is None:
            bev_img = self.render_base_map(None, None, None, None, None, "waiting")

        right = bev_img
        right_h = right.shape[0]

        top_h = right_h // 2
        bottom_h = right_h - top_h

        left_top = self._make_labeled_panel(self.rgb_bgr, "RGB", self.left_panel_width, top_h)
        left_bottom = self._make_labeled_panel(self.depth_vis, "DEPTH", self.left_panel_width, bottom_h)
        left = np.vstack((left_top, left_bottom))

        canvas = np.hstack((left, right))
        cv2.rectangle(canvas, (0, 0), (canvas.shape[1] - 1, canvas.shape[0] - 1), (90, 90, 90), 1)
        return canvas


def build_vlm_prompt(depth_min: float, depth_max: float, bev_render_mode: str):
    if bev_render_mode == "cloud":
        bev_rule = "- BEV shows a depth-colored point cloud rasterized on top-view."
    else:
        bev_rule = "- Red points on BEV are obstacle candidates after floor filtering."
    return f"""VLM Input Rule (RGB + DEPTH + BEV)

Panel layout:
- Left-Top: RGB image (camera view).
- Left-Bottom: DEPTH colormap of the same scene.
- Right: Bird-Eye View (BEV) obstacle map.

Coordinate and map rules:
- BEV origin (camera) is near the bottom-center.
- +x means right side, +z means forward direction.
{bev_rule}
- Yellow lines: full camera horizontal FOV boundary.
- Grid labels are in meters.

Depth panel rules:
- DEPTH values are clipped to [{depth_min:.2f}, {depth_max:.2f}] meters.
- This uses TURBO colormap, so color is relative depth.
- Use BEV geometry for obstacle position; do not infer metric distance from DEPTH color alone.

VLM task instructions:
1. Describe nearest obstacle distance/heading using BEV text and point location.
2. Summarize occupancy in three sectors: left, front-center, right.
3. Flag immediate risk if front-center has close obstacles.
4. If RGB and BEV disagree, trust BEV for metric position and RGB for object semantics.
"""


def main():
    parser = argparse.ArgumentParser(description="Depth-based bird-eye obstacle map viewer for current ROS topics")
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
    parser.add_argument("--print-vlm-prompt", action="store_true")
    args = parser.parse_args()

    if args.print_vlm_prompt:
        print(build_vlm_prompt(args.depth_min, args.depth_max, args.bev_render_mode))

    rclpy.init()
    node = BirdEyeNode(
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

    cv2.namedWindow("rgb_depth_bev_current", cv2.WINDOW_NORMAL)

    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)

    frame_period = 1.0 / max(args.fps, 1.0)
    last_frame = 0.0

    try:
        while rclpy.ok():
            executor.spin_once(timeout_sec=0.01)

            now = time.time()
            if (now - last_frame) >= frame_period:
                bev = node.build_bev()
                scene = node.compose_scene(bev)
                if scene is not None:
                    cv2.imshow("rgb_depth_bev_current", scene)
                last_frame = now

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break
    finally:
        node.destroy_node()
        rclpy.shutdown()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
