FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && pip install -r /app/requirements.txt

# Создаём пользователя
RUN useradd -m appuser

# Копируем проект
COPY . /app

# ВАЖНО: создаём папку для статики и выдаём права
RUN mkdir -p /app/staticfiles && chown -R appuser:appuser /app

USER appuser
