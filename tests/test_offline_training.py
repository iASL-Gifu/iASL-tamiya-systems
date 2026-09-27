"""デバイス選択とrosbagsアダプターを標準ライブラリのみで検証。"""

from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_ws/tinylidarnet/src'))

from tinylidarnet.bag_reader import BagReader, DRIVE_COMMAND_DEFINITION, DRIVE_COMMAND_TYPE
from tinylidarnet.devices import select_device, resolve_device


class DeviceTests(unittest.TestCase):
    def test_auto_prefers_cuda_then_mps_then_cpu(self):
        self.assertEqual(select_device('auto', 1, True), 'cuda')
        self.assertEqual(select_device('auto', 0, True), 'mps')
        self.assertEqual(select_device('auto', 0, False), 'cpu')

    def test_explicit_devices_do_not_silently_fall_back(self):
        self.assertEqual(select_device('mps', 0, True), 'mps')
        self.assertEqual(select_device('cuda:1', 2, False), 'cuda:1')
        self.assertEqual(select_device('cpu', 2, True), 'cpu')
        for value in ('mps', 'cuda', 'cuda:1', 'invalid'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                select_device(value)

    def test_torch_build_without_mps_attribute_can_use_cpu(self):
        fake_torch = types.SimpleNamespace(
            backends=types.SimpleNamespace(),
            cuda=types.SimpleNamespace(is_available=lambda: False),
            device=lambda name: name,
        )
        self.assertEqual(resolve_device(fake_torch, 'auto'), 'cpu')


class BagReaderTests(unittest.TestCase):
    def test_custom_definition_matches_ros_interface(self):
        path = ROOT / 'ros2_ws/src/rc_car_interfaces/msg/DriveCommand.msg'
        fields = [line.strip() for line in path.read_text().splitlines()
                  if line.strip() and not line.lstrip().startswith('#')]
        self.assertEqual(fields, DRIVE_COMMAND_DEFINITION.strip().splitlines())

    def test_registered_custom_type_and_filtered_reading(self):
        scan = types.SimpleNamespace(topic='/scan', msgtype='sensor_msgs/msg/LaserScan')
        command = types.SimpleNamespace(topic='/drive/applied', msgtype=DRIVE_COMMAND_TYPE)
        store = Mock()
        backend = Mock()
        backend.connections = [scan, command]
        backend.messages.return_value = [(scan, 123, memoryview(b'data'))]
        backend.deserialize.return_value = 'decoded'
        any_reader = Mock(return_value=backend)
        get_types = Mock(return_value={'custom': 'definition'})
        modules = {
            'rosbags': types.ModuleType('rosbags'),
            'rosbags.highlevel': types.ModuleType('rosbags.highlevel'),
            'rosbags.typesys': types.ModuleType('rosbags.typesys'),
        }
        modules['rosbags.highlevel'].AnyReader = any_reader
        modules['rosbags.typesys'].Stores = types.SimpleNamespace(ROS2_HUMBLE='humble')
        modules['rosbags.typesys'].get_typestore = lambda _: store
        modules['rosbags.typesys'].get_types_from_msg = get_types
        with patch.dict(sys.modules, modules):
            with BagReader(Path('/example/bag')) as reader:
                reader.validate_topics({'/scan': 'sensor_msgs/msg/LaserScan'})
                self.assertEqual(list(reader.messages(['/scan'])), [('/scan', b'data', 123)])
                self.assertEqual(reader.deserialize(b'data', scan.msgtype), 'decoded')
                backend.messages.assert_called_once_with(connections=[scan])
                # AnyReaderはconnections=[]を「全件」と解釈するため、空の対象は読まない。
                self.assertEqual(list(reader.messages(['/missing'])), [])
                self.assertEqual(backend.messages.call_count, 1)
                with self.assertRaises(ValueError):
                    reader.validate_topics({'/scan': 'wrong/msg/Type'})
        get_types.assert_called_once_with(DRIVE_COMMAND_DEFINITION, DRIVE_COMMAND_TYPE)
        store.register.assert_called_once_with({'custom': 'definition'})
        any_reader.assert_called_once_with([Path('/example/bag')], default_typestore=store)
        backend.open.assert_called_once()
        backend.close.assert_called_once()

    def test_reader_closes_on_conversion_error(self):
        reader = BagReader('/example/bag')
        reader.reader = Mock()
        reader.__exit__(ValueError, ValueError('test'), None)
        reader.reader.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
