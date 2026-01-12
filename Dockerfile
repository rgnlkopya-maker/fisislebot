FROM python:3.11-slim

# Logların anlık akması için
ENV PYTHONUNBUFFERED=1

# Sistem bağımlılıkları (OCR + PDF text extraction + pillow-heif + opencv runtime)
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

# Render cache kırmak için (her sorun olursa değer artır)
ARG CACHEBUST=20260112_2

# Requirements önce kopyalanır ki Docker layer cache doğru çalışsın
COPY requirements.txt .

# pip'i güncelle (wheel çözümlemeleri daha stabil olur)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# ✅ Web server için kritik paketleri kesin kur (port açma garantisi)
RUN pip install --no-cache-dir gunicorn==21.2.0 flask==3.0.2

# ✅ Sonra diğer tüm bağımlılıkları kur
RUN pip install --no-cache-dir -r requirements.txt


# ✅ Doğrulama: Flask ve Gunicorn gerçekten kuruldu mu?
RUN python -c "import flask; import gunicorn; print('flask+gunicorn OK')"
RUN pip freeze | grep -E "flask|gunicorn"

# Uygulama kodunu kopyala
COPY . .

# start.sh çalıştırılabilir olmalı
RUN chmod +x start.sh

# Container başlangıcı
CMD ["bash", "start.sh"]
