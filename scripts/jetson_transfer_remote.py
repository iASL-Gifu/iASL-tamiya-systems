"""SSH経由でJetson上に送って実行する補助処理。ローカルに設置不要。"""

import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile


def safe_path(value, absolute=False):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', value):
        raise ValueError('転送先のパス・bagファイル名には英数字、_、-、.、/を使用してください')
    path = PurePosixPath(value)
    if '..' in path.parts or path.is_absolute() != absolute or str(path) == '.':
        raise ValueError(f'不正なパスです: {value}')
    return path


def reserve_directory(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate = path if index == 1 else path.with_name(f'{path.name}_{index:02d}')
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            index += 1


def describe_bag(record_root, metadata_path, document):
    directory = metadata_path.parent
    if metadata_path.is_symlink() or not metadata_path.resolve().is_relative_to(record_root.resolve()):
        raise ValueError('record外へのリンクは対象にできません')
    if not isinstance(document, dict) or not isinstance(document.get('rosbag2_bagfile_information'), dict):
        raise ValueError('rosbag2のmetadata.yamlではありません')
    info = document['rosbag2_bagfile_information']
    duration = info.get('duration', {})
    if not isinstance(duration, dict):
        raise ValueError('metadata.yamlのdurationが不正です')
    relative = str(directory.relative_to(record_root))
    safe_path(relative)
    files = info['relative_file_paths']
    if not isinstance(files, list) or not files:
        raise ValueError('metadata.yamlにbagファイルの一覧がありません')
    for name in files:
        relative_file = safe_path(name)
        path = directory / relative_file
        if (not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to(directory.resolve())):
            raise ValueError(f'bagファイルが見つからないか、外部リンクです: {name}')
    files = list(dict.fromkeys(files))
    if 'metadata.yaml' in files:
        raise ValueError('bagファイル一覧にmetadata.yamlは指定できません')
    return {
        'relative': relative, 'files': files + ['metadata.yaml'],
        'messages': int(info.get('message_count', 0)),
        'seconds': int(duration.get('nanoseconds', 0)) / 1e9,
        'bytes': sum((directory / name).stat().st_size for name in files) + metadata_path.stat().st_size,
    }


def main():
    action, root_string, *arguments = sys.argv[1:]
    safe_path(root_string, absolute=True)
    root = Path(root_string).resolve(strict=True)
    safe_path(str(root), absolute=True)
    outputs = root / 'python_ws' / 'tinylidarnet' / 'outputs'
    if action == 'list-bags':
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError('Jetsonで sudo apt install python3-yaml を実行してください') from exc
        record_root = root / 'record'
        if not record_root.is_dir():
            raise ValueError(f'収録ディレクトリがありません: {record_root}')
        bags, warnings = [], []
        for path in sorted(record_root.rglob('metadata.yaml')):
            try:
                bags.append(describe_bag(record_root, path, yaml.safe_load(path.read_text())))
            except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as exc:
                warnings.append(f'{path.parent.name}: {exc}')
        result = {'bags': bags, 'warnings': warnings}
    elif action == 'prepare-upload':
        outputs.mkdir(parents=True, exist_ok=True)
        result = {'staging': str(Path(tempfile.mkdtemp(prefix='.upload-', dir=outputs)))}
    elif action in ('finish-upload', 'cancel-upload'):
        staging = Path(arguments[0])
        if (staging.parent.resolve() != outputs.resolve() or not staging.name.startswith('.upload-')
                or staging.is_symlink() or not staging.is_dir()):
            raise ValueError('転送用一時ディレクトリが不正です')
        if action == 'cancel-upload':
            shutil.rmtree(staging)
            result = {'cancelled': True}
        else:
            relative = safe_path(arguments[1])
            if not all((staging / name).is_file() for name in ('weights.pt', 'metadata.json')):
                raise ValueError('重みまたはmetadata.jsonの転送が完了していません')
            destination = reserve_directory(outputs / relative)
            try:
                staging.rename(destination)
            except OSError:
                destination.rmdir()
                raise
            result = {'destination': str(destination)}
    else:
        raise ValueError('未対応の操作です')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Jetson側の処理に失敗しました: {exc}', file=sys.stderr)
        sys.exit(1)
