#!/usr/bin/env bash
set -e

# Bot (Telegram downloader) background
python bot_polling.py &

# Worker foreground (OCR + parse)
python worker_process.py
