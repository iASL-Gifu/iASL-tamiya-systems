"""転送メニュー。ノートPC側はPython標準ライブラリとssh/scpのみ使用。"""

import argparse
import ipaddress
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

from jetson_transfer_remote import reserve_directory, safe_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / 'python_ws' / 'tinylidarnet' / 'outputs'
REMOTE_SCRIPT = Path(__file__).with_name('jetson_transfer_remote.py')


def select_indices(value, count):
    if value.strip().lower() == 'all':
        return list(range(count))
    indices = []
    for token in value.replace(',', ' ').split():
        parts = token.split('-')
        if len(parts) not in (1, 2) or any(not part.isascii() or not part.isdigit() for part in parts):
            raise ValueError('番号は「1 3」「1,3」「1-3」またはallで指定してください')
        start, end = int(parts[0]), int(parts[-1])
        if not 1 <= start <= end <= count:
            raise ValueError('一覧にある番号を指定してください')
        indices.extend(range(start - 1, end))
    if not indices:
        raise ValueError('コピーする番号を指定してください')
    return list(dict.fromkeys(indices))


def choose(count):
    while True:
        value = input('コピーする番号（例: 1 3 / 1-3 / all、空欄で中止）: ')
        if not value.strip():
            return []
        try:
            return select_indices(value, count)
        except ValueError as exc:
            print(exc)


def list_models(root):
    models = []
    if not root.is_dir():
        return models
    for weight in sorted(root.rglob('weights.pt')):
        directory = weight.parent
        if (weight.is_symlink() or not directory.resolve().is_relative_to(root.resolve())
                or not (directory / 'metadata.json').is_file()
                or (directory / 'metadata.json').is_symlink()):
            continue
        relative = str(directory.relative_to(root))
        safe_path(relative)
        models.append({'relative': relative, 'directory': directory, 'bytes': weight.stat().st_size})
    return models


class Connection:
    def __init__(self, ip, user, socket):
        address = ipaddress.ip_address(ip)
        self.host = f'{user}@{address}'
        self.scp_host = f'{user}@[{address}]' if address.version == 6 else self.host
        self.options = ['-o', 'ConnectTimeout=10', '-o', 'ControlMaster=auto',
                        '-o', 'ControlPersist=60', '-o', f'ControlPath={socket}']
        self.socket = socket

    def remote(self, action, root, *args):
        command = 'python3 - ' + ' '.join(shlex.quote(str(value)) for value in (action, root, *args))
        result = subprocess.run(['ssh', *self.options, self.host, command],
                                input=REMOTE_SCRIPT.read_text(), text=True,
                                stdout=subprocess.PIPE, check=True)
        return json.loads(result.stdout)

    def remote_path(self, path):
        # 従来のSCPとSFTP方式の両方で、リモートシェル展開を起こさないパスに限定。
        safe_path(str(path), absolute=True)
        return f'{self.scp_host}:{path}'

    def download(self, source, destination):
        subprocess.run(['scp', *self.options, self.remote_path(source), str(destination)], check=True)

    def upload(self, sources, destination):
        subprocess.run(['scp', *self.options, *[str(path) for path in sources],
                        self.remote_path(destination) + '/'], check=True)

    def close(self):
        if Path(self.socket).exists():
            subprocess.run(['ssh', '-o', f'ControlPath={self.socket}', '-O', 'exit', self.host],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)


def download_bags(connection, remote_root):
    listing = connection.remote('list-bags', remote_root)
    for warning in listing['warnings']:
        print(f'一覧から除外: {warning}')
    bags = listing['bags']
    if not bags:
        print('転送可能なrosbagが見つかりませんでした。')
        return 0
    for index, bag in enumerate(bags, 1):
        print(f"[{index}] {bag['relative']} | {bag['seconds']:.1f}秒 | "
              f"{bag['messages']}件 | {bag['bytes'] / 1024**2:.1f} MiB")
    selected = choose(len(bags))
    destination_root = PROJECT_ROOT / 'record'
    completed = 0
    for index in selected:
        bag = bags[index]
        relative = safe_path(bag['relative'])
        destination_root.mkdir(parents=True, exist_ok=True)
        # 完了までは隠し一時ディレクトリ。失敗時は今回の一時ファイルのみ削除。
        with tempfile.TemporaryDirectory(prefix='.download-', dir=destination_root) as temporary:
            staging = Path(temporary)
            for filename in bag['files']:
                member = safe_path(filename)
                local_file = staging / member
                local_file.parent.mkdir(parents=True, exist_ok=True)
                connection.download(Path(remote_root) / 'record' / relative / member, local_file)
            destination = reserve_directory(destination_root / relative)
            try:
                staging.rename(destination)
            except OSError:
                destination.rmdir()
                raise
        completed += 1
        print(f'取得しました: {destination}')
    return completed


def upload_models(connection, remote_root):
    models = list_models(OUTPUT_ROOT)
    if not models:
        print(f'weights.ptとmetadata.jsonがそろったモデルがありません: {OUTPUT_ROOT}')
        return 0
    for index, model in enumerate(models, 1):
        print(f"[{index}] {model['relative']}/weights.pt | {model['bytes'] / 1024**2:.1f} MiB")
    completed = 0
    for index in choose(len(models)):
        model = models[index]
        directory = model['directory']
        files = [directory / 'weights.pt', directory / 'metadata.json']
        if (directory / 'history.json').is_file() and not (directory / 'history.json').is_symlink():
            files.append(directory / 'history.json')
        staging = connection.remote('prepare-upload', remote_root)['staging']
        try:
            connection.upload(files, staging)
            result = connection.remote('finish-upload', remote_root, staging, model['relative'])
        except BaseException:
            try:
                connection.remote('cancel-upload', remote_root, staging)
            except Exception:
                print(f'一時データを削除できませんでした。Jetson側を確認してください: {staging}', file=sys.stderr)
            raise
        completed += 1
        print(f"送信しました: {result['destination']}")
    return completed


def main():
    parser = argparse.ArgumentParser(description='Jetsonのrosbag取得／学習済みモデル送信')
    parser.add_argument('--user', default='tamiya', help='Jetsonのユーザー名（初期値: tamiya）')
    args = parser.parse_args()
    if (not args.user or args.user.startswith('-')
            or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for char in args.user)):
        parser.error('ユーザー名には英数字・_・-を使用してください')
    for command in ('ssh', 'scp'):
        if shutil.which(command) is None:
            parser.error(f'{command}が見つかりません')
    print('[1] JetsonのrosbagをノートPCへ取得')
    print('[2] ノートPCの学習済みモデルをJetsonへ送信')
    choice = input('操作を選択してください (1-2): ').strip()
    if choice not in ('1', '2'):
        raise ValueError('1または2を指定してください')
    ip = str(ipaddress.ip_address(input('JetsonのIPアドレス: ').strip()))
    default_root = f'/home/{args.user}/iASL-tamiya-systems'
    remote_root = input(f'Jetsonのプロジェクトルート [{default_root}]: ').strip() or default_root
    safe_path(remote_root, absolute=True)
    # SSH接続を再利用し、複数ファイルごとのパスワード入力を避ける。
    with tempfile.TemporaryDirectory(prefix='jt-', dir='/tmp') as temporary:
        connection = Connection(ip, args.user, str(Path(temporary) / 'ssh'))
        try:
            count = download_bags(connection, remote_root) if choice == '1' else upload_models(connection, remote_root)
            print(f'完了: {count}件を転送しました。')
        finally:
            connection.close()


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\n中止しました。', file=sys.stderr)
        sys.exit(130)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as exc:
        print(f'転送に失敗しました: {exc}', file=sys.stderr)
        sys.exit(1)
