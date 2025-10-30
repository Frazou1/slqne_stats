FROM python:3.11-slim

# --- Optimisations Python ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# --- Timezone ---
ENV TZ=America/Toronto
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    jq \
    ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# --- Dépendances Python ---
RUN pip install --no-cache-dir \
    "requests>=2.31,<3" \
    "beautifulsoup4>=4.12,<5" \
    "lxml>=4.9,<6" \
    "paho-mqtt==1.6.1" \
    "pytz>=2024.1,<2025" \
    "html5lib>=1.1"

# --- Répertoire de travail ---
WORKDIR /app

# --- Copie des fichiers de l’add-on ---
COPY run.sh /run.sh
COPY script.py /script.py
RUN chmod a+x /run.sh

# --- Commande d’exécution ---
CMD ["/run.sh"]
