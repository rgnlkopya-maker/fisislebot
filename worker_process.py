from parser_receipt import parse_receipt_fields

import json
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone
import subprocess

import cv2
import numpy as np
from PIL import Image
import pytesseract

# PDF OCR için (PDF -> image)
from pdf2image import convert_from_path

print("WORKER_VERSION=2026-01-14-001")



# =========================
#  AYARLAR / CONFIG
# =========================
DATA_DIR = Path("data")

INBOX_SUBDIR = "inbox"
PROCESSED_SUBDIR = "processed"
FAILED_SUBDIR = "failed"
OUTPUT_SUBDIR = "output"

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}

# OCR ayarları
TESS_LANG = "tur"                # Türkçe OCR (gerekirse: "tur+eng")
TESS_CONFIG = "--oem 3 --psm 6"  # Fiş için iyi başlangıç

SCAN_INTERVAL_SECONDS = 2


# =========================
#  HELPER FONKSİYONLAR
# =========================
def now_str():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_subdirs(user_dir: Path):
    (user_dir / INBOX_SUBDIR).mkdir(parents=True, exist_ok=True)
    (user_dir / PROCESSED_SUBDIR).mkdir(parents=True, exist_ok=True)
    (user_dir / FAILED_SUBDIR).mkdir(parents=True, exist_ok=True)
    (user_dir / OUTPUT_SUBDIR).mkdir(parents=True, exist_ok=True)


def preprocess_image_for_ocr(img_bgr: np.ndarray) -> np.ndarray:
    """
    Fiş OCR kalitesini artırmak için basit ama etkili pre-processing:
    - grayscale
    - bilateral filter (gürültü azaltma)
    - adaptive threshold (kontrast arttırma)
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    thr = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        35, 11
    )
    return thr


def ocr_image(img: Image.Image) -> str:
    """
    PIL Image -> OCR text
    """
    img_rgb = np.array(img.convert("RGB"))
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

    processed = preprocess_image_for_ocr(img_bgr)
    processed_pil = Image.fromarray(processed)

    text = pytesseract.image_to_string(
        processed_pil,
        lang=TESS_LANG,
        config=TESS_CONFIG
    )
    return text


def extract_text_from_pdf_pdftotext(pdf_path: Path) -> str:
    """
    PDF içindeki selectable text'i pdftotext ile çıkarır.
    Linux/Docker ortamında poppler-utils kuruluysa çalışır.
    Windows'ta PATH'te pdftotext varsa çalışır.
    """
    cmd = shutil.which("pdftotext")
    if not cmd:
        return ""

    try:
        tmp_txt = pdf_path.with_suffix(".pdftotext.tmp.txt")
        subprocess.run(
            [cmd, str(pdf_path), str(tmp_txt)],
            check=False
        )

        if tmp_txt.exists():
            txt = tmp_txt.read_text(encoding="utf-8", errors="ignore")
            tmp_txt.unlink(missing_ok=True)
            return txt.strip()

    except Exception:
        return ""

    return ""


def ocr_pdf(pdf_path: Path) -> str:
    """
    PDF -> page images -> OCR -> birleşik text
    """
    images = convert_from_path(
        str(pdf_path),
        dpi=300
    )

    all_text = []
    for i, img in enumerate(images, start=1):
        page_text = ocr_image(img)
        all_text.append(f"\n--- PAGE {i} ---\n{page_text}")

    return "\n".join(all_text)



def write_json(output_path: Path, payload: dict):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def move_file(src: Path, dest_dir: Path) -> Path:
    dest_path = dest_dir / src.name
    return Path(shutil.move(str(src), str(dest_path)))


# =========================
#  DOSYA İŞLEME
# =========================
def process_file(file_path: Path, chat_id: str):
    """
    Tek dosyayı OCR yapar, JSON yazar, dosyayı processed/failed'a taşır.
    """
    user_dir = DATA_DIR / chat_id
    ensure_subdirs(user_dir)

    processed_dir = user_dir / PROCESSED_SUBDIR
    failed_dir = user_dir / FAILED_SUBDIR
    output_dir = user_dir / OUTPUT_SUBDIR

    ext = file_path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return

    started_at = now_str()
    processed_at_iso = datetime.now(timezone.utc).isoformat()


    try:
        # 1) OCR/TEXT üret
        if ext in {".jpg", ".jpeg", ".png"}:
            img = Image.open(file_path)
            text = ocr_image(img)

        elif ext == ".pdf":
            # PDF Text Layer (pdftotext)
            pdf_text = extract_text_from_pdf_pdftotext(file_path)

            # OCR sadece PDF_TEXT yeterli değilse çalışsın
            ocr_text = ""
            if not pdf_text or len(pdf_text) < 200:
                ocr_text = ocr_pdf(file_path)

            # Combine
            parts = []
            if pdf_text:
                parts.append("=== PDF_TEXT ===\n" + pdf_text)
            if ocr_text:
                parts.append("=== OCR_TEXT ===\n" + ocr_text)

            text = "\n\n".join(parts).strip()

        else:
            raise ValueError(f"Unsupported extension: {ext}")

        # 2) Payload oluştur
        payload = {
            "chat_id": chat_id,
            "source_file": str(file_path),
            "processed_at": started_at,                 # eski format kalsın (geriye uyum)
            "processed_at_iso": processed_at_iso,       # yeni: UTC ISO
            "ocr_engine": "tesseract",
            "lang": TESS_LANG,
            "config": TESS_CONFIG,
            "text": text,
        }



        # 3) Parser çalıştır
        result = parse_receipt_fields(text, filename=file_path.name)

        # Geriye uyumluluk: parser eski format dönerse normalize et
        if isinstance(result, dict) and "fields" in result:
            payload["parsed"] = result.get("fields", {})
            payload["confidence"] = result.get("confidence", {})
            payload["warnings"] = result.get("warnings", [])
            payload["fallback"] = result.get("fallback", {})
        else:
            # eski parser çıktısı: direkt parsed'a koy
            payload["parsed"] = result
            payload["confidence"] = {}
            payload["warnings"] = []
            payload["fallback"] = {"used": False, "reason": "legacy_parser_output"}


        # 4) JSON yaz
        json_name = f"{file_path.stem}.json"
        output_path = output_dir / json_name
        write_json(output_path, payload)

        # 5) Dosyayı processed'a taşı
        moved_path = move_file(file_path, processed_dir)

        print(f"[OK] OCR complete: {file_path.name}")
        print(f"     JSON: {output_path}")
        print(f"     Moved to: {moved_path}")

    except Exception as e:
        moved_path = None
        try:
            moved_path = move_file(file_path, failed_dir)
        except Exception:
            pass

        print(f"[FAIL] OCR failed: {file_path.name}")
        print(f"       Error: {e}")
        if moved_path:
            print(f"       Moved to: {moved_path}")


# =========================
#  INBOX SCAN
# =========================
def scan_inbox_and_process():
    """
    data/*/inbox/ altında yeni dosya var mı bakar, sırayla işler.
    """
    if not DATA_DIR.exists():
        return

    for chat_dir in DATA_DIR.iterdir():
        if not chat_dir.is_dir():
            continue

        chat_id = chat_dir.name
        inbox_dir = chat_dir / INBOX_SUBDIR
        if not inbox_dir.exists():
            continue

        files = sorted(
            [p for p in inbox_dir.iterdir() if p.is_file()],
            key=lambda p: p.stat().st_mtime
        )

        for file_path in files:
            process_file(file_path, chat_id)


# =========================
#  MAIN LOOP
# =========================
def main():
    print("✅ Worker started: inbox taranıyor...")
    print("📌 Klasör: data/<chat_id>/inbox/")
    print("📌 Çıktı: data/<chat_id>/output/*.json")
    print("⛔ Durdurmak için: CTRL + C")

    while True:
        scan_inbox_and_process()
        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
