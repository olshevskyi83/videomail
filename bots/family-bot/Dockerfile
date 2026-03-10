FROM python:3.12-slim

# ffmpeg для перекодування у mp4
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./

# важливо: спершу оновлюємо pip, тоді інсталимо зависимости
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "family_bot.py"]
