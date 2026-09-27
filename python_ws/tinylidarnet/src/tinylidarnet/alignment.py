"""bag受信時刻を使った教師値の対応付け（標準ライブラリのみ）。"""

from bisect import bisect_right


def manual_intervals(modes, max_gap_ns):
    """手動モードの継続区間。モード通信の欠落でも区間を分割する。"""
    intervals = []
    start = last = None
    for stamp, mode in sorted(modes):
        if last is not None and (mode != 'manual' or stamp - last > max_gap_ns):
            intervals.append((start, last))
            start = last = None
        if mode == 'manual':
            if start is None:
                start = stamp
            last = stamp
    if start is not None:
        intervals.append((start, last))
    return intervals


class LabelMatcher:
    def __init__(self, commands, modes, max_age_ns=100_000_000, transition_guard_ns=100_000_000):
        if max_age_ns <= 0 or transition_guard_ns < 0:
            raise ValueError('同期許容時間は正、モード境界の除外時間は0以上にしてください')
        self.commands = sorted(commands, key=lambda row: row[0])
        self.times = [row[0] for row in self.commands]
        self.intervals = manual_intervals(modes, max_age_ns)
        self.starts = [row[0] for row in self.intervals]
        self.max_age_ns = max_age_ns
        self.guard = transition_guard_ns

    def match(self, stamp):
        command_index = bisect_right(self.times, stamp) - 1
        interval_index = bisect_right(self.starts, stamp) - 1
        if min(command_index, interval_index) < 0:
            return None
        command_stamp, steering, throttle = self.commands[command_index]
        start, end = self.intervals[interval_index]
        if stamp - command_stamp > self.max_age_ns:
            return None
        # 操作モードと出力が別トピックなので、切り替え境界は教師値に使わない。
        if not start + self.guard <= command_stamp <= stamp <= end - self.guard:
            return None
        return steering, throttle
