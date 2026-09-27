"""LaserScanから既存teleop_managerへ自動運転指令を配信する。"""

import math
import time

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rc_car_interfaces.msg import DriveCommand
from sensor_msgs.msg import LaserScan

from tinylidarnet.preprocessing import scan_is_fresh


class TinyLidarNetNode(Node):
    def __init__(self):
        super().__init__('tinylidarnet_node')
        descriptor = ParameterDescriptor(read_only=True)

        def parameter(name, default):
            return self.declare_parameter(name, default, descriptor=descriptor).value

        model_dir = parameter('model_dir', '')
        device = parameter('device', 'cpu')
        threads = parameter('torch_threads', 1)
        rate = parameter('publish_rate', 20.0)
        self.scan_timeout = parameter('scan_timeout', 0.2)
        self.expected_frame = parameter('expected_frame_id', '')
        self.max_throttle = parameter('max_throttle', 0.25)
        self.max_steering = parameter('max_steering', 1.0)
        if not model_dir:
            raise ValueError('model_dirに学習済みモデルのディレクトリを指定してください')
        if type(threads) is not int or threads <= 0:
            raise ValueError('torch_threadsには正の整数を指定してください')
        if not math.isfinite(rate) or not 0 < rate <= 1000:
            raise ValueError('publish_rateは(0, 1000]で指定してください')
        if not math.isfinite(self.scan_timeout) or self.scan_timeout <= 0:
            raise ValueError('scan_timeoutには有限の正の値を指定してください')
        for limit in (self.max_throttle, self.max_steering):
            if not math.isfinite(limit) or not 0 < limit <= 1:
                raise ValueError('出力上限は(0, 1]で指定してください')

        import torch
        from tinylidarnet.predictor import Predictor

        torch.set_num_threads(threads)
        self.predictor = Predictor(model_dir, device)
        self.publisher = self.create_publisher(DriveCommand, 'autonomy/command', 1)
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(LaserScan, 'scan', self.on_scan, qos)
        self.latest = None
        self.sequence = 0
        self.predicted_sequence = -1
        self.prediction = (0.0, 0.0)
        self.last_stamp = 0
        self.create_timer(1.0 / rate, self.on_timer, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.get_logger().info(
            f'Loaded model: {model_dir}; preprocessing={self.predictor.config}; output=autonomy/command')

    def on_scan(self, msg):
        stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        if self.expected_frame and msg.header.frame_id != self.expected_frame:
            self.latest = None
            self.get_logger().warning('LaserScanのframe_idが設定と異なります。', throttle_duration_sec=2.0)
            return
        if stamp <= self.last_stamp or not scan_is_fresh(
                stamp, self.get_clock().now().nanoseconds, self.scan_timeout):
            self.latest = None
            self.get_logger().warning('古い／重複／未来時刻のLaserScanを破棄しました。', throttle_duration_sec=2.0)
            return
        self.last_stamp = stamp
        self.sequence += 1
        self.latest = (msg, time.monotonic(), stamp)

    def fresh(self):
        if self.latest is None:
            return False
        _, received, stamp = self.latest
        return (0 <= time.monotonic() - received <= self.scan_timeout
                and scan_is_fresh(stamp, self.get_clock().now().nanoseconds, self.scan_timeout))

    def on_timer(self):
        if not self.fresh():
            self.publish_neutral()
            return
        if self.predicted_sequence != self.sequence:
            msg = self.latest[0]
            try:
                self.prediction = self.predictor.predict(
                    msg.ranges, msg.angle_min, msg.angle_increment, msg.range_min, msg.range_max)
            except (ValueError, RuntimeError) as exc:
                self.prediction = (0.0, 0.0)
                self.get_logger().error(f'推論を停止しました: {exc}', throttle_duration_sec=2.0)
            self.predicted_sequence = self.sequence
        # 推論処理の間に古くなった結果も採用しない。
        if not self.fresh():
            self.publish_neutral()
            return
        steering, throttle = self.prediction
        self.publisher.publish(DriveCommand(
            steering=max(-self.max_steering, min(self.max_steering, steering)),
            throttle=max(-self.max_throttle, min(self.max_throttle, throttle)),
        ))

    def publish_neutral(self):
        self.publisher.publish(DriveCommand(steering=0.0, throttle=0.0))


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = TinyLidarNetNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            if rclpy.ok():
                node.publish_neutral()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
