# backend/Dockerfile
FROM python:3.11-slim

# Install system dependencies including LibreOffice and Tesseract OCR
RUN apt-get update && apt-get install -y \
    libreoffice \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
