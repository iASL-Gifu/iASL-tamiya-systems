"""Actuator node with its own watchdog, independent of teleop_manager."""

from dataclasses import fields
import math
import time

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rc_car_interfaces.msg import DriveCommand

from .backend import HardwareConfig, JetRacerBackend, MockBackend
from .watchdog import Watchdog


class JetRacerNode(Node):
    def __init__(self):
        super().__init__('jetracer_node')
        read_only = ParameterDescriptor(read_only=True)
        self.mock = self.declare_parameter('use_mock_hardware', True, descriptor=read_only).value
        timeout = self.declare_parameter('command_timeout', 0.3, descriptor=read_only).value
        throttle_limit = self.declare_parameter('max_throttle', 0.25, descriptor=read_only).value
        steering_limit = self.declare_parameter('max_steering', 1.0, descriptor=read_only).value
        self.watchdog = Watchdog(timeout, throttle_limit, steering_limit)
        rate = self.declare_parameter('update_rate', 50.0, descriptor=read_only).value
        if not math.isfinite(rate) or not 0 < rate <= 1000:
            raise ValueError('update_rate must be in (0, 1000]')
        defaults = HardwareConfig()
        config = HardwareConfig(**{
            field.name: self.declare_parameter(
                field.name, getattr(defaults, field.name), descriptor=read_only).value
            for field in fields(defaults)
        })
        self.applied_pub = self.create_publisher(DriveCommand, 'drive/applied', 1)
        self.create_subscription(DriveCommand, 'drive/command', self.on_command, 1)
        self.create_timer(1.0 / rate, self.apply_command, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.backend = MockBackend() if self.mock else JetRacerBackend(config)
        self.get_logger().info('MOCK hardware: no PWM output.' if self.mock else 'JetRacer hardware initialized at neutral.')

    def on_command(self, msg):
        if not self.watchdog.update(msg.throttle, msg.steering, time.monotonic()):
            self.get_logger().warning('Invalid drive command: requesting neutral.', throttle_duration_sec=2.0)

    def apply_command(self):
        throttle, steering = self.watchdog.output(time.monotonic())
        try:
            self.backend.write(throttle, steering)
        except Exception:
            self.get_logger().fatal('Actuator write failed; attempting neutral and exiting.')
            self.stop_hardware()
            raise
        # Software request after validation, not measured vehicle feedback.
        self.applied_pub.publish(DriveCommand(throttle=throttle, steering=steering))

    def stop_hardware(self):
        try:
            self.backend.stop()
        except Exception as exc:
            self.get_logger().fatal(f'Unable to write neutral: {exc}')


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = JetRacerNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.stop_hardware()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
