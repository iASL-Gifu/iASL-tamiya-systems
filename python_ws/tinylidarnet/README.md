# TinyLidarNet：収録・学習・ROS 2推論

[Pythonワークスペース・uvセットアップへ戻る](../README.md) / [プロジェクト全体へ戻る](../../README.md)

Hokuyoの **1081点・視野−135〜135度・距離上限30.0 m** を標準とする、LiDARから操舵・スロットルを学習するパッケージです。

[TinyLidarNetの公開実装](https://github.com/CSL-KU/TinyLidarNet/blob/main/train.py)の5層Conv1D・4層全結合の構成をPyTorchで実装しています。このプロジェクトでは入力距離を0〜1に正規化し、出力を`[steering, throttle]`の正規化指令に合わせています。本家のTensorFlow/TFLiteモデルとは重み・入出力仕様が異なり、そのまま読み込めません。論文の結果の再現を保証する実装ではありません。

## 全体の流れ

```text
Hokuyo → /scan ─────────────────────────────┐
                                          │ MCAP収録
手動運転 → /drive/applied + /teleop/mode ────┘
    ↓ tinylidarnet-bag-to-dataset（rosbags、ROS不要）
NPZ（前処理済みLiDAR、操舵・スロットル）
    ↓ tinylidarnet-train（ROS不要）
weights.pt + metadata.json
    ↓ tinylidarnet_node（ROS 2側）
/scan → 推論 → /autonomy/command → teleop_manager → jetracer_node
```

学習コードは`python_ws/tinylidarnet`、ROS 2アダプターは`ros2_ws/src/tinylidarnet_ros`に分けています。前処理とモデルはPythonパッケージを共有します。

## 1. セットアップ

uvのLinux／macOSへの導入方法は[PythonワークスペースのREADME](../README.md)を参照してください。uvを導入後、リポジトリルートから仮想環境と依存関係を用意します。

```bash
cd python_ws
uv python install 3.11
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cd ..
```

これ以降はリポジトリルートで実行します。ノートPC側はROS不要で、bag変換から学習までこの仮想環境を使えます。次回は`source python_ws/.venv/bin/activate`で再開できます。

変換だけを行う場合は、requirements.txtの代わりに`uv pip install -e './tinylidarnet[bags]'`を`python_ws`内で実行するとPyTorchを省略できます。

車載側では、JetPackなどの環境に対応したPyTorchを先に導入し、**ROSノードを起動するPython環境**に共有パッケージを入れます。学習用の仮想環境とは別でも構いません。MCAP→NPZ変換だけならPyTorchは不要です。

```bash
source /opt/ros/humble/setup.bash
source ~/drivers_ws/install/setup.bash
python3 -m pip install -e ./python_ws/tinylidarnet
cd ros2_ws
rosdep install --from-paths src --ignore-src -r -y --rosdistro ${ROS_DISTRO}
colcon build --symlink-install
source install/setup.bash
cd ..
```

`tinylidarnet`とPyTorchはROSパッケージではないため、`rosdep`や`colcon build`だけでは導入されません。以降の`ros2`コマンドを使うターミナルでも、ROS 2とワークスペースの環境を読み込んでください。

## 2. 手動走行を収録

Hokuyoの`urg_node2`は、[メインREADMEのセットアップ](../../README.md#セットアップ)に従い、外部の`~/drivers_ws`で事前にビルド・インストールします。[LiDARの起動と確認](../../README.md#lidarの起動と確認)を済ませ、`sensor_msgs/msg/LaserScan`を`/scan`へ配信してください。ドライバーは収録・推論中も起動しておきます。LiDARの0度が車体前方、正の角度が左方向となるようにし、学習と運用で取り付け位置・方向をそろえてください。TFによる座標変換は行いません。

車体の配線・校正を済ませ、既存のlaunchを起動します。三角ボタンを押しながら手動走行してください。

```bash
ros2 launch rc_car_bringup bringup.launch.py use_mock_hardware:=false
```

別ターミナルで収録します。

```bash
mkdir -p record
ros2 bag record -s mcap -o record/run01 /scan /drive/applied /teleop/mode
```

Ctrl+Cで終了します。検証用に、別の走行を`run02`へ収録してください。`/drive/applied`は実測速度ではなく、車体側で制限された操舵・スロットル要求です。モード情報を使い、自動運転中・停止モード中のデータは学習から除外します。

## 3. MCAPをNPZへ変換

Jetsonでの収録後、[転送スクリプト](../../scripts/README.md)でノートPCの`record/`へコピーしてください。以降はLinux／macOSの仮想環境で実行でき、ROS 2は不要です。`--bag`には`metadata.yaml`とMCAP／SQLite3ファイルがそろったディレクトリを指定します。

```bash
tinylidarnet-bag-to-dataset \
  --bag record/run01 --output data/datasets/run01.npz \
  --scan-config python_ws/tinylidarnet/config/scan.json

tinylidarnet-bag-to-dataset \
  --bag record/run02 --output data/datasets/run02.npz \
  --scan-config python_ws/tinylidarnet/config/scan.json
```

トピック名は`--scan-topic`・`--command-topic`・`--mode-topic`で変更できます。保存形式は自動判定し、独自のDriveCommand型も登録します。既存のNPZは上書きしません。従来の`ros2 run tinylidarnet_ros bag_to_dataset`も同じ処理を呼びますが、その環境には`tinylidarnet[bags]`の導入が必要です。

現在の指令メッセージには生成時刻がないため、対応付けにはbag受信時刻を使います。各スキャンの直前の指令を選び、時刻差が`--sync-tolerance`（初期値0.1秒）を超えたものは除外します。モード通信の欠落と、手動モードの開始・終了付近（`--transition-guard`、初期値0.1秒）も除外します。完全なセンサー同期や人間の操作遅れの補正ではありません。

スキャン生成時刻とbag受信時刻の差も確認し、初期値で0.2秒を超えて古いもの、不正な時刻・入力は除外します。同じROS時刻系で収録してください。変換時に採用数と除外理由ごとの件数を表示します。

| NPZのキー | 内容 |
|---|---|
| `scans` | `float32 [N, 1081]`、前処理済み距離、0〜1 |
| `targets` | `float32 [N, 2]`、`[steering, throttle]`、各−1〜1 |
| `timestamps_ns` | `int64 [N]`、スキャンのbag受信時刻 |
| `metadata` | JSON文字列、前処理・教師値の順序・収録セッションIDなど |

変換・学習はデータをメモリに保持します。長時間の収録は複数の走行単位に分けてください。

## 4. 学習

NPZを学習環境へコピーすれば、学習時にROSは不要です。

```bash
tinylidarnet-train \
  --train data/datasets/run01.npz \
  --val data/datasets/run02.npz \
  --epochs 20 --batch-size 64 --learning-rate 0.00005 \
  --device auto
```

`auto`ではCUDA → MPS → CPUの順に利用可能なデバイスを選びます。MacのGPUを明示する場合は`--device mps`、NVIDIA GPUは`--device cuda`、CPUは`--device cpu`を指定します。MPSを使うには対応するMac・OS・PyTorchが必要です。利用できないGPUを指定するとエラーを表示します。

`--train`・`--val`は複数ファイルを指定できます。近接フレームの混入を避けるため、フレームのランダム分割はせず、別の収録セッションを明示します。同じセッションが学習用と検証用に含まれる場合や、前処理設定が異なる場合はエラーになります。最終評価には、さらに別の未使用走行を確保してください。

Huber損失とAdamで学習します。`tqdm`でエポック・学習バッチ・検証バッチの進捗を表示します。各エポックの学習・検証損失、操舵・スロットルの平均絶対誤差を記録し、検証損失が最も小さい重みを保存します。

`--output`は省略できます。実行開始時のローカル日時を使い、パッケージ直下の`outputs/MM-DD/HH-MM/`へ自動保存します。たとえば9月11日12時34分に開始すると、次の構成になります。

```text
python_ws/tinylidarnet/outputs/09-11/12-34/
├── weights.pt      # 最良の検証損失を得たPyTorch state_dict
├── metadata.json   # モデル仕様・前処理・教師値の順序・学習条件
└── history.json    # エポックごとの損失と検証誤差
```

同じ保存先が存在する場合は`12-34_02`、`12-34_03`と連番を付け、既存の重みを上書きしません。日時別保存の親フォルダーは`--output-root`、出力先全体は`--output`で任意に変更できます。既定の保存場所は、このREADMEのeditableインストールを前提としています。

推論には`weights.pt`と`metadata.json`の両方が必要です。学習を中断した未完成の出力は、推論用モデルとして扱いません。Jetsonとのデータ転送は[転送スクリプトの使い方](../../scripts/README.md)を参照してください。

## 5. ROS 2で推論

学習成果物を車載側へコピーし、まず車体側を模擬モードで起動します。LiDARのドライバーも起動しておきます。

```bash
ros2 launch rc_car_bringup bringup.launch.py
```

別ターミナルで、学習成果物の絶対パスを指定して推論を起動します。

```bash
ros2 launch tinylidarnet_ros inference.launch.py \
  model_dir:=/absolute/path/to/python_ws/tinylidarnet/outputs/09-11/12-34
```

`/autonomy/command`と`/drive/applied`を確認し、四角を押している間だけ推論指令が選択されることを確認します。実機へ切り替えるときは、車体launchの`use_mock_hardware:=false`を指定します。ダミーの自動運転指令は終了し、配信元が重複しないようにしてください。

推論設定は[ROS側のtinylidarnet.yaml](../../ros2_ws/src/tinylidarnet_ros/config/tinylidarnet.yaml)です。別の設定やスキャン名を使う場合は、以下のように指定できます。

```bash
ros2 launch tinylidarnet_ros inference.launch.py \
  model_dir:=/absolute/path/to/model \
  config_file:=/absolute/path/to/tinylidarnet.yaml \
  scan_topic:=/scan
```

| 設定 | 初期値 | 内容 |
|---|---|---|
| `device` | `cpu` | PyTorchの推論先。環境に応じて`cuda`など |
| `torch_threads` | `1` | PyTorchのCPUスレッド数 |
| `publish_rate` | `20.0` | 指令配信Hz。新しいスキャンのみ推論 |
| `scan_timeout` | `0.2` | 受信途絶・生成時刻・推論後の鮮度上限（秒） |
| `expected_frame_id` | 空文字 | 空なら照合なし。指定時は異なるframeを拒否 |
| `max_throttle` | `0.25` | 推論ノードでのスロットル上限 |
| `max_steering` | `1.0` | 推論ノードでの操舵上限 |

スキャンがない・古い・時刻が逆行した・入力が不正・推論に失敗した場合はゼロ指令を出します。ノード停止・長時間停止時は、既存の`teleop_manager`の自動指令タイムアウトが働きます。時刻は単調増加を前提とし、時計を巻き戻した場合はノードを再起動してください。これは衝突検知や経路の安全性を保証する機能ではありません。

## 前処理の仕様

[config/scan.json](config/scan.json)が標準設定です。

```json
{
  "sample_count": 1081,
  "angle_min_deg": -135.0,
  "angle_max_deg": 135.0,
  "max_distance": 30.0,
  "min_finite_fraction": 0.1
}
```

角度の小さい側から大きい側へ並べ、各目標角度に最も近い測距点を使います。Hokuyoの1081点・0.25度刻みではそのままの点順を保ちます。負の角度刻みや360度スキャンにも対応しますが、必要な角度範囲をカバーしない入力は拒否します。

距離は30.0 mでクリップして30.0で割ります。正の無限大はセンサーの`range_max`、NaN・負の無限大・センサー範囲外は0として扱います。有限かつセンサー範囲内の点が10%未満なら、スキャン全体を拒否します。

前処理設定はNPZからモデルの`metadata.json`へ引き継ぎ、推論時に読み込みます。設定を変えた場合はデータ変換と学習をやり直してください。

## 検証範囲

リポジトリルートから、標準ライブラリだけで前処理・時刻判定・教師値の対応付けを検証できます。

```bash
python3 -m unittest discover -s tests -v
```

PyTorchの学習・推論、ROS 2ビルド、実MCAP変換、実機走行は未検証です。学習済み重み・収録データは含まれていません。

## 参照

- [TinyLidarNet論文](https://arxiv.org/abs/2410.07447)
- [公開実装のモデル構成と学習](https://github.com/CSL-KU/TinyLidarNet/blob/main/train.py)
- [rosbags：AnyReader](https://ternaris.gitlab.io/rosbags/topics/highlevel.html)
- [PyTorch：MPS](https://docs.pytorch.org/docs/2.8/notes/mps.html)
