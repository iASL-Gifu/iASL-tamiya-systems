"""日時別保存とSCPの選択・転送処理を、標準ライブラリだけで確認する。"""

from contextlib import redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'python_ws/tinylidarnet/src')]

import jetson_transfer_remote as remote
import transfer_jetson as transfer
from tinylidarnet.run_paths import create_run_directory


def run_remote(action, root, *args):
    output = io.StringIO()
    with patch.object(sys, 'argv', ['remote', action, str(root), *map(str, args)]), redirect_stdout(output):
        remote.main()
    return json.loads(output.getvalue())


class FakeConnection:
    """SSH/SCPのみを置き換える。ローカルの一時ファイルで転送処理を検証。"""
    def __init__(self, bags=(), fail=False):
        self.bags = list(bags)
        self.fail = fail

    def remote(self, action, root, *args):
        if action == 'list-bags':
            return {'bags': self.bags, 'warnings': []}
        return run_remote(action, root, *args)

    def download(self, source, destination):
        if self.fail:
            raise OSError('模擬的な転送エラー')
        shutil.copyfile(source, destination)

    def upload(self, sources, destination):
        for source in sources:
            shutil.copyfile(source, Path(destination) / source.name)
            if self.fail:
                raise OSError('模擬的な転送エラー')


class TrainingOutputTests(unittest.TestCase):
    def test_timestamp_and_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stamp = datetime(2026, 9, 11, 12, 34)
            first = create_run_directory(root, stamp)
            (first / 'weights.pt').write_text('keep')
            second = create_run_directory(root, stamp)
            self.assertEqual(first.relative_to(root).as_posix(), '09-11/12-34')
            self.assertEqual(second.relative_to(root).as_posix(), '09-11/12-34_02')
            self.assertEqual((first / 'weights.pt').read_text(), 'keep')


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='transfer-test-')
        self.root = Path(self.temporary.name)
        self.jetson = self.root / 'jetson'
        self.laptop = self.root / 'laptop'
        self.jetson.mkdir()
        self.laptop.mkdir()
        self.outputs = self.laptop / 'python_ws/tinylidarnet/outputs'

    def tearDown(self):
        self.temporary.cleanup()

    def bag(self, name):
        record_root = self.jetson / 'record'
        directory = record_root / name
        directory.mkdir(parents=True)
        (directory / 'metadata.yaml').write_text('metadata')
        (directory / 'part0.mcap').write_bytes(b'first')
        (directory / 'part1.mcap').write_bytes(b'second')
        (directory / 'unrelated.txt').write_text('not a bag')
        document = {'rosbag2_bagfile_information': {
            'relative_file_paths': ['part0.mcap', 'part1.mcap'],
            'message_count': 123, 'duration': {'nanoseconds': 2_500_000_000},
        }}
        result = remote.describe_bag(record_root, directory / 'metadata.yaml', document)
        self.assertEqual(result['seconds'], 2.5)
        return result

    def model(self, name, complete=True):
        directory = self.outputs / name
        directory.mkdir(parents=True)
        (directory / 'weights.pt').write_bytes(b'weights')
        if complete:
            (directory / 'metadata.json').write_text('{}')
        (directory / 'history.json').write_text('[]')
        return directory

    def test_multiple_selection_and_rejection(self):
        self.assertEqual(transfer.select_indices('1,3 2-4 1', 4), [0, 2, 1, 3])
        self.assertEqual(transfer.select_indices('all', 3), [0, 1, 2])
        for value in ('', '0', '4', '2-1', '1;exit', '-1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                transfer.select_indices(value, 3)

    def test_paths_cannot_escape_or_expand_in_remote_shell(self):
        for value in ('../data', '/etc/passwd', 'file;pwd', 'space name', '*', '$HOME'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                remote.safe_path(value)

    def test_multiple_bags_include_all_metadata_members(self):
        bags = [self.bag('run01'), self.bag('run02')]
        with patch.object(transfer, 'PROJECT_ROOT', self.laptop), patch('builtins.input', return_value='all'), redirect_stdout(io.StringIO()):
            count = transfer.download_bags(FakeConnection(bags), str(self.jetson))
            transfer.download_bags(FakeConnection(bags), str(self.jetson))
        self.assertEqual(count, 2)
        for name in ('run01', 'run02', 'run01_02', 'run02_02'):
            directory = self.laptop / 'record' / name
            self.assertEqual(sorted(path.name for path in directory.iterdir()),
                             ['metadata.yaml', 'part0.mcap', 'part1.mcap'])
        self.assertFalse(list((self.laptop / 'record').glob('.download-*')))

    def test_failed_download_does_not_leave_a_finished_bag(self):
        bag = self.bag('run01')
        with patch.object(transfer, 'PROJECT_ROOT', self.laptop), patch('builtins.input', return_value='1'), redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                transfer.download_bags(FakeConnection([bag], fail=True), str(self.jetson))
        self.assertEqual(list((self.laptop / 'record').iterdir()), [])

    def test_missing_bag_member_is_rejected(self):
        self.bag('run01')
        document = {'rosbag2_bagfile_information': {'relative_file_paths': ['missing.mcap']}}
        with self.assertRaises(ValueError):
            remote.describe_bag(self.jetson / 'record', self.jetson / 'record/run01/metadata.yaml', document)

    def test_models_include_metadata_and_do_not_overwrite(self):
        self.model('09-11/12-34')
        self.model('09-11/12-35')
        self.model('09-11/incomplete', complete=False)
        self.assertEqual(len(transfer.list_models(self.outputs)), 2)
        with patch.object(transfer, 'OUTPUT_ROOT', self.outputs), patch('builtins.input', return_value='all'), redirect_stdout(io.StringIO()):
            count = transfer.upload_models(FakeConnection(), str(self.jetson))
            transfer.upload_models(FakeConnection(), str(self.jetson))
        self.assertEqual(count, 2)
        output = self.jetson / 'python_ws/tinylidarnet/outputs'
        for name in ('12-34', '12-35', '12-34_02', '12-35_02'):
            self.assertEqual(sorted(p.name for p in (output / '09-11' / name).iterdir()),
                             ['history.json', 'metadata.json', 'weights.pt'])
        self.assertFalse(list(output.glob('.upload-*')))

    def test_failed_upload_cleans_up_its_staging(self):
        self.model('09-11/12-34')
        with patch.object(transfer, 'OUTPUT_ROOT', self.outputs), patch('builtins.input', return_value='1'), redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                transfer.upload_models(FakeConnection(fail=True), str(self.jetson))
        self.assertEqual(list((self.jetson / 'python_ws/tinylidarnet/outputs').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
