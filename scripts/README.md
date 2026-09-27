# 便利スクリプト

## JetsonとノートPCのファイル転送

ノートPCから起動します。起動場所によらず、このリポジトリを基準に保存先を決めます。

```bash
bash scripts/transfer_jetson.sh
```

1. rosbagの取得、または学習済みモデルの送信を選択します。
2. JetsonのIPアドレスを入力します。
3. Jetson側のプロジェクトルートを入力します。初期値は`/home/tamiya/iASL-tamiya-systems`です。
4. 表示された一覧から、コピーする番号を入力します。

番号は`1 3`、`1,3`、`1-3`で複数選択でき、`all`で全件を選択します。空欄で中止できます。選んだものは順に転送されます。ユーザー名は初期値`tamiya`で、変更する場合は`--user ユーザー名`を付けます。

ノートPC側にはPython 3.9以上と`ssh`・`scp`が必要です。Jetson側にはSSHサーバー、Python 3.9以上、metadata.yamlを読むPyYAMLが必要です。Ubuntuでは次のように準備できます。

```bash
# Jetson側で実行
sudo apt install openssh-server python3-yaml
sudo systemctl enable --now ssh
```

SSHの通常のホスト確認・認証を使用します。一度確立した接続は処理中に再利用するので、ファイルごとのパスワード入力を避けられます。補助処理は実行時にSSH経由で送るため、Jetson側にこの転送スクリプトを事前配置する必要はありません。

### 1. Jetsonのrosbagを取得

Jetsonの`プロジェクトルート/record/`以下を探索し、`metadata.yaml`から収録時間・メッセージ数・bagファイル一覧を読み取ります。参照先のファイルがそろった収録を一覧表示します。収録を終了してから転送してください。

選択した収録について、`metadata.yaml`と、その`relative_file_paths`に記載されたファイルをコピーします。分割された複数のMCAP・DB3ファイルもまとめて取得します。無関係なファイルは転送しません。

```text
Jetson:   プロジェクトルート/record/run01/
                  ↓
ノートPC: プロジェクトルート/record/run01/
```

不正なmetadataやファイル欠落がある収録は、理由を表示して一覧から除外します。

### 2. 学習済みモデルをJetsonへ送信

ノートPCの`python_ws/tinylidarnet/outputs/`以下から、`weights.pt`と`metadata.json`がそろったモデルを一覧表示します。

選択したモデルの`weights.pt`・`metadata.json`と、存在する場合は`history.json`を送信します。推論に必要な前処理設定も一緒に移すため、重みだけを送る操作にはしていません。

```text
ノートPC: python_ws/tinylidarnet/outputs/09-11/12-34/
                  ↓
Jetson:   プロジェクトルート/python_ws/tinylidarnet/outputs/09-11/12-34/
```

### 保存先の扱い

既存のディレクトリには上書きせず、重複時は`_02`、`_03`と連番を付けます。転送中は一時ディレクトリを使用し、その収録・モデルの転送が完了してから保存先へ移動します。途中で失敗しても、それ以前に転送が完了したものは残ります。

Jetson側のプロジェクトパスと、bag・モデルの相対パスには英数字・`_`・`-`・`.`・`/`を使用してください。空白や日本語を含むリモートパスは対象外です。

## コントローラーの接続

車載側で実行します。

```bash
bash scripts/connect_controller.sh
```

接続したいコントローラーのMACアドレスを入力すると、ペアリング・接続を行います。
