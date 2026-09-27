"""Hardware is imported only when explicitly enabled."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class HardwareConfig:
    i2c_address: int = 0x40
    steering_channel: int = 0
    throttle_channel: int = 1
    steering_gain: float = -0.65
    steering_offset: float = 0.0
    throttle_gain: float = 0.8

    def __post_init__(self):
        if type(self.i2c_address) is not int or not 0x08 <= self.i2c_address <= 0x77:
            raise ValueError('i2c_address must be a usable 7-bit I2C address')
        for name in ('steering_channel', 'throttle_channel'):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 15:
                raise ValueError(f'{name} must be in [0, 15]')
        if self.steering_channel == self.throttle_channel:
            raise ValueError('steering and throttle channels must differ')
        for value in (self.steering_gain, self.steering_offset, self.throttle_gain):
            if not math.isfinite(value):
                raise ValueError('hardware gains and offset must be finite')
        if not 0 < abs(self.throttle_gain) <= 1:
            raise ValueError('abs(throttle_gain) must be in (0, 1]')
        if self.steering_gain == 0 or abs(self.steering_gain) + abs(self.steering_offset) > 1:
            raise ValueError('steering gain must be nonzero; abs(gain) + abs(offset) must be <= 1')


class MockBackend:
    def __init__(self):
        self.command = (0.0, 0.0)

    def write(self, throttle, steering):
        self.command = (throttle, steering)

    def stop(self):
        self.command = (0.0, 0.0)


class JetRacerBackend:
    def __init__(self, config: HardwareConfig):
        from jetracer.nvidia_racecar import NvidiaRacecar

        # Pass channel/calibration traits before ServoKit is created.
        self.car = NvidiaRacecar(**vars(config))
        self.stop()

    def write(self, throttle, steering):
        # Neutral first: a steering failure must not prevent a stop request.
        if throttle == 0.0:
            self.car.throttle_motor.throttle = 0.0
        self.car.steering = steering
        self.car.throttle = throttle

    def stop(self):
        # Traitlets does not notify for unchanged values. Explicitly write PWM
        # neutral even when the software throttle already equals zero.
        # Attempt both channels even if one I2C operation fails.
        try:
            self.car.throttle_motor.throttle = 0.0
            self.car.throttle = 0.0
        finally:
            self.car.steering_motor.throttle = self.car.steering_offset
            self.car.steering = 0.0
