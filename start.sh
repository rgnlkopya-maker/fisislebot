#!/usr/bin/env bash
set -e

echo "✅ Starting FISISLE-BOT container..."

# Render sets PORT env var automatically
export PORT="${PORT:-5000}"

# Graceful shutdown
cleanup() {
  echo "🧹 Shutting down..."
  pkill -P $$ || true
  exit 0
}
trap cleanup SIGINT SIGTERM

echo "🌐 Starting web server on port $PORT..."
gunicorn -b 0.0.0.0:$PORT web_runner:app --workers 1 --threads 4 --timeout 120 &
WEB_PID=$!

echo "🤖 Starting Telegram bot polling..."
python bot_polling.py &
BOT_PID=$!

echo "⚙️ Starting worker process..."
python worker_process.py &
WORKER_PID=$!

echo "✅ All processes started."
echo "   web pid=$WEB_PID, bot pid=$BOT_PID, worker pid=$WORKER_PID"

# Wait forever, but exit if any process dies
while true; do
  if ! kill -0 $WEB_PID 2>/dev/null; then
    echo "❌ Web server died."
    exit 1
  fi
  if ! kill -0 $BOT_PID 2>/dev/null; then
    echo "❌ Telegram bot died."
    exit 1
  fi
  if ! kill -0 $WORKER_PID 2>/dev/null; then
    echo "❌ Worker died."
    exit 1
  fi
  sleep 2
done
