# iASL Tamiya Systems

JetRacerのようなRCカーをROS 2で動かすための基盤です。まずDualShock 4で手動運転し、今後は自動運転ノードからの指令を切り替えて使います。

車載側の暫定の対象環境は **Ubuntu 22.04 / ROS 2 Humble / Python 3.10** です。実機構成に合わせて環境を確定してください。

学習・オフラインのbag処理はLinux／macOSで行えます。[Pythonワークスペースのセットアップ](python_ws/README.md)から、[TinyLidarNetの学習手順](python_ws/tinylidarnet/README.md)へ進んでください。

## セットアップ

### 1. ROS 2関連パッケージの導入

ROS 2を導入済みのUbuntuで実行します。最初に使用するディストリビューションの環境を読み込みます。以下はHumbleの例で、読み込み後の`ROS_DISTRO`は`humble`になります。

```bash
source /opt/ros/humble/setup.bash
sudo apt update
sudo apt install git python3-setuptools python3-traitlets python3-colcon-common-extensions python3-rosdep
sudo apt install ros-${ROS_DISTRO}-joy
sudo apt install ros-${ROS_DISTRO}-rosbag2-storage-mcap # rosbagのMCAP形式での記録用
```

### 2. NVIDIA JetRacerの導入（実機用）

車載側で、本家の[JetRacer導入手順](https://github.com/NVIDIA-AI-IOT/jetracer/blob/master/docs/software_setup.md#step-5---install-python-packages)に沿ってPythonパッケージを導入します。模擬モードだけを使う場合は、この手順を省略できます。

ROSパッケージではないため、このプロジェクトの`ros2_ws/src`の外に配置します。以下ではホームディレクトリに取得します。

```bash
cd ~
git clone https://github.com/NVIDIA-AI-IOT/jetracer.git
cd jetracer
sudo python3 setup.py install
```

`jetracer`、`adafruit-circuitpython-servokit`、`traitlets`、Adafruitのボード依存環境が必要です。ROSノードが使うPythonからインポートできる状態にしてください。JetRacerのインストールではServoKitの依存関係も導入されますが、ボード側のI2C設定・アクセス権限は別途必要です。

ハードウェアを初期化せずに、インポートを確認できます。

```bash
python3 -c 'from jetracer.nvidia_racecar import NvidiaRacecar; print("JetRacer import OK")'
```

### 3. Hokuyo urg_node2の導入（LiDAR用）

[公式urg_node2](https://github.com/Hokuyo-aut/urg_node2)を、このリポジトリとは別の`~/drivers_ws`でビルド・インストールします。このプロジェクトにはsubmoduleとして登録せず、事前導入したドライバーとして利用します。手動運転だけの場合は省略できます。

車載側で、プロジェクトの環境をまだ読み込んでいない新しいターミナルから実行します。`rosdep`が未初期化の場合だけ、先に`sudo rosdep init`を一度実行してください。

```bash
source /opt/ros/humble/setup.bash
sudo apt install build-essential
mkdir -p ~/drivers_ws/src
cd ~/drivers_ws/src
git clone --recursive https://github.com/Hokuyo-aut/urg_node2.git
cd ~/drivers_ws
rosdep update
rosdep install --from-paths src --ignore-src -r -y --rosdistro ${ROS_DISTRO}
```

`--recursive`はドライバー自身が使用するライブラリを取得するためのものです。取得先はすべて外部の`drivers_ws`内です。

ドライバー本体はそのままビルドします。接続設定は、このプロジェクト側のYAMLと`lidar.launch.py`で管理するため、外部のソースやlaunchを編集する必要はありません。

```bash
cd ~/drivers_ws
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
source install/setup.bash
ros2 pkg prefix urg_node2
```

以後はインストール済みのドライバーを利用できます。IPや接続方式の変更に、ドライバーの再ビルドは不要です。起動方法は[LiDARの起動と確認](#lidarの起動と確認)を参照してください。

### 4. ワークスペースのビルド

`rosdep`が未初期化の場合だけ、`sudo rosdep init`を一度実行します。その後、**このプロジェクトのリポジトリルートへ戻ってから**実行します。

```bash
source /opt/ros/humble/setup.bash
# LiDARを使う場合：事前ビルドしたドライバーの環境を読み込む
source ~/drivers_ws/install/setup.bash
rosdep update
cd ros2_ws
rosdep install --from-paths src --ignore-src -r -y --rosdistro ${ROS_DISTRO}
colcon build --symlink-install
source install/setup.bash
```

別ターミナルでも、ROS 2 → `~/drivers_ws/install/setup.bash` → このプロジェクトの`ros2_ws/install/setup.bash`の順で読み込んでください。LiDARを導入していない場合は`drivers_ws`の読み込みを省略します。起動手順は[まず模擬モードで確認](#まず模擬モードで確認)を参照してください。

### 5. コントローラーのBluetooth接続

[scripts/connect_controller.sh](scripts/connect_controller.sh)で、PS4 DualShock 4 / PS5 DualSenseのペアリングと接続ができます。USB接続の場合は不要です。

```bash
sudo apt install bluez coreutils
bash scripts/connect_controller.sh
```

起動すると、接続したいコントローラーのMACアドレスを求められます。`AA:BB:CC:DD:EE:FF`の形式で、実際に使うコントローラーのアドレスを入力してください。

初回は、電源を切った状態からPS4では **PS + SHARE**、PS5では **PS + クリエイト** を長押しして、ライトが点滅するペアリングモードにします。登録済みの場合はPSボタンで電源を入れてください。スクリプトは登録済みの情報を利用し、最後にペアリング・信頼設定・接続の状態を確認します。実行時には管理者権限の認証が必要です。

MACアドレスが分からない場合は、ペアリングモードにして`bluetoothctl`を起動し、`scan on`で表示される機器名とアドレスを確認してください。確認後は`scan off`、`quit`で終了します。

## 構成

```text
DualShock 4
    │
    ▼
joy/game_controller_node ── /joy ──────────┐
                                         ▼
TinyLidarNetなど ──── /autonomy/command ── teleop_manager
                                         │ /drive/command
                                         ▼
                                  jetracer_node
                                         │
                               NVIDIA NvidiaRacecar
                                         │
                                 Adafruit ServoKit
                                         │ I2C
                                      PCA9685
                                         │ PWM
                               操舵サーボ / 駆動ESC
```

PCA9685はPWM信号を生成します。駆動モーターを直接駆動するものではなく、この実装ではJetRacerと同様、ニュートラルを持つESCと操舵サーボを想定します。別のモータードライバーを使う場合は、出力部分の変更が必要です。

```text
ros2_ws/src/
├── rc_car_interfaces/   # 共通メッセージ DriveCommand
├── teleop_manager/      # 手動・自動の選択、入力タイムアウト
├── jetracer_driver/     # jetracer_node、車体側タイムアウト、模擬出力
├── rc_car_bringup/      # 車体とLiDARのlaunch・設定YAML
└── tinylidarnet_ros/    # TinyLidarNet推論ノード、MCAP→NPZ変換
python_ws/
└── tinylidarnet/        # ROS非依存の前処理・モデル・学習・推論API
tests/                  # ROS・実機不要の標準ライブラリによるテスト
```

`joy`はapt、`urg_node2`は外部の`~/drivers_ws`で導入します。車体の通常起動は3ノードで、TinyLidarNetによる自動運転時には推論ノードを追加します。LiDARのドライバーは別途起動します。

## LiDARの起動と確認

車載側の専用ターミナルで起動し、収録・推論中は動かしておきます。

```bash
source /opt/ros/humble/setup.bash
source ~/drivers_ws/install/setup.bash
# このプロジェクトのリポジトリルートで実行
source ros2_ws/install/setup.bash
ros2 launch rc_car_bringup lidar.launch.py connection:=ether ip_address:=192.168.0.10
```

IPは実際のLiDARのアドレスへ変更してください。起動するドライバー本体は外部の`drivers_ws`にインストールしたものです。このlaunchは自動でライフサイクルをActiveへ遷移させます。`publish_multiecho: false`で`/scan`（`sensor_msgs/msg/LaserScan`）を配信します。

接続設定は次のYAMLで変更できます。

| 接続方式 | 設定ファイル | 主な設定 |
|---|---|---|
| Ethernet（既定） | [urg_ether.yaml](ros2_ws/src/rc_car_bringup/config/urg_ether.yaml) | `ip_address`、`ip_port` |
| USB | [urg_serial.yaml](ros2_ws/src/rc_car_bringup/config/urg_serial.yaml) | `serial_port`、`serial_baud` |

USBで起動する場合：

```bash
ros2 launch rc_car_bringup lidar.launch.py connection:=serial serial_port:=/dev/ttyACM0
```

独自のYAMLを指定する場合：

```bash
ros2 launch rc_car_bringup lidar.launch.py connection:=ether config_file:=/absolute/path/to/urg.yaml
```

YAMLは`urg_node2.ros__parameters`配下に設定を書きます。`ip_address`・`serial_port`をlaunch引数で指定した場合はYAMLより優先され、省略時はYAMLの値を使います。`connection:=serial`ではUSB接続を選ぶため`ip_address`を空にします。配信先は`scan_topic:=/scan`で変更できます。

同梱YAMLは±135度・`cluster: 1`・`skip: 0`で、0.25度刻みの機種では1081点を想定します。**30.0 mはTinyLidarNetの前処理上限**で、ドライバーの測距性能を変更する値ではありません。

設定変更後はLiDARノードを再起動してください。`config_file`で編集したYAMLを直接指定すれば再ビルドは不要です。同梱YAMLを既定で使う場合は、変更をインストール先へ反映するためこのプロジェクトの`ros2_ws`で再ビルドしてください。

Ethernetでは車載PCの有線インターフェースをLiDARと通信できるネットワークに設定します。USBではデバイスへのアクセス権限を確認してください。Ubuntuで`dialout`グループが必要な場合は`sudo usermod -aG dialout "$USER"`を実行し、ログインし直します。

同じ環境を読み込んだ別ターミナルで確認します。

```bash
ros2 lifecycle get /urg_node2
ros2 topic info /scan
ros2 topic echo /scan --once --no-arr
ros2 topic hz /scan
```

状態が`active`で、`ranges`が1081点、角度が約−2.356〜+2.356 rad、角度刻みが約0.0043633 radになっていることを確認します。`--no-arr`では配列の内容を省略して長さを表示します。`hz`はCtrl+Cで終了します。

LiDARの0度を車体前方、正の角度を左方向に合わせてください。`frame_id`の変更だけでは測距データの方向は変わりません。配信が確認できたら、[TinyLidarNetの収録・学習・推論](python_ws/tinylidarnet/README.md)へ進みます。

## 操作

以下は初期設定での操作です。ボタンやスティックの割り当ては、[rc_car.yaml](ros2_ws/src/rc_car_bringup/config/rc_car.yaml)の`teleop_manager.ros__parameters`で変更できます。具体例は[設定](#設定)を参照してください。

| 操作・状態 | 出力 |
|---|---|
| 三角だけを押し続ける | 手動運転 |
| 四角だけを押し続ける | 自動運転指令を採用 |
| 両方押す / 両方離す | スロットル0、操舵0 |
| 左スティック上下 | 前進・後退のスロットル |
| 左スティック左右 | 操舵 |
| Joyが0.3秒以上届かない | 手動・自動とも停止指令 |
| 自動運転指令が0.3秒以上届かない | 自動モードの出力を停止指令へ |
| 車体側で指令が0.3秒以上届かない | 車体側で停止指令 |

モードは押している間だけ有効です。自動モードへの切り替え時は、切り替え後に新しく受信した自動運転指令を待ちます。自動運転中も四角の押下とJoyの継続受信が必要です。

スロットル上限は初期値`0.25`です。手動入力はこの値でスケーリングし、自動入力はこの値で上限を設けます。車体側にも独立した上限があります。これらは速度制御ではなく、実際の走行速度との関係は車体依存です。

## まず模擬モードで確認

DualShock 4をUSBまたはBluetoothで接続し、認識を確認します。

```bash
ros2 run joy joy_enumerate_devices
ros2 launch rc_car_bringup bringup.launch.py
```

**デフォルトは模擬モードです。I2CやPWMにはアクセスしません。** 模擬モードでもDualShock 4を読んで、切り替えと車体側の指令処理まで確認できます。物理シミュレーターではありません。

別ターミナルで、必要なトピックを確認します。

```bash
ros2 topic echo /joy
ros2 topic echo /teleop/mode
ros2 topic echo /drive/applied
```

各`echo`は実行し続けるため、別々のターミナルで起動するか、Ctrl+Cで切り替えます。三角を押しながらスティックを動かし、離すと出力がゼロに戻ることを確認してください。`/drive/applied`はソフトウェアが適用した正規化指令であり、実測の速度・PWM・舵角ではありません。

自動切り替えは、**模擬モードでのみ**次のダミー指令を流して確認できます。

```bash
ros2 topic pub --rate 20 /autonomy/command rc_car_interfaces/msg/DriveCommand \
  '{throttle: 0.15, steering: 0.2}'
```

四角を押している間だけ採用されます。指令の配信を止めると、四角を押し続けていても約0.3秒後に出力がゼロになります。三角への切り替え、同時押し、コントローラー切断も確認してください。

## 実機接続

冒頭の[セットアップ](#セットアップ)でJetRacerの導入とインポート確認を済ませてください。

実機起動前に、車輪を浮かせて、次を確認します。

1. PCA9685のI2C接続・アドレス・アクセス権限、サーボとESCの電源・GND。
2. 操舵とESCのチャンネルが設定と一致していること。初期値は操舵`0`、ESC`1`。
3. ESCのアーミングとニュートラル位置。`throttle=0`がニュートラルになること。
4. 操舵の中央・方向・可動範囲。`steering_offset`と`steering_gain`を調整すること。
5. 低い出力での前後方向と、ボタン解放・切断・終了時のニュートラル復帰。

模擬モードのlaunchとダミー指令を終了してから、実機モードを明示して起動します。

```bash
ros2 launch rc_car_bringup bringup.launch.py use_mock_hardware:=false
```

本家クラスの`steering`と`throttle`へ正規化値を渡し、本家のServoKit経由でPCA9685へ出力します。PWMパルス幅を直接指定するインターフェースではありません。初期化・終了時には、同じ値の代入でも確実にニュートラル書き込みを試みるよう、ESC出力にも明示的にゼロを書き込みます。

## 設定

[rc_car.yaml](ros2_ws/src/rc_car_bringup/config/rc_car.yaml)でボタン・軸番号、タイムアウト、出力上限、ハードウェアの校正値を変更できます。操作の割り当ては、次の項目を編集します（初期設定の抜粋）。

```yaml
teleop_manager:
  ros__parameters:
    manual_button: 3          # 手動モード：三角
    auto_button: 2            # 自動モード：四角
    steering_axis: 0          # 操舵：左スティック左右
    throttle_axis: 1          # スロットル：左スティック上下
    steering_inverted: false # trueで操舵入力の方向を反転
    throttle_inverted: false # trueでスロットル入力の方向を反転
```

たとえば、右スティック上下をスロットルに使う場合は`throttle_axis: 3`へ変更します。手動を四角、自動を三角に入れ替える場合は`manual_button: 2`、`auto_button: 3`にします。手動と自動には異なるボタン番号を指定してください。配置を変更しても、押している間だけ有効・両方押すと停止という動作は同じです。

別ファイルを使う場合は絶対パスで指定します。

```bash
ros2 launch rc_car_bringup bringup.launch.py config_file:=/absolute/path/to/rc_car.yaml
```

`teleop_manager`と`jetracer_node`の設定は起動時に確定し、実行中の変更は受け付けません。変更後は再起動してください。ワークスペース内のYAMLを編集した場合、インストール側へ反映するため再ビルドしてください。

`game_controller_node`の標準マッピングでは、三角は`buttons[3]`、四角は`buttons[2]`、左スティックは`axes[0]`と`axes[1]`です。ROSの軸は左・上が正です。実機の`/joy`で確認し、必要なら`steering_inverted`・`throttle_inverted`で反転できます。物理出力方向は本家クラスのゲインでも校正できます。

複数のコントローラーがある場合は、`joy_node.ros__parameters`の`device_name`または`device_id`を指定してください。`autorepeat_rate: 20.0`と`sticky_buttons: false`は、押し続け操作とタイムアウト検出のため維持します。

## JetsonとノートPCのデータ転送

ノートPCで`bash scripts/transfer_jetson.sh`を起動し、JetsonのIPとプロジェクトルートを入力します。

- Jetsonの`record/`をmetadata.yamlから一覧化し、選択したrosbagをノートPCの`record/`へ取得します。
- ノートPCの`python_ws/tinylidarnet/outputs/`からモデルを選択し、重みとmetadata.jsonをJetsonへ送信します。

複数選択に対応しています。準備と操作方法は[scripts/README.md](scripts/README.md)を参照してください。

## TinyLidarNetの学習と推論

Hokuyoの **1081点・視野−135〜135度・距離上限30.0 m** を標準設定にしています。学習用パッケージは`python_ws/tinylidarnet`、ROS 2側は`tinylidarnet_ros`です。

手動走行をMCAPへ収録し、NPZへ変換して学習します。学習済みモデルをROS 2ノードで読み込み、`/scan`から`/autonomy/command`へ操舵・スロットルを配信します。四角ボタンによる切り替えは既存の`teleop_manager`が担当します。

uv・仮想環境・requirements.txtによる導入は[PythonワークスペースのREADME](python_ws/README.md)、収録・変換・学習・推論は[TinyLidarNetのREADME](python_ws/tinylidarnet/README.md)にまとめています。学習済み重みは含まれていません。

## 自動運転ノードとの接続仕様

| トピック | 型 | 用途 |
|---|---|---|
| `/scan` | `sensor_msgs/msg/LaserScan` | 外部導入した`urg_node2`からの測距データ |
| `/joy` | `sensor_msgs/msg/Joy` | コントローラー入力 |
| `/autonomy/command` | `rc_car_interfaces/msg/DriveCommand` | TinyLidarNetなどの自動運転ノードからの入力 |
| `/drive/command` | 同上 | `teleop_manager`が選択した車体向け指令 |
| `/drive/applied` | 同上 | 車体側で検証・制限した出力要求の確認 |
| `/teleop/mode` | `std_msgs/msg/String` | 実際の出力状態：`manual` / `auto` / `stopped` |

`DriveCommand`のフィールドは以下の2つです。

```text
float32 throttle   # [-1, 1]、正が前進
float32 steering   # [-1, 1]、正が左
```

単位はm/sやradではありません。将来の経路追従側が速度・舵角を出す場合は、車体校正に基づく変換ノードを追加します。自動運転ノードは`/autonomy/command`へ20Hz程度で継続配信してください。`/drive/command`への直接配信は手動・自動の選択を迂回するため、通常は`teleop_manager`だけを配信元とします。

入力購読のQoSはBest Effort・Volatile・深さ1で、Reliable配信元にも対応します。車体向け出力と購読はReliable・Volatile・深さ1です。タイムアウトはローカル受信時刻の単調増加時計で判定し、監視タイマーもROSシミュレーション時刻の停止に依存しません。メッセージに生成時刻は持たないため、上流で生成された時点からの古さは検出しません。

## 停止動作の範囲

このプロジェクトの「停止」は、スロットルをゼロ、操舵を中央へ戻す要求です。車輪の即時停止や能動的なブレーキを保証するものではありません。NaN・無限大・範囲外の指令や不正なJoy入力でもゼロへ戻します。タイムアウトによる停止は、通常は設定時間と最大1周期分の遅延で処理しますが、OSやI2Cの遅延を含む厳密な時間保証はありません。

通常終了時にはニュートラル出力を試みます。起動した3ノードのいずれかが終了すると、launch全体も終了します。ただし、車体ノードの強制終了、OS停止、I2C故障ではPythonから停止出力できず、PCA9685が直前のPWMを出し続ける可能性があります。実車では独立した電源遮断やハードウェアのフェイルセーフが必要です。

## 開発時の検証

リポジトリのルートから、Python標準ライブラリだけで実行できます。

```bash
python3 -m unittest discover -s tests -v
```

モード切り替え、ボタン解放・同時押し、通信タイムアウト、古い自動指令の破棄、入力異常、出力制限、本家クラスへの設定引き渡しとニュートラル書き込みを確認します。ROSノードの起動・DDS通信・実際のI2C出力はこのテストの対象外です。ROS側のビルド・起動と実機検証は車載環境で実施します。

パッケージのmaintainerは仮の値です。ライセンス表記は公開ライセンス未決定のため`Proprietary`としてあり、公開・配布方針が決まり次第更新してください。

## 参照

- [Hokuyo urg_node2：導入・設定・起動手順](https://github.com/Hokuyo-aut/urg_node2)
- [ROS joy：game_controller_nodeのマッピングと設定](https://github.com/ros-drivers/joystick_drivers/blob/ros2/joy/README.md)
- [ROS joy：軸の符号変換](https://github.com/ros-drivers/joystick_drivers/blob/ros2/joy/src/game_controller.cpp)
- [NVIDIA JetRacer：NvidiaRacecar実装](https://github.com/NVIDIA-AI-IOT/jetracer/blob/master/jetracer/nvidia_racecar.py)
- [NVIDIA JetRacer：導入手順](https://github.com/NVIDIA-AI-IOT/jetracer/blob/master/docs/software_setup.md)
- [rosbag2：MCAPストレージプラグイン](https://github.com/ros2/rosbag2/blob/humble/rosbag2_storage_mcap/README.md)
