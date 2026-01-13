import os
import csv
import requests
from pathlib import Path
from datetime import datetime
import logging
logging.basicConfig(level=logging.INFO)


from dotenv import load_dotenv

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
except Exception as e:
    print("❌ python-telegram-bot import failed:", e)
    raise

from PIL import Image

# HEIC -> JPG dönüşümü opsiyonel
try:
    import pillow_heif
    HEIC_ENABLED = True
except Exception:
    pillow_heif = None
    HEIC_ENABLED = False

# =========================
# ENV / CONFIG
# =========================
if os.path.exists(".env"):
    load_dotenv()


# Tek standart token key: TELEGRAM_BOT_TOKEN
BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
)

if not BOT_TOKEN:
    raise ValueError(
        "Telegram token bulunamadı. "
        "Render için: TELEGRAM_BOT_TOKEN env var olarak ekle. "
        "Local için: .env içine TELEGRAM_BOT_TOKEN=123:ABC... yaz."
    )

# Webhook silme isteğe bağlı (Render'da gereksiz)
DELETE_WEBHOOK = os.getenv("DELETE_WEBHOOK", "0") == "1"

# Ana klasörler
DATA_DIR = Path("data")
LOG_DIR = Path("logs")
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

DOWNLOAD_LOG_FILE = LOG_DIR / "downloads.csv"

# Kabul edilen uzantılar
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".heic"}

# Maks dosya boyutu (MB)
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# HEIC dönüştürdükten sonra orijinal HEIC kalsın mı?
KEEP_ORIGINAL_HEIC = True


# =========================
# HELPERS
# =========================
def delete_webhook(token: str):
    url = f"https://api.telegram.org/bot{token}/deleteWebhook"
    r = requests.get(url, timeout=10)
    print("deleteWebhook response:", r.status_code, r.text)


def now_str():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_user_dir(chat_id: int) -> Path:
    """
    data/<chat_id>/inbox klasörünü oluşturur.
    """
    inbox_dir = DATA_DIR / str(chat_id) / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    return inbox_dir


def make_safe_filename(original_name: str, message_id: int) -> str:
    """
    Benzersiz ve sıralanabilir dosya adı üret:
    <timestamp>__<message_id>__<original_name>
    """
    ts = now_str()
    original_name = original_name or "file.bin"
    return f"{ts}__{message_id}__{original_name}"


def write_download_log(row: dict):
    """
    logs/downloads.csv dosyasına indirilen her dosya için log yaz.
    """
    file_exists = DOWNLOAD_LOG_FILE.exists()
    with open(DOWNLOAD_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def convert_heic_to_jpg(heic_path: Path) -> Path:
    """
    HEIC dosyasını JPG'ye çevirir.
    pillow_heif yoksa çalışmaz.
    """
    if not HEIC_ENABLED:
        raise RuntimeError("pillow_heif yüklü değil, HEIC dönüşümü yapılamaz.")

    pillow_heif.register_heif_opener()

    img = Image.open(heic_path).convert("RGB")

    jpg_path = heic_path.with_suffix(".jpg")
    if jpg_path.exists():
        jpg_path = heic_path.parent / f"{heic_path.stem}_{now_str()}.jpg"

    img.save(jpg_path, "JPEG", quality=95)
    return jpg_path


# =========================
# TELEGRAM HANDLERS
# =========================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Merhaba! Bana fiş/fotoğraf gönder, indirip kayıt altına alayım.\n"
        "Not: Şu an polling ile çalışıyorum."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Telegram PHOTO olarak gelen fotoğraflar.
    """
    if not update.message.photo:
        return

    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    user_dir = ensure_user_dir(chat_id)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    filename = make_safe_filename("photo.jpg", message_id)
    save_path = user_dir / filename

    await file.download_to_drive(custom_path=str(save_path))

    user = update.effective_user
    log_row = {
        "timestamp": now_str(),
        "chat_id": chat_id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "message_id": message_id,
        "file_type": "photo",
        "original_name": "photo.jpg",
        "saved_path": str(save_path),
        "converted_to": "",
    }
    write_download_log(log_row)

    await update.message.reply_text(f"Foto indirildi ✅\nKaydedildi: {save_path}")
    print(f"[OK] Photo saved to: {save_path}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Telegram DOCUMENT olarak gelen dosyalar (PDF/JPG/PNG/HEIC vb.).
    """
    doc = update.message.document
    if not doc:
        return

    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    user_dir = ensure_user_dir(chat_id)

    # Boyut kontrolü
    if doc.file_size and doc.file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text(
            f"Dosya çok büyük ({doc.file_size/1024/1024:.2f} MB). "
            f"Maksimum {MAX_FILE_SIZE_MB} MB kabul ediyorum."
        )
        return

    file = await context.bot.get_file(doc.file_id)

    original_name = doc.file_name or "document.bin"
    ext = Path(original_name).suffix.lower()

    # Uzantı kontrolü
    if ext not in ALLOWED_EXTENSIONS:
        await update.message.reply_text(
            "Bu dosya türünü kabul etmiyorum. Lütfen PDF veya JPG/PNG/HEIC gönder."
        )
        return

    filename = make_safe_filename(original_name, message_id)
    save_path = user_dir / filename

    await file.download_to_drive(custom_path=str(save_path))

    converted_to = ""

    # HEIC ise otomatik JPG'ye dönüştür
    if save_path.suffix.lower() == ".heic":
        if not HEIC_ENABLED:
            await update.message.reply_text(
                f"HEIC dosyası indirildi ✅\nKaydedildi: {save_path}\n"
                f"⚠️ HEIC dönüşümü web ortamında aktif değil (pillow_heif yok)."
            )
            print("[WARN] HEIC received but pillow_heif not installed.")
        else:
            try:
                jpg_path = convert_heic_to_jpg(save_path)
                converted_to = str(jpg_path)

                await update.message.reply_text(
                    f"HEIC dosyası indirildi ✅\nKaydedildi: {save_path}\n"
                    f"JPG'ye dönüştürüldü ✅\nKaydedildi: {jpg_path}"
                )
                print(f"[OK] HEIC saved to: {save_path}")
                print(f"[OK] Converted to JPG: {jpg_path}")

                if not KEEP_ORIGINAL_HEIC:
                    save_path.unlink(missing_ok=True)
                    print("[INFO] Original HEIC deleted.")

            except Exception as e:
                await update.message.reply_text(
                    f"Dosya indirildi ✅\nKaydedildi: {save_path}\n"
                    f"⚠️ HEIC dönüştürme hatası: {e}"
                )
                print(f"[ERROR] HEIC conversion failed: {e}")

    else:
        await update.message.reply_text(f"Dosya indirildi ✅\nKaydedildi: {save_path}")
        print(f"[OK] Document saved to: {save_path}")

    # Log satırı
    user = update.effective_user
    log_row = {
        "timestamp": now_str(),
        "chat_id": chat_id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "message_id": message_id,
        "file_type": "document",
        "original_name": original_name,
        "saved_path": str(save_path),
        "converted_to": converted_to,
    }
    write_download_log(log_row)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id if update.effective_chat else None
    text = update.message.text if update.message else None
    logging.info("TG TEXT chat_id=%s text=%s", chat_id, text)


    await update.message.reply_text(
        "Bana fiş/fotoğraf (photo) veya dosya (document) gönderirsen indirip kaydederim."
    )


# =========================
# MAIN
# =========================
def main():
    if DELETE_WEBHOOK:
        delete_webhook(BOT_TOKEN)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Bot polling ile başlıyor...")
    print("👉 Dosyalar: data/<chat_id>/inbox/ içine kaydedilecek")
    print("👉 Log: logs/downloads.csv")
    print(f"👉 HEIC -> JPG dönüşüm: {'aktif' if HEIC_ENABLED else 'kapalı'} (KEEP_ORIGINAL_HEIC={KEEP_ORIGINAL_HEIC})")
    print("⛔ Durdurmak için: CTRL + C")

    app.run_polling()


if __name__ == "__main__":
    main()
