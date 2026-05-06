FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV TESSERACT_CMD=/usr/bin/tesseract
ENV PYTHONUNBUFFERED=1

CMD python -c "import app; print('IMPORT_APP_OK')" && gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180 --capture-output --access-logfile - --error-logfile - --log-level debug
