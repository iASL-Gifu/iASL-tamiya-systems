"""Run from the repository root: python3 -m unittest discover -s tests -v."""

from dataclasses import replace
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / 'ros2_ws' / 'src'
sys.path[:0] = [str(SRC / 'teleop_manager'), str(SRC / 'jetracer_driver')]

from teleop_manager.controller import Command, Config, Controller
from jetracer_driver.backend import HardwareConfig, JetRacerBackend, MockBackend
from jetracer_driver.watchdog import Watchdog


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller(Config())

    def joy(self, now=0.0, manual=False, auto=False, axes=None):
        return self.controller.update_joy(
            [0.5, 1.0] if axes is None else axes,
            [0, 0, int(auto), int(manual)], now,
        )

    def test_startup_and_no_button_are_neutral(self):
        self.assertEqual(self.controller.output(0), ('stopped', Command()))
        self.joy()
        self.assertEqual(self.controller.output(0), ('stopped', Command()))

    def test_manual_scaled_and_button_release_stops(self):
        self.joy(manual=True)
        self.assertEqual(self.controller.output(0.1), ('manual', Command(0.25, 0.5)))
        self.joy(now=0.15)
        self.assertEqual(self.controller.output(0.15), ('stopped', Command()))

    def test_both_buttons_stop(self):
        self.joy(manual=True, auto=True)
        self.assertEqual(self.controller.output(0.1), ('stopped', Command()))

    def test_joy_timeout_stops_manual_and_auto(self):
        for manual in (True, False):
            with self.subTest(manual=manual):
                self.setUp()
                self.joy(manual=manual, auto=not manual)
                self.controller.update_auto(0.2, -0.3, 0.1)
                self.assertEqual(self.controller.output(0.3), ('stopped', Command()))

    def test_auto_requires_new_command_after_button_press(self):
        self.controller.update_auto(0.2, 0.3, 0)
        self.joy(now=0.01, auto=True)
        self.assertEqual(self.controller.output(0.02), ('stopped', Command()))
        self.controller.update_auto(0.2, 0.3, 0.03)
        self.assertEqual(self.controller.output(0.04), ('auto', Command(0.2, 0.3)))

    def test_auto_timeout_with_fresh_joy_and_recovery(self):
        self.joy(auto=True)
        self.controller.update_auto(0.2, 0.3, 0)
        self.joy(now=0.2, auto=True)
        self.assertEqual(self.controller.output(0.3), ('stopped', Command()))
        self.controller.update_auto(0.1, 0.1, 0.31)
        self.assertEqual(self.controller.output(0.32), ('auto', Command(0.1, 0.1)))

    def test_mode_switch_discards_previous_auto_command(self):
        self.joy(auto=True)
        self.controller.update_auto(0.2, 0.3, 0.01)
        self.joy(now=0.02, manual=True)
        self.assertEqual(self.controller.output(0.02)[0], 'manual')
        self.joy(now=0.03, auto=True)
        self.assertEqual(self.controller.output(0.03), ('stopped', Command()))

    def test_joy_gap_requires_new_auto_even_without_timer_tick(self):
        self.controller = Controller(Config(auto_timeout=1.0))
        self.joy(auto=True)
        self.controller.update_auto(0.2, 0.3, 0.01)
        self.joy(now=0.31, auto=True)
        self.assertEqual(self.controller.output(0.32), ('stopped', Command()))

    def test_auto_clamped_and_does_not_override_manual(self):
        self.joy(auto=True)
        self.controller.update_auto(1.0, -1.0, 0.01)
        self.assertEqual(self.controller.output(0.02), ('auto', Command(0.25, -1.0)))
        self.joy(now=0.03, manual=True)
        self.controller.update_auto(-1.0, -1.0, 0.04)
        self.assertEqual(self.controller.output(0.05), ('manual', Command(0.25, 0.5)))

    def test_invalid_joy_stops_previous_command(self):
        for axes, buttons in [([], []), ([0.0], [0, 0, 0, 1]),
                              ([0.0, float('nan')], [0, 0, 0, 1]),
                              ([0.0, float('inf')], [0, 0, 0, 1]),
                              ([0.0, 1.1], [0, 0, 0, 1]),
                              ([0.0, 0.5], [0, 0, 0, 2])]:
            with self.subTest(axes=axes, buttons=buttons):
                self.joy(manual=True)
                self.assertFalse(self.controller.update_joy(axes, buttons, 0.1))
                self.assertEqual(self.controller.output(0.1), ('stopped', Command()))

    def test_invalid_auto_clears_previous_command(self):
        for value in (float('nan'), float('inf'), -1.01, 1.01):
            with self.subTest(value=value):
                self.joy(auto=True)
                self.controller.update_auto(0.2, 0.2, 0.01)
                self.assertFalse(self.controller.update_auto(value, 0.0, 0.02))
                self.assertEqual(self.controller.output(0.03), ('stopped', Command()))

    def test_axis_mapping_and_inversion(self):
        self.controller = Controller(Config(throttle_axis=3, steering_axis=2,
                                            throttle_inverted=True, steering_inverted=True))
        self.joy(manual=True, axes=[0.0, 0.0, 0.5, -1.0])
        self.assertEqual(self.controller.output(0.1), ('manual', Command(0.25, -0.5)))

    def test_invalid_config_rejected(self):
        for kwargs in ({'manual_button': -1}, {'manual_button': 2}, {'throttle_axis': 1.5},
                       {'max_throttle': 1.1}, {'joy_timeout': 0}, {'auto_timeout': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Config(**kwargs)


class WatchdogTests(unittest.TestCase):
    def test_startup_limit_timeout_and_recovery(self):
        watchdog = Watchdog()
        self.assertEqual(watchdog.output(0), (0.0, 0.0))
        self.assertTrue(watchdog.update(0.9, -0.5, 0))
        self.assertEqual(watchdog.output(0.1), (0.25, -0.5))
        self.assertEqual(watchdog.output(0.3), (0.0, 0.0))
        watchdog.update(-0.1, 0.1, 0.4)
        self.assertEqual(watchdog.output(0.41), (-0.1, 0.1))

    def test_invalid_command_clears_previous_output(self):
        watchdog = Watchdog()
        for command in ((float('nan'), 0), (0, float('inf')), (1.01, 0), (0, -1.01)):
            watchdog.update(0.2, 0.5, 0)
            self.assertFalse(watchdog.update(*command, now=0.1))
            self.assertEqual(watchdog.output(0.1), (0.0, 0.0))

    def test_invalid_config_rejected(self):
        for kwargs in ({'timeout': 0}, {'timeout': float('inf')}, {'max_throttle': -1},
                       {'max_steering': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Watchdog(**kwargs)

    def test_manager_loss_stops_driver_even_after_nonzero_command(self):
        controller = Controller(Config())
        watchdog = Watchdog()
        controller.update_joy([0.0, 1.0], [0, 0, 0, 1], 0)
        _, command = controller.output(0.01)
        watchdog.update(command.throttle, command.steering, 0.01)
        self.assertEqual(watchdog.output(0.1), (0.25, 0.0))
        self.assertEqual(watchdog.output(0.32), (0.0, 0.0))


class BackendTests(unittest.TestCase):
    def test_mock_needs_no_hardware_import(self):
        backend = MockBackend()
        backend.write(0.2, 0.3)
        self.assertEqual(backend.command, (0.2, 0.3))
        backend.stop()
        self.assertEqual(backend.command, (0.0, 0.0))

    def test_hardware_parameters_rejected_before_import(self):
        for kwargs in ({'throttle_channel': 0}, {'steering_channel': 16}, {'i2c_address': 0},
                       {'steering_offset': 0.9}, {'throttle_gain': 0}, {'steering_gain': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                HardwareConfig(**kwargs)

    def test_upstream_class_receives_configuration_and_explicit_neutral(self):
        # Stand-in for JetRacer only; does not require traitlets or ServoKit.
        class FakeCar:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.__dict__.update(kwargs)
                self.throttle = self.steering = 0.0
                self.throttle_motor = types.SimpleNamespace(throttle=0.8)
                self.steering_motor = types.SimpleNamespace(throttle=0.8)

        package = types.ModuleType('jetracer')
        module = types.ModuleType('jetracer.nvidia_racecar')
        module.NvidiaRacecar = FakeCar
        config = replace(HardwareConfig(), steering_offset=0.1)
        with patch.dict(sys.modules, {'jetracer': package, 'jetracer.nvidia_racecar': module}):
            backend = JetRacerBackend(config)
        self.assertEqual(backend.car.kwargs, vars(config))
        self.assertEqual(backend.car.throttle_motor.throttle, 0.0)
        self.assertEqual(backend.car.steering_motor.throttle, 0.1)
        backend.write(0.2, -0.3)
        self.assertEqual((backend.car.throttle, backend.car.steering), (0.2, -0.3))
        backend.car.throttle_motor.throttle = 0.8
        backend.stop()
        self.assertEqual(backend.car.throttle_motor.throttle, 0.0)
        self.assertEqual((backend.car.throttle, backend.car.steering), (0.0, 0.0))


if __name__ == '__main__':
    unittest.main()
