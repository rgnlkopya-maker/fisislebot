import os
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from dotenv import load_dotenv

# Load env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN bulunamadı. .env dosyasına BOT_TOKEN ekle.")

app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# Where files will be stored
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


# ---------------- Commands ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Merhaba! Fiş fotoğrafı veya PDF gönder.\n"
        "Sistem otomatik okuyup Google Sheet'e işleyecek ve linki gönderecek.\n\n"
        "Komutlar:\n"
        "/help - Yardım\n"
        "/sheet - Sheet linki\n"
        "/status - Özet"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Sistemi başlat\n"
        "/help - Yardım ve kullanım\n"
        "/sheet - Sheet linkini gönder\n"
        "/status - Bu ayki fiş ve toplam özet\n\n"
        "Fiş fotoğrafı veya PDF gönderdiğinde otomatik işlenecek."
    )

async def sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sheet linki: (şimdilik test) https://docs.google.com/")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Durum: test modundayız. Bu ay 0 fiş.")


# ---------------- File Handler ----------------
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    user_id = user.id if user else "unknown"

    await msg.reply_text("Fiş alındı. İndiriyorum...")

    file_id = None
    ext = "jpg"

    # Photo
    if msg.photo:
        file_id = msg.photo[-1].file_id
        ext = "jpg"

    # Document (PDF or image)
    elif msg.document:
        file_id = msg.document.file_id
        filename = msg.document.file_name or ""
        if "." in filename:
            ext = filename.split(".")[-1].lower()
        else:
            ext = "bin"

    if not file_id:
        await msg.reply_text("Dosya bulunamadı. Lütfen tekrar gönder.")
        return

    tg_file = await context.bot.get_file(file_id)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = DATA_DIR / f"{user_id}_{ts}.{ext}"

    await tg_file.download_to_drive(custom_path=str(save_path))

    await msg.reply_text(
        f"Dosya indirildi ✅\n"
        f"Kaydedilen dosya: {save_path.name}\n"
        f"data/ klasörüne kaydedildi.\n\n"
        f"(Sonraki adım: OCR + Sheet'e yazma)"
    )


# Register handlers
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("help", help_cmd))
tg_app.add_handler(CommandHandler("sheet", sheet))
tg_app.add_handler(CommandHandler("status", status))
tg_app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_file))


# ---------------- Webhook Endpoint ----------------
@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.get("/")
def root():
    return {"status": "running"}
