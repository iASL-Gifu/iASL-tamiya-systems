"""ROS 2 adapter for the dead-man command selector."""

from dataclasses import fields
import math
import time

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rc_car_interfaces.msg import DriveCommand
from sensor_msgs.msg import Joy
from std_msgs.msg import String

from .controller import Config, Controller


class TeleopManager(Node):
    def __init__(self):
        super().__init__('teleop_manager')
        defaults = Config()
        read_only = ParameterDescriptor(read_only=True)
        values = {
            field.name: self.declare_parameter(
                field.name, getattr(defaults, field.name), descriptor=read_only).value
            for field in fields(defaults)
        }
        self.controller = Controller(Config(**values))
        rate = self.declare_parameter('publish_rate', 50.0, descriptor=read_only).value
        if not math.isfinite(rate) or not 0.0 < rate <= 1000.0:
            raise ValueError('publish_rate must be in (0, 1000]')
        # Volatile, depth one: do not retain a command for a new subscriber.
        self.command_pub = self.create_publisher(DriveCommand, 'drive/command', 1)
        self.mode_pub = self.create_publisher(String, 'teleop/mode', 1)
        input_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Joy, 'joy', self.on_joy, input_qos)
        self.create_subscription(DriveCommand, 'autonomy/command', self.on_auto, input_qos)
        self._previous_mode = None
        self.create_timer(1.0 / rate, self.publish_command, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def on_joy(self, msg):
        if not self.controller.update_joy(msg.axes, msg.buttons, time.monotonic()):
            self.get_logger().warning('Invalid Joy input: requesting neutral.', throttle_duration_sec=2.0)

    def on_auto(self, msg):
        if not self.controller.update_auto(msg.throttle, msg.steering, time.monotonic()):
            self.get_logger().warning('Invalid autonomous command: requesting neutral.', throttle_duration_sec=2.0)

    def publish_command(self):
        mode, command = self.controller.output(time.monotonic())
        self.command_pub.publish(DriveCommand(throttle=command.throttle, steering=command.steering))
        self.mode_pub.publish(String(data=mode))
        if mode != self._previous_mode:
            self.get_logger().info(f'Output mode: {mode}')
            self._previous_mode = mode


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = TeleopManager()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
