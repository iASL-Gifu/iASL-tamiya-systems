"""標準ライブラリのみ。PyTorch・NumPy・ROSをインポートしない。"""

import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_ws' / 'tinylidarnet' / 'src'))

from tinylidarnet.alignment import LabelMatcher, manual_intervals
from tinylidarnet.preprocessing import preprocess_scan, scan_is_fresh
from tinylidarnet.spec import ScanConfig, feature_size, metadata, read_spec


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.config = ScanConfig()
        self.angle_min = math.radians(-135)
        self.increment = math.radians(0.25)

    def preprocess(self, ranges, **kwargs):
        options = dict(angle_min=self.angle_min, angle_increment=self.increment,
                       range_min=0.05, range_max=30.0, config=self.config)
        options.update(kwargs)
        return preprocess_scan(ranges, **options)

    def test_hokuyo_defaults_and_order(self):
        ranges = [1 + 29 * index / 1080 for index in range(1081)]
        result = self.preprocess(ranges)
        self.assertEqual(len(result), 1081)
        self.assertAlmostEqual(result[0], 1 / 30)
        self.assertAlmostEqual(result[-1], 1.0)
        self.assertAlmostEqual(result[540], 15.5 / 30)
        self.assertEqual(result, sorted(result))

    def test_negative_increment_preserves_physical_direction(self):
        ranges = [1 + index / 100 for index in range(1081)]
        expected = self.preprocess(ranges)
        actual = self.preprocess(list(reversed(ranges)), angle_min=math.radians(135),
                                 angle_increment=-self.increment)
        self.assertEqual(actual, expected)

    def test_360_scan_wraps_front_sector(self):
        ranges = [1 + index / 100 for index in range(1441)]
        result = self.preprocess(ranges, angle_min=0.0)
        self.assertAlmostEqual(result[540], ranges[0] / 30)
        self.assertAlmostEqual(result[0], ranges[900] / 30)
        self.assertAlmostEqual(result[-1], ranges[540] / 30)

    def test_invalid_values_and_clipping(self):
        ranges = [15.0] * 1081
        ranges[:7] = [float('nan'), float('inf'), -float('inf'), 0.01, -1.0, 31.0, 45.0]
        result = self.preprocess(ranges)
        self.assertEqual(result[:7], [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(result[7], 0.5)
        result = self.preprocess([45.0] * 1081, range_max=60.0)
        self.assertEqual(result, [1.0] * 1081)

    def test_no_return_is_limited_by_sensor_range(self):
        ranges = [5.0] * 1081
        ranges[0] = float('inf')
        self.assertAlmostEqual(self.preprocess(ranges, range_max=20.0)[0], 20 / 30)

    def test_blind_scan_is_rejected(self):
        for value in (float('inf'), float('nan'), -1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.preprocess([value] * 1081)

    def test_missing_sector_is_rejected(self):
        with self.assertRaises(ValueError):
            self.preprocess([10.0] * 721, angle_min=math.radians(-90))

    def test_invalid_geometry_is_rejected(self):
        for kwargs in ({'angle_increment': 0.0}, {'range_max': float('inf')},
                       {'range_min': 30.0}, {'angle_min': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.preprocess([10.0] * 1081, **kwargs)

    def test_timestamp_validation(self):
        now = 10_000_000_000
        self.assertTrue(scan_is_fresh(now - 100_000_000, now, 0.2))
        self.assertFalse(scan_is_fresh(now - 300_000_000, now, 0.2))
        self.assertFalse(scan_is_fresh(now + 100_000_000, now, 0.2))
        self.assertFalse(scan_is_fresh(0, now, 0.2))


class SpecTests(unittest.TestCase):
    def test_saved_config_matches_user_hardware(self):
        config = ScanConfig(**json.loads((ROOT / 'python_ws/tinylidarnet/config/scan.json').read_text()))
        self.assertEqual(config, ScanConfig())
        self.assertEqual((config.sample_count, config.angle_min_deg, config.angle_max_deg,
                          config.max_distance), (1081, -135.0, 135.0, 30.0))
        self.assertEqual(read_spec(json.loads(json.dumps(metadata(config)))), config)

    def test_feature_size_for_published_architecture(self):
        self.assertEqual(feature_size(1081), 28 * 64)
        self.assertEqual(feature_size(541), 11 * 64)
        with self.assertRaises(ValueError):
            ScanConfig(sample_count=20)

    def test_incompatible_target_order_is_rejected(self):
        data = metadata(ScanConfig())
        data['target_names'] = ['throttle', 'steering']
        with self.assertRaises(ValueError):
            read_spec(data)

    def test_invalid_parameters_are_rejected(self):
        for kwargs in ({'sample_count': 1081.0}, {'max_distance': 0.0},
                       {'angle_min_deg': 140}, {'min_finite_fraction': 0.0},
                       {'max_distance': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ScanConfig(**kwargs)


class AlignmentTests(unittest.TestCase):
    def test_manual_intervals_split_on_mode_change_and_missing_messages(self):
        modes = [(0, 'manual'), (20, 'manual'), (40, 'auto'), (60, 'manual'),
                 (80, 'manual'), (200, 'manual'), (220, 'manual')]
        self.assertEqual(manual_intervals(modes, 30), [(0, 20), (60, 80), (200, 220)])

    def test_previous_command_and_transition_guard(self):
        modes = [(t, 'manual') for t in range(0, 301, 20)]
        matcher = LabelMatcher([(80, 0.2, 0.1), (140, 0.3, 0.2)], modes,
                               max_age_ns=50, transition_guard_ns=40)
        self.assertEqual(matcher.match(100), (0.2, 0.1))
        self.assertEqual(matcher.match(150), (0.3, 0.2))
        self.assertIsNone(matcher.match(70))  # 未来の指令を教師値に使わない。
        self.assertIsNone(matcher.match(220))  # 古い指令を使わない。

    def test_boundaries_and_auto_are_excluded(self):
        modes = [(t, 'manual' if 40 <= t <= 200 else 'auto') for t in range(0, 301, 20)]
        commands = [(t, 0.1, 0.2) for t in range(0, 301, 20)]
        matcher = LabelMatcher(commands, modes, max_age_ns=30, transition_guard_ns=40)
        for stamp in (0, 20, 40, 60, 180, 200, 220, 300):
            with self.subTest(stamp=stamp):
                self.assertIsNone(matcher.match(stamp))
        self.assertEqual(matcher.match(100), (0.1, 0.2))

    def test_no_command_or_mode_has_no_label(self):
        for commands, modes in (([], []), ([(10, 0.0, 0.2)], []), ([], [(10, 'manual')])):
            self.assertIsNone(LabelMatcher(commands, modes).match(10))


if __name__ == '__main__':
    unittest.main()
