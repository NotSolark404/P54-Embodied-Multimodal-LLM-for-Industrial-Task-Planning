FROM python:3.11-slim

# Set environment variables to silence Ultralytics and Qt warnings in headless mode
ENV YOLO_CONFIG_DIR=/tmp/Ultralytics \
    QT_QPA_PLATFORM=offscreen \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    cmake \
    curl \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir opencv-python-headless --upgrade

COPY . .

CMD ["python", "main.py", "--interactive"]