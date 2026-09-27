"""モデルとデータセットの共通仕様（標準ライブラリのみ）。"""

from dataclasses import asdict, dataclass
import math

SCHEMA_VERSION = 1
ARCHITECTURE = 'tinylidarnet_1d_v1'
TARGET_NAMES = ['steering', 'throttle']
CONVOLUTIONS = ((24, 10, 4), (36, 8, 4), (48, 4, 2), (64, 3, 1), (64, 3, 1))


def feature_size(sample_count):
    length = sample_count
    for _, kernel, stride in CONVOLUTIONS:
        length = (length - kernel) // stride + 1
        if length <= 0:
            raise ValueError('sample_countがCNNの入力に必要な点数を満たしていません')
    return length * CONVOLUTIONS[-1][0]


@dataclass(frozen=True)
class ScanConfig:
    sample_count: int = 1081
    angle_min_deg: float = -135.0
    angle_max_deg: float = 135.0
    max_distance: float = 30.0
    min_finite_fraction: float = 0.1

    def __post_init__(self):
        if type(self.sample_count) is not int or self.sample_count < 2:
            raise ValueError('sample_countには2以上の整数を指定してください')
        feature_size(self.sample_count)
        values = (self.angle_min_deg, self.angle_max_deg, self.max_distance, self.min_finite_fraction)
        if not all(math.isfinite(x) for x in values):
            raise ValueError('前処理設定には有限値を指定してください')
        if not -180 <= self.angle_min_deg < self.angle_max_deg <= 180:
            raise ValueError('角度範囲は-180〜180度内の昇順で指定してください')
        if self.max_distance <= 0 or not 0 < self.min_finite_fraction <= 1:
            raise ValueError('距離上限は正、有効点率は(0, 1]で指定してください')


def metadata(config):
    return {
        'schema_version': SCHEMA_VERSION,
        'architecture': ARCHITECTURE,
        'target_names': TARGET_NAMES.copy(),
        'preprocessing': asdict(config),
    }


def read_spec(data):
    if data.get('schema_version') != SCHEMA_VERSION or data.get('architecture') != ARCHITECTURE:
        raise ValueError('未対応のデータ／モデル仕様です')
    if data.get('target_names') != TARGET_NAMES:
        raise ValueError('教師値の順序は[steering, throttle]である必要があります')
    return ScanConfig(**data['preprocessing'])
