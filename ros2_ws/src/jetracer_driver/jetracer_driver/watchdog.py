"""ROS-independent final command validation and reception timeout."""

import math


class Watchdog:
    def __init__(self, timeout=0.3, max_throttle=0.25, max_steering=1.0):
        if not math.isfinite(timeout) or timeout <= 0.0:
            raise ValueError('command_timeout must be finite and positive')
        for value in (max_throttle, max_steering):
            if not math.isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError('actuator limits must be in (0, 1]')
        self.timeout = timeout
        self.max_throttle = max_throttle
        self.max_steering = max_steering
        self._received = None
        self._command = (0.0, 0.0)

    def update(self, throttle, steering, now):
        if not all(math.isfinite(x) and -1.0 <= x <= 1.0 for x in (throttle, steering)):
            self._received = None
            self._command = (0.0, 0.0)
            return False
        self._received = now
        self._command = (
            max(-self.max_throttle, min(self.max_throttle, throttle)),
            max(-self.max_steering, min(self.max_steering, steering)),
        )
        return True

    def output(self, now):
        if self._received is None or not 0 <= now - self._received < self.timeout:
            return 0.0, 0.0
        return self._command
