"""TinyLidarNetの5層Conv1D + 4層全結合構成をPyTorchで実装。"""

from torch import nn

from .spec import CONVOLUTIONS, feature_size


class TinyLidarNet(nn.Module):
    def __init__(self, sample_count=1081):
        super().__init__()
        layers = []
        channels = 1
        for output_channels, kernel, stride in CONVOLUTIONS:
            layers.extend((nn.Conv1d(channels, output_channels, kernel, stride), nn.ReLU()))
            channels = output_channels
        self.features = nn.Sequential(*layers)
        self.regressor = nn.Sequential(
            nn.Flatten(),
            nn.Linear(feature_size(sample_count), 100), nn.ReLU(),
            nn.Linear(100, 50), nn.ReLU(),
            nn.Linear(50, 10), nn.ReLU(),
            nn.Linear(10, 2), nn.Tanh(),
        )

    def forward(self, scans):
        # 入力[B, 1, N]、出力[B, 2]（操舵、スロットル）。
        return self.regressor(self.features(scans))
