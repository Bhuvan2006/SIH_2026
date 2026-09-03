FROM python:3.11-slim

# Tesseract is the real OCR engine used for printed prescription text
# (see app/services/ocr_service.py). Installed via apt since it's a
# system binary, not a Python package.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# start.sh fetches the prebuilt database on first boot and runs migrations
# before handing over to uvicorn. See its header for why the database is
# neither in the image nor in git.
RUN chmod +x start.sh

EXPOSE 8000
CMD ["./start.sh"]
