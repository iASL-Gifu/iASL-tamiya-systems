"""学習成果物を読むROS非依存の推論API。"""

import json
from pathlib import Path

import numpy as np
import torch

from .model import TinyLidarNet
from .devices import resolve_device
from .preprocessing import preprocess_scan
from .spec import read_spec


class Predictor:
    def __init__(self, model_dir, device='cpu'):
        model_dir = Path(model_dir).expanduser()
        self.config = read_spec(json.loads((model_dir / 'metadata.json').read_text()))
        self.device = resolve_device(torch, device)
        self.model = TinyLidarNet(self.config.sample_count)
        weights = torch.load(model_dir / 'weights.pt', map_location='cpu', weights_only=True)
        self.model.load_state_dict(weights, strict=True)
        if not all(torch.isfinite(value).all().item() for value in self.model.state_dict().values()):
            raise ValueError('モデル重みに非有限値があります')
        self.model.to(self.device).eval()

    def predict(self, ranges, angle_min, angle_increment, range_min, range_max):
        scan = preprocess_scan(ranges, angle_min, angle_increment, range_min, range_max, self.config)
        tensor = torch.from_numpy(np.asarray(scan, dtype=np.float32)).reshape(1, 1, -1).to(self.device)
        with torch.inference_mode():
            result = self.model(tensor).cpu().numpy()[0]
        if result.shape != (2,) or not np.isfinite(result).all() or (np.abs(result) > 1).any():
            raise ValueError('推論出力が不正です')
        return float(result[0]), float(result[1])
