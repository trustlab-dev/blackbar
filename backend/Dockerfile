# backend/Dockerfile
FROM python:3.11-slim

# Install system dependencies including LibreOffice and Tesseract OCR.
# `upgrade` first: the base image is cut periodically, so without it every
# Debian security fix published since the last base cut ships unpatched.
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    libreoffice \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Refresh the base image's own site-packages (wheel, jaraco.context ship
# outdated with known CVEs) before installing app dependencies.
RUN pip install --no-cache-dir -U pip setuptools wheel "jaraco.context>=6.1" \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
