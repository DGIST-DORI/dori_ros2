#!/usr/bin/env python3
import threading

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, CompressedImage, Image, PointCloud2
from tf2_ros import Buffer, TransformException, TransformListener

try:
    from sensor_msgs_py import point_cloud2 as pc2
except ImportError:  # pragma: no cover
    pc2 = None


COLOR_TOPIC = "/camera/camera/color/image_raw"
COLOR_COMPRESSED_TOPIC = "/camera/camera/color/image_raw/compressed"
DEPTH_TOPIC = "/camera/camera/aligned_depth_to_color/image_raw"
DEPTH_COMPRESSED_TOPIC = "/camera/camera/aligned_depth_to_color/image_raw/compressed"
DEPTH_INFO_TOPIC = "/camera/camera/aligned_depth_to_color/camera_info"
GROUND_CLOUD_TOPIC = "/rtabmap/ground"

USE_COLOR_COMPRESSED = False
USE_DEPTH_COMPRESSED = False
USE_GROUND_CLOUD = True
USE_DEPTH_PLANE_FALLBACK = True

DEPTH_MAX_M = 5.0
FLOOR_DISTANCE_THRESH_M = 0.03
FLOOR_RANSAC_ITERS = 80
FLOOR_RANSAC_STRIDE = 4
FLOOR_SAMPLE_MIN_ROW_FRACTION = 0.55
FLOOR_NORMAL_Y_MIN = 0.6
FLOOR_MASK_MORPH_K = 5
FLOOR_BOTTOM_ROWS = 40
PLANE_SMOOTH_ALPHA = 0.2

OBJECT_HEIGHT_THRESH_M = 0.15
OBJECT_MIN_AREA_PX = 200
OBJECT_MORPH_K = 5

GROUND_PLANE_SAMPLE_STRIDE = 3
GROUND_PLANE_MAX_POINTS = 50000
GROUND_PLANE_TIMEOUT_S = 1.0

GRID_SPACING_M = 0.5
GRID_EXTENT_M = 6.0
GRID_COLOR = (0, 255, 0)
GRID_MAJOR_SPACING_M = 1.0
GRID_MINOR_THICKNESS = 1
GRID_MAJOR_THICKNESS = 2
GRID_AXIS_THICKNESS = 3
GRID_AXIS_COLOR_X = (0, 0, 255)
GRID_AXIS_COLOR_Z = (255, 0, 0)
GRID_TEXT_COLOR = (255, 255, 255)
GRID_TEXT_OUTLINE = (0, 0, 0)
GRID_TEXT_SCALE = 0.6
GRID_TEXT_THICKNESS = 2
GRID_TEXT_OUTLINE_THICKNESS = 4


class CameraVizNode(Node):
    def __init__(self) -> None:
        super().__init__("camera_viz")
        self.bridge = CvBridge()
        self.color_frame = None
        self.depth_frame = None
        self.color_lock = threading.Lock()
        self.depth_lock = threading.Lock()
        self.depth_max_m = DEPTH_MAX_M
        self.fx = None
        self.fy = None
        self.cx = None
        self.cy = None
        self.img_w = None
        self.img_h = None
        self.camera_frame_id = None
        self.plane_n = None
        self.plane_d = None
        self.last_plane_ns = 0
        self.plane_interval_ns = int(0.25 * 1e9)
        self.ground_plane_n = None
        self.ground_plane_d = None
        self.ground_plane_frame = None
        self.ground_plane_stamp = None
        self.ground_plane_ns = 0

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        if USE_COLOR_COMPRESSED:
            self.create_subscription(
                CompressedImage, COLOR_COMPRESSED_TOPIC, self._on_color_compressed, 10
            )
            color_topic = COLOR_COMPRESSED_TOPIC
        else:
            self.create_subscription(Image, COLOR_TOPIC, self._on_color, 10)
            color_topic = COLOR_TOPIC

        if USE_DEPTH_COMPRESSED:
            self.create_subscription(
                CompressedImage, DEPTH_COMPRESSED_TOPIC, self._on_depth_compressed, 10
            )
            depth_topic = DEPTH_COMPRESSED_TOPIC
        else:
            self.create_subscription(Image, DEPTH_TOPIC, self._on_depth, 10)
            depth_topic = DEPTH_TOPIC

        self.create_subscription(CameraInfo, DEPTH_INFO_TOPIC, self._on_camera_info, 10)
        if USE_GROUND_CLOUD:
            self.create_subscription(
                PointCloud2, GROUND_CLOUD_TOPIC, self._on_ground_cloud, 3
            )

        self.timer = self.create_timer(0.03, self._on_timer)  # ~30 FPS
        self.get_logger().info(f"Color topic: {color_topic}")
        self.get_logger().info(f"Depth topic: {depth_topic}")
        self.get_logger().info(f"Depth info topic: {DEPTH_INFO_TOPIC}")
        if USE_GROUND_CLOUD:
            self.get_logger().info(f"Ground cloud topic: {GROUND_CLOUD_TOPIC}")

    def _on_color(self, msg: Image) -> None:
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warning(f"Color decode failed: {exc}")
            return
        with self.color_lock:
            self.color_frame = frame

    def _on_color_compressed(self, msg: CompressedImage) -> None:
        try:
            np_arr = np.frombuffer(msg.data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        except Exception as exc:
            self.get_logger().warning(f"Compressed color decode failed: {exc}")
            return
        if frame is None:
            self.get_logger().warning("Compressed color decode returned None")
            return
        with self.color_lock:
            self.color_frame = frame

    def _on_depth(self, msg: Image) -> None:
        try:
            depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        except Exception as exc:
            self.get_logger().warning(f"Depth decode failed: {exc}")
            return
        with self.depth_lock:
            self.depth_frame = depth

    def _on_camera_info(self, msg: CameraInfo) -> None:
        if len(msg.k) < 9:
            return
        self.fx = msg.k[0]
        self.fy = msg.k[4]
        self.cx = msg.k[2]
        self.cy = msg.k[5]
        self.img_w = msg.width
        self.img_h = msg.height
        self.camera_frame_id = msg.header.frame_id

    def _on_depth_compressed(self, msg: CompressedImage) -> None:
        # Note: compressedDepth uses a special encoding that OpenCV cannot decode directly.
        # This path supports standard compressed (JPEG/PNG) only.
        if "compressedDepth" in msg.format:
            self.get_logger().error(
                "compressedDepth is not supported. Use a raw depth topic instead."
            )
            return
        try:
            np_arr = np.frombuffer(msg.data, np.uint8)
            depth = cv2.imdecode(np_arr, cv2.IMREAD_UNCHANGED)
        except Exception as exc:
            self.get_logger().warning(f"Compressed depth decode failed: {exc}")
            return
        if depth is None:
            self.get_logger().warning("Compressed depth decode returned None")
            return
        with self.depth_lock:
            self.depth_frame = depth

    def _on_ground_cloud(self, msg: PointCloud2) -> None:
        if pc2 is None:
            self.get_logger().error("sensor_msgs_py.point_cloud2 not available")
            return
        points = self._pointcloud2_to_xyz(
            msg,
            stride=GROUND_PLANE_SAMPLE_STRIDE,
            max_points=GROUND_PLANE_MAX_POINTS,
        )
        if points.shape[0] < 50:
            return
        plane = self._fit_plane_svd(points)
        if plane is None:
            return
        n, d = plane
        self.ground_plane_n = n
        self.ground_plane_d = d
        self.ground_plane_frame = msg.header.frame_id
        self.ground_plane_stamp = Time.from_msg(msg.header.stamp)
        self.ground_plane_ns = self.get_clock().now().nanoseconds

    def _colorize_depth(self, depth: np.ndarray) -> np.ndarray:
        depth = np.nan_to_num(depth, nan=0.0, posinf=0.0, neginf=0.0)
        if depth.dtype == np.uint16:
            depth_m = depth.astype(np.float32) / 1000.0  # assume mm
        else:
            depth_m = depth.astype(np.float32)

        depth_m = np.clip(depth_m, 0.0, self.depth_max_m)
        if self.depth_max_m <= 0:
            self.depth_max_m = 5.0

        norm = (depth_m / self.depth_max_m * 255.0).astype(np.uint8)
        colored = cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)
        colored[depth_m == 0] = 0
        return colored

    def _depth_to_meters(self, depth: np.ndarray) -> np.ndarray:
        if depth.dtype == np.uint16:
            return depth.astype(np.float32) / 1000.0
        return depth.astype(np.float32)

    def _pointcloud2_to_xyz(
        self, msg: PointCloud2, stride: int = 1, max_points: int = 0
    ) -> np.ndarray:
        if pc2 is None:
            return np.empty((0, 3), dtype=np.float32)
        pts = []
        idx = 0
        for p in pc2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True):
            if stride > 1 and (idx % stride) != 0:
                idx += 1
                continue
            pts.append(p)
            idx += 1
            if max_points and len(pts) >= max_points:
                break
        if not pts:
            return np.empty((0, 3), dtype=np.float32)
        return np.asarray(pts, dtype=np.float32)

    def _sample_points(self, depth_m: np.ndarray) -> np.ndarray:
        if self.fx is None:
            return np.empty((0, 3), dtype=np.float32)
        h, w = depth_m.shape[:2]
        v_start = int(h * FLOOR_SAMPLE_MIN_ROW_FRACTION)
        v = np.arange(v_start, h, FLOOR_RANSAC_STRIDE)
        u = np.arange(0, w, FLOOR_RANSAC_STRIDE)
        vv, uu = np.meshgrid(v, u, indexing="ij")
        z = depth_m[vv, uu]
        valid = np.isfinite(z) & (z > 0.1) & (z < self.depth_max_m)
        if not np.any(valid):
            return np.empty((0, 3), dtype=np.float32)
        uu = uu[valid].astype(np.float32)
        vv = vv[valid].astype(np.float32)
        z = z[valid].astype(np.float32)
        x = (uu - self.cx) * z / self.fx
        y = (vv - self.cy) * z / self.fy
        return np.stack([x, y, z], axis=1)

    def _fit_plane_ransac(self, points: np.ndarray) -> tuple[np.ndarray, float] | None:
        if points.shape[0] < 50:
            return None
        best_inliers = None
        best_n = None
        best_d = None
        n_points = points.shape[0]
        for _ in range(FLOOR_RANSAC_ITERS):
            idx = np.random.choice(n_points, 3, replace=False)
            p1, p2, p3 = points[idx]
            v1 = p2 - p1
            v2 = p3 - p1
            n = np.cross(v1, v2)
            norm = np.linalg.norm(n)
            if norm < 1e-6:
                continue
            n = n / norm
            d = -np.dot(n, p1)
            dist = np.abs(points @ n + d)
            inliers = dist < FLOOR_DISTANCE_THRESH_M
            if best_inliers is None or np.count_nonzero(inliers) > np.count_nonzero(best_inliers):
                best_inliers = inliers
                best_n = n
                best_d = d
        if best_inliers is None or np.count_nonzero(best_inliers) < 50:
            return None
        inlier_pts = points[best_inliers]
        centroid = np.mean(inlier_pts, axis=0)
        uu, ss, vv = np.linalg.svd(inlier_pts - centroid, full_matrices=False)
        n = vv[-1]
        n = n / np.linalg.norm(n)
        d = -np.dot(n, centroid)
        if n[1] > 0:
            n = -n
            d = -d
        return n, float(d)

    def _fit_plane_svd(self, points: np.ndarray) -> tuple[np.ndarray, float] | None:
        if points.shape[0] < 3:
            return None
        centroid = np.mean(points, axis=0)
        _, _, vh = np.linalg.svd(points - centroid, full_matrices=False)
        n = vh[-1]
        n_norm = np.linalg.norm(n)
        if n_norm < 1e-6:
            return None
        n = n / n_norm
        d = -np.dot(n, centroid)
        return n, float(d)

    def _segment_floor(self, depth_m: np.ndarray) -> np.ndarray | None:
        if self.plane_n is None:
            return None
        h, w = depth_m.shape[:2]
        u = np.arange(0, w, dtype=np.float32)
        v = np.arange(0, h, dtype=np.float32)
        uu, vv = np.meshgrid(u, v)
        z = depth_m
        valid = np.isfinite(z) & (z > 0.1) & (z < self.depth_max_m)
        x = (uu - self.cx) * z / self.fx
        y = (vv - self.cy) * z / self.fy
        dist = np.abs(self.plane_n[0] * x + self.plane_n[1] * y + self.plane_n[2] * z + self.plane_d)
        mask = valid & (dist < FLOOR_DISTANCE_THRESH_M)
        mask_u8 = (mask * 255).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (FLOOR_MASK_MORPH_K, FLOOR_MASK_MORPH_K))
        mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, k)
        mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, k)

        num_labels, labels = cv2.connectedComponents(mask_u8)
        if num_labels <= 1:
            return mask_u8.astype(bool)
        bottom = labels[max(0, h - FLOOR_BOTTOM_ROWS):h, :]
        candidates = np.unique(bottom)
        candidates = candidates[candidates != 0]
        if candidates.size == 0:
            return mask_u8.astype(bool)

        counts = np.bincount(labels.ravel())
        best = candidates[np.argmax(counts[candidates])]
        return labels == best

    def _segment_objects(self, depth_m: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
        if self.plane_n is None:
            return None, None
        h, w = depth_m.shape[:2]
        u = np.arange(0, w, dtype=np.float32)
        v = np.arange(0, h, dtype=np.float32)
        uu, vv = np.meshgrid(u, v)
        z = depth_m
        valid = np.isfinite(z) & (z > 0.1) & (z < self.depth_max_m)
        x = (uu - self.cx) * z / self.fx
        y = (vv - self.cy) * z / self.fy
        signed = self.plane_n[0] * x + self.plane_n[1] * y + self.plane_n[2] * z + self.plane_d
        obj = valid & (signed > OBJECT_HEIGHT_THRESH_M)
        obj_u8 = (obj * 255).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (OBJECT_MORPH_K, OBJECT_MORPH_K))
        obj_u8 = cv2.morphologyEx(obj_u8, cv2.MORPH_OPEN, k)
        obj_u8 = cv2.morphologyEx(obj_u8, cv2.MORPH_CLOSE, k)
        return obj_u8.astype(bool), signed

    def _project_points(self, pts: np.ndarray) -> np.ndarray:
        z = pts[:, 2]
        valid = z > 0.1
        pts = pts[valid]
        if pts.size == 0:
            return np.empty((0, 2), dtype=np.int32)
        u = (pts[:, 0] * self.fx / pts[:, 2]) + self.cx
        v = (pts[:, 1] * self.fy / pts[:, 2]) + self.cy
        uv = np.stack([u, v], axis=1)
        return uv.astype(np.int32)

    def _quat_to_rot(self, q) -> np.ndarray:
        x, y, z, w = q.x, q.y, q.z, q.w
        xx = x * x
        yy = y * y
        zz = z * z
        xy = x * y
        xz = x * z
        yz = y * z
        wx = w * x
        wy = w * y
        wz = w * z
        return np.array(
            [
                [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
                [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
                [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
            ],
            dtype=np.float32,
        )

    def _transform_plane(
        self, n: np.ndarray, d: float, from_frame: str, stamp: Time | None
    ) -> tuple[np.ndarray, float] | None:
        if self.camera_frame_id is None:
            return None
        try:
            tf = self.tf_buffer.lookup_transform(
                self.camera_frame_id,
                from_frame,
                stamp if stamp is not None else Time(),
                timeout=Duration(seconds=0.1),
            )
        except TransformException:
            if stamp is not None:
                try:
                    tf = self.tf_buffer.lookup_transform(
                        self.camera_frame_id,
                        from_frame,
                        Time(),
                        timeout=Duration(seconds=0.1),
                    )
                except TransformException:
                    return None
            else:
                return None

        rot = self._quat_to_rot(tf.transform.rotation)
        t = tf.transform.translation
        t_vec = np.array([t.x, t.y, t.z], dtype=np.float32)
        n_cam = rot @ n
        d_cam = d - float(np.dot(n_cam, t_vec))
        return n_cam, d_cam

    def _update_plane_from_ground_cloud(self) -> bool:
        if not USE_GROUND_CLOUD:
            return False
        if self.ground_plane_n is None or self.ground_plane_frame is None:
            return False
        now_ns = self.get_clock().now().nanoseconds
        if now_ns - self.ground_plane_ns > int(GROUND_PLANE_TIMEOUT_S * 1e9):
            return False
        plane = self._transform_plane(
            self.ground_plane_n,
            self.ground_plane_d,
            self.ground_plane_frame,
            self.ground_plane_stamp,
        )
        if plane is None:
            return False
        n_cam, d_cam = plane
        if n_cam[1] > 0:
            n_cam = -n_cam
            d_cam = -d_cam
        if self.plane_n is None:
            self.plane_n, self.plane_d = n_cam, d_cam
        else:
            self.plane_n = (1.0 - PLANE_SMOOTH_ALPHA) * self.plane_n + PLANE_SMOOTH_ALPHA * n_cam
            self.plane_n /= np.linalg.norm(self.plane_n)
            self.plane_d = (1.0 - PLANE_SMOOTH_ALPHA) * self.plane_d + PLANE_SMOOTH_ALPHA * d_cam
        return True

    def _draw_text(self, canvas: np.ndarray, text: str, org: tuple[int, int]) -> None:
        cv2.putText(
            canvas,
            text,
            org,
            cv2.FONT_HERSHEY_SIMPLEX,
            GRID_TEXT_SCALE,
            GRID_TEXT_OUTLINE,
            GRID_TEXT_OUTLINE_THICKNESS,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            text,
            org,
            cv2.FONT_HERSHEY_SIMPLEX,
            GRID_TEXT_SCALE,
            GRID_TEXT_COLOR,
            GRID_TEXT_THICKNESS,
            cv2.LINE_AA,
        )

    def _grid_basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = self.plane_n
        d = self.plane_d
        origin = -d * n
        cam_x = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        cam_z = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        axis1 = cam_x - np.dot(cam_x, n) * n
        if np.linalg.norm(axis1) < 1e-3:
            axis1 = cam_z - np.dot(cam_z, n) * n
        axis1 /= np.linalg.norm(axis1)
        axis2 = np.cross(n, axis1)
        axis2 /= np.linalg.norm(axis2)
        return origin, axis1, axis2

    def _draw_grid(self, canvas: np.ndarray) -> None:
        if self.plane_n is None or self.fx is None:
            return
        h, w = canvas.shape[:2]
        origin, axis1, axis2 = self._grid_basis()

        lines = int(GRID_EXTENT_M / GRID_SPACING_M)
        t_vals = np.linspace(-GRID_EXTENT_M, GRID_EXTENT_M, 80, dtype=np.float32)
        for i in range(-lines, lines + 1):
            offset = i * GRID_SPACING_M
            is_major = abs(offset / GRID_MAJOR_SPACING_M - round(offset / GRID_MAJOR_SPACING_M)) < 1e-3
            line1 = origin + axis2 * offset + np.outer(t_vals, axis1)  # constant axis2 -> Z labels
            line2 = origin + axis1 * offset + np.outer(t_vals, axis2)  # constant axis1 -> X labels

            for line, is_axis, axis_color in (
                (line1, abs(offset) < 1e-6, GRID_AXIS_COLOR_Z),
                (line2, abs(offset) < 1e-6, GRID_AXIS_COLOR_X),
            ):
                uv = self._project_points(line)
                if uv.shape[0] < 2:
                    continue
                if is_axis:
                    color = axis_color
                    thickness = GRID_AXIS_THICKNESS
                else:
                    color = GRID_COLOR
                    thickness = GRID_MAJOR_THICKNESS if is_major else GRID_MINOR_THICKNESS
                cv2.polylines(canvas, [uv], False, color, thickness, cv2.LINE_AA)

            if is_major and abs(offset) > 1e-6:
                # Label Z on axis1-aligned lines
                pos_z = origin + axis2 * offset
                uv_z = self._project_points(pos_z[None, :])
                if uv_z.shape[0] == 1:
                    u, v = int(uv_z[0, 0]), int(uv_z[0, 1])
                    if 0 <= u < w and 0 <= v < h:
                        self._draw_text(canvas, f"Z={offset:.1f}m", (u + 6, v - 6))

                # Label X on axis2-aligned lines
                pos_x = origin + axis1 * offset
                uv_x = self._project_points(pos_x[None, :])
                if uv_x.shape[0] == 1:
                    u, v = int(uv_x[0, 0]), int(uv_x[0, 1])
                    if 0 <= u < w and 0 <= v < h:
                        self._draw_text(canvas, f"X={offset:.1f}m", (u + 6, v + 14))

        # Origin label
        uv_o = self._project_points(origin[None, :])
        if uv_o.shape[0] == 1:
            u, v = int(uv_o[0, 0]), int(uv_o[0, 1])
            if 0 <= u < w and 0 <= v < h:
                self._draw_text(canvas, "0,0", (u + 6, v + 14))

    def _on_timer(self) -> None:
        color = None
        depth = None
        with self.color_lock:
            if self.color_frame is not None:
                color = self.color_frame.copy()
        with self.depth_lock:
            if self.depth_frame is not None:
                depth = self.depth_frame.copy()

        if color is not None:
            cv2.imshow("Color", color)
        if depth is not None:
            depth_m = self._depth_to_meters(depth)
            depth_vis = self._colorize_depth(depth)

            if self.fx is not None:
                used_ground = self._update_plane_from_ground_cloud()
                now_ns = self.get_clock().now().nanoseconds
                if (not used_ground and USE_DEPTH_PLANE_FALLBACK and
                        now_ns - self.last_plane_ns > self.plane_interval_ns):
                    points = self._sample_points(depth_m)
                    plane = self._fit_plane_ransac(points)
                    if plane is not None:
                        n, d = plane
                        if abs(n[1]) >= FLOOR_NORMAL_Y_MIN:
                            if self.plane_n is None:
                                self.plane_n, self.plane_d = n, d
                            else:
                                self.plane_n = (1.0 - PLANE_SMOOTH_ALPHA) * self.plane_n + PLANE_SMOOTH_ALPHA * n
                                self.plane_n /= np.linalg.norm(self.plane_n)
                                self.plane_d = (1.0 - PLANE_SMOOTH_ALPHA) * self.plane_d + PLANE_SMOOTH_ALPHA * d
                            self.last_plane_ns = now_ns

                mask = self._segment_floor(depth_m)
                if mask is not None:
                    overlay = depth_vis.copy()
                    overlay[mask] = (0, 200, 0)
                    depth_vis = cv2.addWeighted(depth_vis, 0.7, overlay, 0.3, 0)
                    obj_mask, signed = self._segment_objects(depth_m)
                    if obj_mask is not None:
                        obj_overlay = depth_vis.copy()
                        obj_overlay[obj_mask] = (0, 0, 255)
                        depth_vis = cv2.addWeighted(depth_vis, 0.85, obj_overlay, 0.15, 0)

            cv2.imshow("Depth", depth_vis)

            if color is not None:
                color_grid = color.copy()
                if self.plane_n is not None:
                    self._draw_grid(color_grid)
                    obj_mask, signed = self._segment_objects(depth_m)
                    if obj_mask is not None:
                        obj_u8 = obj_mask.astype(np.uint8) * 255
                        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(obj_u8)
                        for i in range(1, num_labels):
                            area = stats[i, cv2.CC_STAT_AREA]
                            if area < OBJECT_MIN_AREA_PX:
                                continue
                            x0 = stats[i, cv2.CC_STAT_LEFT]
                            y0 = stats[i, cv2.CC_STAT_TOP]
                            w0 = stats[i, cv2.CC_STAT_WIDTH]
                            h0 = stats[i, cv2.CC_STAT_HEIGHT]
                            cv2.rectangle(color_grid, (x0, y0), (x0 + w0, y0 + h0), (0, 0, 255), 2)
                            if signed is not None:
                                height = float(np.nanmedian(signed[labels == i]))
                                self._draw_text(color_grid, f"h={height:.2f}m", (x0, max(0, y0 - 6)))
                cv2.imshow("Color+Grid", color_grid)
                if self.plane_n is not None:
                    grid_only = np.zeros_like(color)
                    self._draw_grid(grid_only)
                    cv2.imshow("GridOnly", grid_only)

        if cv2.waitKey(1) & 0xFF == 27:  # ESC
            rclpy.shutdown()

def main() -> None:
    rclpy.init()
    node = CameraVizNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
