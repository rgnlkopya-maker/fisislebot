FROM python:3.11-slim

# System deps: tesseract, poppler, opencv runtime deps + pillow-heif deps
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-tur \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libheif1 \
    libde265-0 \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache bust: Render eski layer kullanmasın
ARG CACHEBUST=20260110_1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build-time doğrulama: gunicorn gerçekten kuruldu mu?
RUN python -c "import gunicorn; print('gunicorn OK')"

COPY . .

RUN chmod +x start.sh

CMD ["bash", "start.sh"]
