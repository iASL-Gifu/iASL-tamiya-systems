#!/bin/bash
# ノートPCから実行するJetsonとのデータ転送メニュー。
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/transfer_jetson.py" "$@"
