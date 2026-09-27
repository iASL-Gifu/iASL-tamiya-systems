"""学習・推論の実行デバイスを選ぶ。選択ロジックは標準ライブラリのみ。"""

import re


def select_device(requested, cuda_count=0, mps_available=False):
    if requested == 'auto':
        return 'cuda' if cuda_count else 'mps' if mps_available else 'cpu'
    if requested == 'cpu':
        return requested
    if requested == 'mps':
        if not mps_available:
            raise ValueError('MPSを利用できません。対応するMac・PyTorchを確認するか、--device cpuを指定してください')
        return requested
    if re.fullmatch(r'cuda(?::[0-9]+)?', requested):
        index = int(requested.split(':')[1]) if ':' in requested else 0
        if index >= cuda_count:
            raise ValueError('指定したCUDAデバイスを利用できません。GPU・PyTorchを確認してください')
        return requested
    raise ValueError('deviceはauto / cpu / cuda / cuda:N / mpsから指定してください')


def resolve_device(torch, requested):
    mps = getattr(torch.backends, 'mps', None)
    selected = select_device(
        requested,
        cuda_count=torch.cuda.device_count() if torch.cuda.is_available() else 0,
        mps_available=mps is not None and mps.is_available(),
    )
    return torch.device(selected)
