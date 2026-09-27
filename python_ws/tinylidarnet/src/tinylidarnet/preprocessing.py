"""角度基準の再サンプリングと距離正規化。学習・推論で同一処理を使用。"""

import math

from .spec import ScanConfig


def preprocess_scan(ranges, angle_min, angle_increment, range_min, range_max, config: ScanConfig):
    if len(ranges) < 2:
        raise ValueError('LaserScanの点数が不足しています')
    if not all(math.isfinite(x) for x in (angle_min, angle_increment, range_min, range_max)):
        raise ValueError('LaserScanの角度・距離メタデータが不正です')
    if angle_increment == 0 or not 0 <= range_min < range_max:
        raise ValueError('LaserScanの角度刻み・距離範囲が不正です')
    if abs(angle_increment) * (len(ranges) - 1) > 2 * math.pi + abs(angle_increment):
        raise ValueError('LaserScanの角度範囲が360度を超えています')
    result = []
    finite_count = 0
    for point in range(config.sample_count):
        angle = math.radians(config.angle_min_deg + (
            config.angle_max_deg - config.angle_min_deg) * point / (config.sample_count - 1))
        # [0, 2π]と[-π, π]、負のangle_incrementに対応。
        candidates = [(angle + offset - angle_min) / angle_increment
                      for offset in (-2 * math.pi, 0.0, 2 * math.pi)]
        indices = [round(index) for index in candidates
                   if -0.5 <= index <= len(ranges) - 0.5]
        indices = [index for index in indices if 0 <= index < len(ranges)]
        if not indices:
            raise ValueError('LiDARが設定された入力角度範囲をカバーしていません')
        value = float(ranges[indices[0]])
        if math.isfinite(value) and range_min <= value <= range_max:
            finite_count += 1
        elif value == math.inf:
            value = range_max  # 反射なし：センサーの測距上限として扱う。
        else:
            value = 0.0  # NaN、負の無限大、範囲外：近距離側へ倒す。
        result.append(min(value, config.max_distance) / config.max_distance)
    if finite_count / config.sample_count < config.min_finite_fraction:
        raise ValueError('有限な有効測距点が不足しています')
    return result


def scan_is_fresh(stamp_ns, now_ns, max_age, future_tolerance=0.05):
    return stamp_ns > 0 and -future_tolerance <= (now_ns - stamp_ns) / 1e9 <= max_age
