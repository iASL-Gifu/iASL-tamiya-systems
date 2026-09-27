# Pythonワークスペース

[プロジェクト全体へ戻る](../README.md) / [TinyLidarNetの収録・変換・学習・推論](tinylidarnet/README.md)

ROS 2を起動せずにデータ処理と学習を行うワークスペースです。LinuxでもmacOSでも、Jetsonから取得したrosbagをNPZへ変換し、TinyLidarNetを学習できます。実車のデータ収録・ROSノードの起動は車載側で行います。

## uvのインストール（Linux / macOS）

両OS共通の[公式インストーラー](https://docs.astral.sh/uv/getting-started/installation/)で導入します。

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

ターミナルを開き直し、`uv --version`で確認します。macOSでHomebrewを使っている場合は、代わりに`brew install uv`でも導入できます。

## 仮想環境とrequirements.txtによるセットアップ

リポジトリルートから実行します。オフライン変換・学習用にはPython 3.11を用意します。

```bash
cd python_ws
uv python install 3.11
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cd ..
```

仮想環境は`python_ws/.venv`です。以降はリポジトリルートでコマンドを実行します。別ターミナルで再開する場合は、`source python_ws/.venv/bin/activate`で有効化します。

[requirements.txt](requirements.txt)はTinyLidarNetをeditableモードで導入し、`pyproject.toml`の`torch`・`bags`追加依存もまとめてインストールします。バージョン範囲を一か所で管理するため、requirements.txtには依存パッケージを重複して列挙しません。

| パッケージ | 用途 |
|---|---|
| NumPy | LiDAR配列、NPZデータセット |
| PyTorch | モデルの学習・推論 |
| tqdm | 学習進捗の表示 |
| rosbags | ROSなしでMCAP・SQLite3形式のrosbagを読む |

LinuxのNVIDIA GPU環境では、通常の導入コマンドの代わりに次を使い、CUDAドライバーに合うPyTorchの配布先をuvに選ばせることもできます。[uvのPyTorchガイド](https://docs.astral.sh/uv/guides/integration/pytorch/)

```bash
# python_ws内、仮想環境を有効にした状態で実行
uv pip install --torch-backend=auto -r requirements.txt
```

Jetsonの推論環境はJetPackとROSが使うPythonに合わせて別途準備します。この学習用Python 3.11環境をそのままROS Humbleの実行環境には使いません。

## TinyLidarNetの学習までに行うこと

1. **手動走行を収録**：JetsonでLiDAR、車体へ出した操舵・スロットル、手動／自動モードをrosbagへ記録します。
2. **ノートPCへ取得**：[転送スクリプト](../scripts/README.md)で収録を選び、`record/`へコピーします。
3. **教師データを作成**：`rosbags`でメッセージを読み、手動運転中のLiDARと直前の操作指令を時刻で対応付けます。通信欠落やモード切り替え付近は除外します。
4. **LiDARを前処理**：1081点、−135〜135度にそろえ、距離を30.0 mでクリップして0〜1に正規化します。
5. **別走行を検証用に分割**：同じ収録の近接フレームが学習・検証に混ざることを避けます。
6. **模倣学習**：LiDARから人間の操舵・スロットルを予測し、教師値との差を小さくします。検証損失が最も小さい重みを日時別の`outputs`へ保存します。
7. **Jetsonへ転送**：重みと前処理設定を戻し、ROS 2ノードで推論します。

人間の運転例を学ぶ教師あり学習です。具体的なコマンドは[TinyLidarNetのREADME](tinylidarnet/README.md)へ進んでください。

## CPU・CUDA・MPSの選択

`tinylidarnet-train --device auto`は、利用可能な **CUDA → MPS → CPU** の順に選びます。`auto`が初期値です。

| 指定 | 主な用途 |
|---|---|
| `--device cpu` | GPUを使わない学習 |
| `--device cuda` / `cuda:0` | NVIDIA GPU |
| `--device mps` | 対応するMacのMetal GPU（Apple Siliconなど） |

MPSはMac・OS・PyTorchの組み合わせに依存します。利用可否は次で確認できます。[PyTorchのMPS説明](https://docs.pytorch.org/docs/2.8/notes/mps.html)

```bash
python -c 'import torch; print("CUDA:", torch.cuda.is_available()); print("MPS:", torch.backends.mps.is_available())'
```

利用できないGPUの明示指定はエラーにします。MPSの未対応演算などに当たる場合は`--device cpu`へ切り替えられます。重みはCPU上のテンソルとして保存するため、MPSで学習したモデルもJetsonへ移して読み込めます。実機によるMPS学習はまだ検証していません。

## ROSなしでのrosbag処理

`rosbags`はROSのソフトウェアに依存せず、MCAPとSQLite3を扱えます。`tinylidarnet-bag-to-dataset`は、`rclpy`・`rosbag2_py`・ROS環境の読み込みを必要としません。[rosbagsの説明](https://ternaris.gitlab.io/rosbags/)、[対応形式](https://ternaris.gitlab.io/rosbags/topics/rosbag2.html)

`metadata.yaml`と参照先ファイルがそろった収録ディレクトリを入力します。独自の`rc_car_interfaces/msg/DriveCommand`も型登録するため、ノートPC側でROSメッセージをビルドする必要はありません。
