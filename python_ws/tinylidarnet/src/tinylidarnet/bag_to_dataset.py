"""rosbagsでMCAP/SQLite3を学習用NPZに変換。ROSの実行環境は不要。"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from tinylidarnet.alignment import LabelMatcher
from tinylidarnet.bag_reader import BagReader
from tinylidarnet.preprocessing import preprocess_scan, scan_is_fresh
from tinylidarnet.spec import ScanConfig, metadata


def main():
    parser = argparse.ArgumentParser(description='手動走行のLaserScanと指令をNPZに変換します')
    parser.add_argument('--bag', type=Path, required=True, help='ros2 bagで収録したディレクトリ')
    parser.add_argument('--output', type=Path, required=True, help='新規NPZファイル')
    parser.add_argument('--scan-config', type=Path, help='前処理設定JSON、省略時はHokuyo標準設定')
    parser.add_argument('--storage-id', choices=('mcap', 'sqlite3'),
                        help='旧コマンド互換用。形式はrosbagsが自動判定します')
    parser.add_argument('--scan-topic', default='/scan')
    parser.add_argument('--command-topic', default='/drive/applied')
    parser.add_argument('--mode-topic', default='/teleop/mode')
    parser.add_argument('--sync-tolerance', type=float, default=0.1, help='受信時刻の最大差（秒）')
    parser.add_argument('--transition-guard', type=float, default=0.1, help='モード境界の除外時間（秒）')
    parser.add_argument('--scan-max-age', type=float, default=0.2, help='scan生成からbag受信までの上限（秒）')
    args = parser.parse_args()
    for name, value in (('sync-tolerance', args.sync_tolerance), ('scan-max-age', args.scan_max_age)):
        if not math.isfinite(value) or value <= 0:
            parser.error(f'{name}は有限の正の値にしてください')
    if not math.isfinite(args.transition_guard) or args.transition_guard < 0:
        parser.error('transition-guardは有限の非負値にしてください')
    if args.output.suffix != '.npz' or args.output.exists():
        parser.error('outputにはまだ存在しない.npzファイルを指定してください')
    config = ScanConfig(**json.loads(args.scan_config.read_text())) if args.scan_config else ScanConfig()

    import numpy as np
    topics = {
        args.scan_topic: 'sensor_msgs/msg/LaserScan',
        args.command_topic: 'rc_car_interfaces/msg/DriveCommand',
        args.mode_topic: 'std_msgs/msg/String',
    }
    if len(topics) != 3:
        parser.error('scan・command・modeには異なるトピックを指定してください')
    commands, modes = [], []
    session_hash = hashlib.sha256()
    # 1周目は指令・モードだけを保持し、スキャンの生メッセージは保持しない。
    with BagReader(args.bag.resolve()) as reader:
        reader.validate_topics(topics)
        for topic, serialized, stamp in reader.messages(topics):
            session_hash.update(topic.encode() + b'\0' + str(stamp).encode() + b'\0' + serialized)
            if topic == args.command_topic:
                msg = reader.deserialize(serialized, topics[topic])
                commands.append((stamp, float(msg.steering), float(msg.throttle)))
            elif topic == args.mode_topic:
                modes.append((stamp, reader.deserialize(serialized, topics[topic]).data))
    matcher = LabelMatcher(commands, modes, int(args.sync_tolerance * 1e9), int(args.transition_guard * 1e9))

    scans, targets, timestamps = [], [], []
    counts = Counter()
    last_scan_stamp = 0
    with BagReader(args.bag.resolve()) as reader:
        for _, serialized, stamp in reader.messages([args.scan_topic]):
            counts['total_scans'] += 1
            target = matcher.match(stamp)
            if target is None:
                counts['not_manual_or_unsynchronized'] += 1
                continue
            if not all(math.isfinite(x) and -1 <= x <= 1 for x in target):
                counts['invalid_target'] += 1
                continue
            msg = reader.deserialize(serialized, topics[args.scan_topic])
            scan_stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
            if scan_stamp <= last_scan_stamp or not scan_is_fresh(scan_stamp, stamp, args.scan_max_age):
                counts['stale_scan'] += 1
                continue
            last_scan_stamp = scan_stamp
            try:
                scan = preprocess_scan(msg.ranges, msg.angle_min, msg.angle_increment,
                                       msg.range_min, msg.range_max, config)
            except ValueError:
                counts['invalid_scan'] += 1
                continue
            scans.append(scan)
            targets.append(target)
            timestamps.append(stamp)
    counts['accepted'] = len(scans)
    print(json.dumps(dict(counts), indent=2))
    if not scans:
        raise ValueError('学習可能な手動走行データがありません。収録トピック・時刻・設定を確認してください')
    info = metadata(config)
    info.update({
        'session_id': session_hash.hexdigest(), 'source_bag': args.bag.name,
        'topics': list(topics), 'counts': dict(counts),
        'sync_tolerance': args.sync_tolerance, 'transition_guard': args.transition_guard,
        'scan_max_age': args.scan_max_age, 'timestamp_basis': 'bag_receive_time_ns',
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as output:
        np.savez_compressed(output, scans=np.asarray(scans, dtype=np.float32),
                            targets=np.asarray(targets, dtype=np.float32),
                            timestamps_ns=np.asarray(timestamps, dtype=np.int64),
                            metadata=np.asarray(json.dumps(info)))
    print(f'学習データを保存しました: {args.output.resolve()}')


if __name__ == '__main__':
    main()
