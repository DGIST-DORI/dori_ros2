import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Image
from cv_bridge import CvBridge

import cv2


class RGBViewer(Node):
    def __init__(self):
        super().__init__('rgb_viewer')

        self.bridge = CvBridge()

        self.subscription = self.create_subscription(
            Image,
            '/rgb',              # ← 필요하면 토픽명 수정
            self.image_callback,
            10
        )

        self.get_logger().info("RGB Viewer started")

    def image_callback(self, msg: Image):
        try:
            # ROS Image → OpenCV image
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')

            cv2.imshow("RGB Image", cv_image)
            cv2.waitKey(1)

        except Exception as e:
            self.get_logger().error(f"Image conversion failed: {e}")


def main():
    rclpy.init()
    node = RGBViewer()
    rclpy.spin(node)

    cv2.destroyAllWindows()
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
