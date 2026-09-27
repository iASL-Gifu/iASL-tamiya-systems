"""ROS-independent selection logic. All times are monotonic seconds."""

from dataclasses import dataclass
import math
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True)
class Command:
    throttle: float = 0.0
    steering: float = 0.0


@dataclass(frozen=True)
class Config:
    manual_button: int = 3
    auto_button: int = 2
    steering_axis: int = 0
    throttle_axis: int = 1
    steering_inverted: bool = False
    throttle_inverted: bool = False
    max_throttle: float = 0.25
    max_steering: float = 1.0
    joy_timeout: float = 0.3
    auto_timeout: float = 0.3

    def __post_init__(self):
        for name in ('manual_button', 'auto_button', 'steering_axis', 'throttle_axis'):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f'{name} must be a nonnegative integer')
        if self.manual_button == self.auto_button:
            raise ValueError('mode buttons must be different')
        for name in ('max_throttle', 'max_steering'):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError(f'{name} must be in (0, 1]')
        for name in ('joy_timeout', 'auto_timeout'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f'{name} must be finite and positive')


class Controller:
    def __init__(self, config: Config):
        self.config = config
        self._joy_time: Optional[float] = None
        self._requested = 'stopped'
        self._manual = Command()
        self._auto: Optional[Tuple[float, Command]] = None

    def requested_mode(self, now: float) -> str:
        if self._joy_time is None or not 0 <= now - self._joy_time < self.config.joy_timeout:
            return 'stopped'
        return self._requested

    def update_joy(self, axes: Sequence[float], buttons: Sequence[int], now: float) -> bool:
        c = self.config
        old_mode = self.requested_mode(now)
        valid = (
            len(axes) > max(c.steering_axis, c.throttle_axis)
            and len(buttons) > max(c.manual_button, c.auto_button)
            and all(math.isfinite(x) and -1.0 <= x <= 1.0 for x in axes)
            and all(x in (0, 1) for x in buttons)
        )
        if not valid:
            self._joy_time = None
            self._requested = 'stopped'
            self._auto = None
            self._manual = Command()
            return False
        manual, auto = bool(buttons[c.manual_button]), bool(buttons[c.auto_button])
        self._requested = 'manual' if manual and not auto else 'auto' if auto and not manual else 'stopped'
        self._joy_time = now
        if self._requested != old_mode or self._requested != 'auto':
            # Require a new autonomous command after every entry into auto mode.
            self._auto = None
        self._manual = Command(
            axes[c.throttle_axis] * c.max_throttle * (-1 if c.throttle_inverted else 1),
            axes[c.steering_axis] * c.max_steering * (-1 if c.steering_inverted else 1),
        )
        return True

    def update_auto(self, throttle: float, steering: float, now: float) -> bool:
        if not all(math.isfinite(x) and -1.0 <= x <= 1.0 for x in (throttle, steering)):
            self._auto = None
            return False
        if self.requested_mode(now) == 'auto':
            c = self.config
            self._auto = (now, Command(
                max(-c.max_throttle, min(c.max_throttle, throttle)),
                max(-c.max_steering, min(c.max_steering, steering)),
            ))
        else:
            self._auto = None
        return True

    def output(self, now: float) -> Tuple[str, Command]:
        mode = self.requested_mode(now)
        if mode == 'manual':
            return mode, self._manual
        if mode == 'auto' and self._auto is not None:
            received, command = self._auto
            if 0 <= now - received < self.config.auto_timeout:
                return mode, command
        if mode == 'stopped':
            self._auto = None
        return 'stopped', Command()
