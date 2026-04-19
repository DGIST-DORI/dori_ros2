#!/usr/bin/env python3
import rclpy
from rclpy.node import Node

import cv2
import numpy as np
import struct
import threading

from cv_bridge import CvBridge
from sensor_msgs.msg import Image, LaserScan, PointCloud2


class QuadViewOnly(Node):
    def __init__(self):
        super().__init__('quad_view_only')

        self.bridge = CvBridge()

        # Buffers
        self.rgb = None
        self.depth = None
        self.scan = None
        self.pc = None

        # Subscribers
        self.create_subscription(Image, '/rgb', self.cb_rgb, 10)
        self.create_subscription(Image, '/depth', self.cb_depth, 10)
        self.create_subscription(LaserScan, '/scan', self.cb_scan, 10)
        self.create_subscription(PointCloud2, '/point_cloud', self.cb_pc, 10)

        self.running = True
        self.ui_thread = threading.Thread(target=self.ui_loop)
        self.ui_thread.start()

        self.get_logger().info("Quad View (visualization only) started")

    # ======================
    # Callbacks
    # ======================
    def cb_rgb(self, msg):
        self.rgb = self.bridge.imgmsg_to_cv2(msg, 'bgr8')

    def cb_depth(self, msg):
        depth = self.bridge.imgmsg_to_cv2(msg, 'passthrough')
        depth = np.nan_to_num(depth, nan=0.0, posinf=0.0)
        depth = cv2.normalize(depth, None, 0, 255, cv2.NORM_MINMAX)
        self.depth = cv2.applyColorMap(depth.astype(np.uint8), cv2.COLORMAP_JET)

    def cb_scan(self, msg):
        self.scan = msg

    def cb_pc(self, msg):
        self.pc = msg

    # ======================
    # Drawing
    # ======================
    def draw_scan(self):
        img = np.zeros((400, 400, 3), np.uint8)
        if self.scan is None:
            return img

        cx, cy = 200, 200
        scale = 40.0

        for i, r in enumerate(self.scan.ranges):
            if not np.isfinite(r):
                continue
            a = self.scan.angle_min + i * self.scan.angle_increment
            x = int(cx + r * scale * np.cos(a))
            y = int(cy + r * scale * np.sin(a))
            if 0 <= x < 400 and 0 <= y < 400:
                img[y, x] = (0, 255, 0)

        cv2.circle(img, (cx, cy), 4, (0, 0, 255), -1)
        return img

    def draw_pc(self):
        img = np.zeros((400, 400, 3), np.uint8)
        if self.pc is None:
            return img

        step = self.pc.point_step
        for i in range(0, len(self.pc.data), step):
            try:
                x, y, z = struct.unpack_from('fff', self.pc.data, i)
            except struct.error:
                continue

            px = int(200 + x * 20)
            py = int(200 + y * 20)
            if 0 <= px < 400 and 0 <= py < 400:
                img[py, px] = (255, 255, 255)

        return img

    def quad_view(self):
        blank = np.zeros((400, 400, 3), np.uint8)

        rgb = cv2.resize(self.rgb, (400, 400)) if self.rgb is not None else blank
        depth = cv2.resize(self.depth, (400, 400)) if self.depth is not None else blank
        scan = self.draw_scan()
        pc = self.draw_pc()

        return np.vstack([
            np.hstack([rgb, depth]),
            np.hstack([scan, pc])
        ])

    # ======================
    # UI Loop
    # ======================
    def ui_loop(self):
        while self.running:
            cv2.imshow("Quad View (ESC to quit)", self.quad_view())
            if cv2.waitKey(10) & 0xFF == 27:  # ESC
                self.running = False
                break
        cv2.destroyAllWindows()


def main():
    rclpy.init()
    node = QuadViewOnly()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.running = False
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()