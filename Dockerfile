# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 QT_QPA_PLATFORM=offscreen
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgl1 libglib2.0-0 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && (pip uninstall -y opencv-python opencv-contrib-python || true) \
    && pip install opencv-python-headless
COPY . .
CMD ["sleep", "infinity"]

FROM base AS sim
ENV ROBOT_BACKEND=mock

FROM base AS robot
ENV ROBOT_BACKEND=urscript

FROM base AS full
ENV ROBOT_BACKEND=mock
