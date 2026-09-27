#!/bin/bash
# DualShock 4 / DualSenseをBlueZ経由でペアリング・接続します。
set -euo pipefail
export LC_ALL=C

if [[ "${1:-}" == "--help" ]]; then
    echo "使い方: $0"
    echo "接続したいコントローラーのMACアドレスを入力してください。"
    exit 0
fi
if (( $# != 0 )); then
    echo "引数は不要です。使い方は --help を参照してください。" >&2
    exit 1
fi

for command in bluetoothctl timeout; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "$command が見つかりません。Ubuntuで sudo apt install bluez coreutils を実行してください。" >&2
        exit 1
    fi
done

echo "🎮 コントローラーのペアリング・接続"
echo "========================================"
read -r -p "接続したいコントローラーのMACアドレスを入力してください: " CONTROLLER_MAC
if [[ ! "$CONTROLLER_MAC" =~ ^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$ ]]; then
    echo "MACアドレスは AA:BB:CC:DD:EE:FF の形式で入力してください。" >&2
    exit 1
fi

echo
echo "接続先: $CONTROLLER_MAC"

# パイプへの入力がsudoの認証に使われないよう、先に認証します。
SUDO=()
if (( EUID != 0 )); then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "sudo が見つかりません。管理者権限で実行してください。" >&2
        exit 1
    fi
    sudo -v
    SUDO=(sudo -n)
fi

device_info=$("${SUDO[@]}" timeout 5s bluetoothctl info "$CONTROLLER_MAC" 2>/dev/null || true)
already_paired=false
if grep -Eq '^[[:space:]]*Paired: yes[[:space:]]*$' <<< "$device_info"; then
    already_paired=true
    echo "登録済みです。コントローラーのPSボタンを押して電源を入れてください。"
else
    echo "コントローラーの電源を切ってから、ライトが点滅するペアリングモードにしてください。"
    echo "PS4: PS + SHAREを長押し / PS5: PS + クリエイトを長押し"
fi
read -r -p "準備ができたら Enterキーを押してください..." _

echo "接続処理を開始します（約20〜40秒）。"
# agentと探索を同じセッション内に維持します。
# 登録済みの場合はpairを省略し、既存のペアリング情報を利用します。
if ! {
    printf 'power on\n'
    sleep 1
    printf 'agent NoInputNoOutput\n'
    sleep 1
    printf 'default-agent\n'
    sleep 1
    printf 'scan on\n'
    sleep 8
    if [[ "$already_paired" == false ]]; then
        printf 'pair %s\n' "$CONTROLLER_MAC"
        sleep 15
    fi
    printf 'trust %s\n' "$CONTROLLER_MAC"
    sleep 1
    printf 'connect %s\n' "$CONTROLLER_MAC"
    sleep 8
    printf 'scan off\n'
    sleep 1
    printf 'quit\n'
} | "${SUDO[@]}" timeout 55s bluetoothctl; then
    echo "接続処理中にエラーまたはタイムアウトが発生しました。状態を確認します。" >&2
fi

# コマンドの送信完了ではなく、BlueZの現在の状態で成否を判定します。
device_info=$("${SUDO[@]}" timeout 5s bluetoothctl info "$CONTROLLER_MAC" 2>/dev/null || true)
for property in Paired Trusted Connected; do
    if ! grep -Eq "^[[:space:]]*${property}: yes[[:space:]]*$" <<< "$device_info"; then
        echo "接続を確認できませんでした（${property}がyesではありません）。" >&2
        echo "Bluetoothアダプターとコントローラーの状態を確認し、再実行してください。" >&2
        echo "登録情報を削除してやり直す場合: sudo bluetoothctl remove $CONTROLLER_MAC" >&2
        exit 1
    fi
done

echo "✅ $CONTROLLER_MAC のペアリング・信頼設定・接続を確認しました。"
echo "ROS側の認識確認: ros2 run joy joy_enumerate_devices"
