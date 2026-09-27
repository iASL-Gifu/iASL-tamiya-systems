"""NPZデータセットの読み込みと整合性確認。ROSには依存しない。"""

import json
from pathlib import Path

import numpy as np

from .spec import read_spec


def load_sessions(paths):
    scan_batches, target_batches, session_ids = [], [], set()
    config = None
    seen = set()
    for filename in paths:
        path = Path(filename).resolve()
        if path in seen:
            raise ValueError(f'データセットが重複しています: {path}')
        seen.add(path)
        with np.load(path, allow_pickle=False) as archive:
            info = json.loads(str(archive['metadata'].item()))
            current_config = read_spec(info)
            scans = np.asarray(archive['scans'], dtype=np.float32)
            targets = np.asarray(archive['targets'], dtype=np.float32)
        if config is not None and config != current_config:
            raise ValueError('データセット間で前処理設定が異なります')
        config = current_config
        if scans.ndim != 2 or scans.shape[1] != config.sample_count or len(scans) == 0:
            raise ValueError(f'scansは空でない[N, {config.sample_count}]である必要があります: {path}')
        if targets.shape != (len(scans), 2):
            raise ValueError(f'targetsは[N, 2]である必要があります: {path}')
        if not np.isfinite(scans).all() or not ((0 <= scans) & (scans <= 1)).all():
            raise ValueError(f'scansに非有限値または正規化範囲外の値があります: {path}')
        if not np.isfinite(targets).all() or not (np.abs(targets) <= 1).all():
            raise ValueError(f'targetsに非有限値または範囲外の値があります: {path}')
        session_id = info.get('session_id')
        if not isinstance(session_id, str) or not session_id:
            raise ValueError('データセットに収録セッションIDがありません')
        if session_id in session_ids:
            raise ValueError('同じ収録セッションが重複しています')
        session_ids.add(session_id)
        scan_batches.append(scans)
        target_batches.append(targets)
    if config is None:
        raise ValueError('データセットを指定してください')
    return np.concatenate(scan_batches), np.concatenate(target_batches), config, session_ids
