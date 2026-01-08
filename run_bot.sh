#!/usr/bin/env bash
set -e

# Bu script, botu doğru klasörde ve doğru venv ile başlatır.

PROJECT_DIR="/c/Users/oguzh/OneDrive/Masaüstü/fisisle-bot"

cd "$PROJECT_DIR"

# venv aktif et
source .venv/Scripts/activate

# Bilgi çıktıları
echo "✅ Project dir: $(pwd)"
echo "✅ Python: $(python --version)"
echo "✅ Venv: $VIRTUAL_ENV"
echo "✅ Starting bot_polling.py ..."

# Botu çalıştır
python bot_polling.py
