# Thembelani MTD app: one image with Python, Tesseract OCR and the app.
FROM python:3.12-slim

# Tesseract reads the engineering and car report pictures.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY mtdapp ./mtdapp

# All saved data (database, uploaded files) lives here. Mount a persistent disk
# or volume on /data, or the history is lost when the container is replaced.
ENV MTD_DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    OMP_THREAD_LIMIT=1 \
    PORT=8000
VOLUME /data
EXPOSE 8000

# One worker process (SQLite, one shared data folder) with threads for parallel
# requests; a long timeout because reading pictures takes ~20 seconds.
CMD gunicorn "mtdapp.app:create_app()" --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 180
