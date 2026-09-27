"""rosbagsによるROS非依存の読み取り。カスタム型もROSビルドなしで登録。"""

from pathlib import Path

DRIVE_COMMAND_TYPE = 'rc_car_interfaces/msg/DriveCommand'
# 型定義を持たない旧形式のbag用。ROS側.msgとの一致は標準ライブラリのテストで確認。
DRIVE_COMMAND_DEFINITION = 'float32 throttle\nfloat32 steering\n'


class BagReader:
    def __init__(self, path):
        self.path = Path(path)
        self.reader = None

    def __enter__(self):
        from rosbags.highlevel import AnyReader
        from rosbags.typesys import Stores, get_typestore, get_types_from_msg

        store = get_typestore(Stores.ROS2_HUMBLE)
        store.register(get_types_from_msg(DRIVE_COMMAND_DEFINITION, DRIVE_COMMAND_TYPE))
        self.reader = AnyReader([self.path], default_typestore=store)
        self.reader.open()
        return self

    def __exit__(self, *args):
        self.reader.close()

    def validate_topics(self, expected):
        for topic, msgtype in expected.items():
            connections = [c for c in self.reader.connections if c.topic == topic]
            if not connections or any(c.msgtype != msgtype for c in connections):
                raise ValueError(f'必要なトピックがないか型が異なります: {topic} ({msgtype})')

    def messages(self, topics):
        connections = [c for c in self.reader.connections if c.topic in topics]
        if not connections:
            return
        for connection, stamp, raw in self.reader.messages(connections=connections):
            yield connection.topic, bytes(raw), stamp

    def deserialize(self, raw, msgtype):
        return self.reader.deserialize(raw, msgtype)
