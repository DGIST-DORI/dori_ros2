import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import curses
import threading
import time


LINEAR_STEP = 0.1
ANGULAR_STEP = 0.1
MAX_LINEAR = 1.5
MAX_ANGULAR = 2.0


class KeyboardCmdVel(Node):
    def __init__(self, stdscr):
        super().__init__('keyboard_cmd_vel')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)

        self.linear = 0.0
        self.angular = 0.0

        self.stdscr = stdscr
        self.running = True

        self.timer = self.create_timer(0.1, self.publish_cmd)

    def publish_cmd(self):
        msg = Twist()
        msg.linear.x = self.linear
        msg.angular.z = self.angular
        self.pub.publish(msg)

    def clamp(self):
        self.linear = max(-MAX_LINEAR, min(MAX_LINEAR, self.linear))
        self.angular = max(-MAX_ANGULAR, min(MAX_ANGULAR, self.angular))

    def keyboard_loop(self):
        self.stdscr.nodelay(True)
        self.stdscr.clear()

        while self.running:
            key = self.stdscr.getch()

            if key == curses.KEY_UP:
                self.linear += LINEAR_STEP
            elif key == curses.KEY_DOWN:
                self.linear -= LINEAR_STEP
            elif key == curses.KEY_LEFT:
                self.angular += ANGULAR_STEP
            elif key == curses.KEY_RIGHT:
                self.angular -= ANGULAR_STEP
            elif key == ord(' '):
                self.linear = 0.0
                self.angular = 0.0
            elif key in [ord('q'), ord('Q')]:
                self.running = False
                break

            self.clamp()
            self.draw_status()
            time.sleep(0.05)

    def draw_status(self):
        self.stdscr.clear()
        self.stdscr.addstr(0, 0, "ROS2 Keyboard CmdVel Controller")
        self.stdscr.addstr(2, 0, "↑ ↓ : Linear velocity")
        self.stdscr.addstr(3, 0, "← → : Angular velocity")
        self.stdscr.addstr(4, 0, "SPACE : Stop")
        self.stdscr.addstr(5, 0, "Q : Quit")
        self.stdscr.addstr(7, 0, f"Linear  x: {self.linear:.2f}")
        self.stdscr.addstr(8, 0, f"Angular z: {self.angular:.2f}")
        self.stdscr.refresh()


def main(stdscr):
    rclpy.init()
    node = KeyboardCmdVel(stdscr)

    thread = threading.Thread(target=node.keyboard_loop)
    thread.start()

    rclpy.spin(node)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    curses.wrapper(main)
