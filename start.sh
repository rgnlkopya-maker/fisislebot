#!/usr/bin/env bash

echo "✅ Starting FISISLE-BOT container..."

export PORT="${PORT:-5000}"

cleanup() {
  echo "🧹 Shutting down..."

  # pkill yok: child pid'leri tek tek kapat
  if [ -n "${BOT_PID:-}" ]; then kill "$BOT_PID" 2>/dev/null || true; fi
  if [ -n "${WORKER_PID:-}" ]; then kill "$WORKER_PID" 2>/dev/null || true; fi
  if [ -n "${WEB_PID:-}" ]; then kill "$WEB_PID" 2>/dev/null || true; fi

  exit 0
}

trap cleanup SIGINT SIGTERM

echo "🌐 Starting web server on port $PORT..."
python -m gunicorn -b 0.0.0.0:$PORT web_runner:app --workers 1 --threads 4 --timeout 120 &
WEB_PID=$!

# Bot ve worker crash edebilir, web server kapanmamalı (Render port için şart)
echo "🤖 Starting Telegram bot polling..."
python bot_polling.py &
BOT_PID=$!

echo "⚙️ Starting worker process..."
python worker_process.py &
WORKER_PID=$!

echo "✅ All processes started."
echo "   web pid=$WEB_PID, bot pid=$BOT_PID, worker pid=$WORKER_PID"

# Render için kritik: web server ayakta kalsın.
# Bot/worker ölürse logla ama container'ı düşürme.
while true; do
  if ! kill -0 $WEB_PID 2>/dev/null; then
    echo "❌ Web server died. Exiting container so Render can restart."
    exit 1
  fi

  if ! kill -0 $BOT_PID 2>/dev/null; then
    echo "⚠️ Telegram bot died. (Container will stay up; fix bot logs.)"
    # botu tekrar başlatmayı istersen:
    python bot_polling.py &
    BOT_PID=$!
    echo "🔁 Telegram bot restarted with pid=$BOT_PID"
  fi

  if ! kill -0 $WORKER_PID 2>/dev/null; then
    echo "⚠️ Worker died. (Container will stay up; fix worker logs.)"
    python worker_process.py &
    WORKER_PID=$!
    echo "🔁 Worker restarted with pid=$WORKER_PID"
  fi

  sleep 2
done
