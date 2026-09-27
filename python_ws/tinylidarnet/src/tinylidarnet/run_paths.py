"""学習実行ごとの出力先を、既存データを上書きせず作る。"""

from datetime import datetime
from pathlib import Path


def create_run_directory(root, started_at=None):
    started_at = started_at or datetime.now().astimezone()
    parent = Path(root).expanduser() / started_at.strftime('%m-%d')
    parent.mkdir(parents=True, exist_ok=True)
    name = started_at.strftime('%H-%M')
    index = 1
    while True:
        candidate = parent / (name if index == 1 else f'{name}_{index:02d}')
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            index += 1
