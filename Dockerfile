FROM python:3.11-slim

# System deps for Chrome / Selenium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl unzip xvfb \
    fonts-liberation libappindicator3-1 \
    libasound2 libatk-bridge2.0-0 \
    libnspr4 libnss3 lsb-release \
    xdg-utils libxss1 libdbus-glib-1-2 \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome (stable)
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data directories
RUN mkdir -p data/downloads data/logs data/database

CMD ["python", "main.py"]
