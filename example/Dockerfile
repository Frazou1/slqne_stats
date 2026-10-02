ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Toronto \
    DISPLAY=:99

# Installation des dépendances système (Alpine Linux)
RUN apk add --no-cache \
    python3 \
    py3-pip \
    jq \
    bash \
    curl \
    tzdata \
    xvfb \
    chromium \
    chromium-chromedriver

# Installation des paquets Python
RUN pip install --no-cache-dir --break-system-packages \
    "seleniumbase>=4.20.0" \
    "beautifulsoup4>=4.12,<5" \
    "paho-mqtt==1.6.1" \
    "requests>=2.31,<3"

# Répertoire de travail et copie du projet
WORKDIR /app
COPY run.sh /run.sh
COPY script.py /app/script.py

RUN chmod a+x /run.sh

CMD ["/run.sh"]
