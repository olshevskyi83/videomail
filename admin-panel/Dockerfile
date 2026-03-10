FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV CORE_API_URL="http://core-api:8000" \
    ADMIN_BEARER_TOKEN="changeme" \
    ADMIN_PASSWORD="changeme_admin" \
    FLASK_SECRET="devsecret"

EXPOSE 80
CMD ["python","app.py"]
