FROM python:3.11-slim

# --- Optimisations Python ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# --- Timezone ---
ENV TZ=America/Toronto
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata jq ca-certificates wget curl gnupg unzip xvfb \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# --- Dépendances système pour Google Chrome & Xvfb (Nettoyées pour Debian récent) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    libgbm1 \
    libgtk-3-0 \
    libxi6 \
    xauth \
    && rm -rf /var/lib/apt/lists/*

# --- Installation de Google Chrome Stable (Indispensable pour le mode UC) ---
RUN curl -sS -o - https://google.com | apt-key add - \
    && echo "deb [arch=amd64] http://google.com stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# --- Configuration de l'affichage virtuel Xvfb ---
ENV DISPLAY=:99

# --- Dépendances Python ---
RUN pip install --no-cache-dir \
    "seleniumbase>=4.20.0" \
    "beautifulsoup4>=4.12,<5" \
    "paho-mqtt==1.6.1" \
    "requests>=2.31,<3"

# --- Répertoire de travail ---
WORKDIR /app

# --- Copie des fichiers ---
COPY run.sh /run.sh
COPY script.py /app/script.py
RUN chmod a+x /run.sh

# --- Commande par défaut ---
CMD ["/run.sh"]
