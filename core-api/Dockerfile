FROM python:3.12-slim

# Щоб apt не ставив зайве і не висів з питаннями
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) ffmpeg (і тільки він), без рекомендованого мотлоху
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# 2) Пакети Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 3) Код застосунку
COPY . .

# 4) Gunicorn
ENV HOST=0.0.0.0 \
    PORT=8000
CMD ["gunicorn","-c","gunicorn.conf.py","app:app"]
