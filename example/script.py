#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SLQNE – Scraper Spordle automatisé
----------------------------------
Version : 3.2 (Novembre 2025)

Fonctions :
 - Récupère le classement, les stats joueurs, le dernier et le prochain match
 - Extrait les logos des équipes
 - Publie sur MQTT
 - Gestion des timeouts et redémarrage auto
 - Garde un seul driver Selenium ouvert pendant tout le cycle
 - Lecture dynamique des équipes via EQUIPES_JSON
"""

import os
import re
import json
import time
import random
import paho.mqtt.publish as publish
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# ===============================================================
# ⚙️ CONFIGURATION
# ===============================================================
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "7200"))

# --- Lecture dynamique des équipes via variable JSON ---
try:
    equipes_json = os.getenv("EQUIPES_JSON", "")
    if equipes_json.strip():
        data = json.loads(equipes_json)
        EQUIPES = {e["name"]: e["url"] for e in data}
        print(f"[INFO] {len(EQUIPES)} équipes chargées depuis configuration.")
    else:
        EQUIPES = {}
        print("[WARN] Aucune équipe définie via EQUIPES_JSON.")
except Exception as e:
    print(f"[ERROR] Lecture EQUIPES_JSON: {e}")
    EQUIPES = {}
# ===============================================================


# ===============================================================
# 📡 MQTT
# ===============================================================
def publish_sensor(sensor, payload):
    """Publie un sensor MQTT"""
    try:
        topic = f"homeassistant/sensor/{sensor}/state"
        publish.single(
            topic,
            json.dumps(payload, ensure_ascii=False),
            hostname=MQTT_HOST,
            port=MQTT_PORT,
            auth={'username': MQTT_USER, 'password': MQTT_PASS} if MQTT_USER else None,
        )
        print(f"[MQTT] Sensor publié: {sensor}")
    except Exception as e:
        print(f"[ERROR] MQTT publish échoué: {e}")


# ===============================================================
# 🌐 SELENIUM
# ===============================================================
def create_driver():
    """Initialise le navigateur headless (une seule instance par cycle)"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver


def safe_get(driver, url, retries=3):
    """Ouvre une page avec retries si 504 ou timeout"""
    for i in range(retries):
        try:
            driver.get(url)
            time.sleep(random.uniform(2, 4))
            html = driver.page_source
            if "504 Gateway" in html or "Time-out" in html:
                print(f"[WARN] 504 détecté ({i+1}/{retries}) → nouvelle tentative...")
                time.sleep(5)
                continue
            return html
        except Exception as e:
            print(f"[ERROR] Chargement échoué ({i+1}/{retries}): {e}")
            time.sleep(5)
    return ""


def scroll_page(driver):
    """Scroll progressif jusqu'à la fin du contenu (lazy load complet)"""
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count += 1
        print(f"[DEBUG] Scroll {scroll_count}: hauteur={new_height}")
        if new_height == last_height:
            break
        last_height = new_height


# ===============================================================
# 🧩 PARSING HTML
# ===============================================================
def parse_logos_from_standings(html):
    """Extrait les logos et noms d'équipes du classement"""
    soup = BeautifulSoup(html, "html.parser")
    logos = {}
    for row in soup.select("tr"):
        team = row.select_one("td:nth-child(2)")
        logo = row.select_one("img")
        if team and logo and team.text.strip():
            logos[team.text.strip()] = logo.get("src")
    print(f"[DEBUG] {len(logos)} logos d'équipes extraits")
    return logos


def parse_games_from_schedule(html):
    """Analyse les matchs depuis la page HTML"""
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    cards = soup.find_all(["div", "article"], attrs={"data-testid": re.compile("game-card|GameCard", re.I)})
    if not cards:
        cards = soup.find_all("div", class_=re.compile("(GameCard|match-card|card)", re.I))

    for card in cards:
        try:
            date_tag = card.find("div", string=re.compile(r"\w+ \d{1,2}"))
            teams = [t.get_text(strip=True) for t in card.find_all("div", class_=re.compile("team-name|teamName"))]
            scores = [s.get_text(strip=True) for s in card.find_all("div", class_=re.compile("score|final-score"))]
            arena_tag = card.find("div", string=re.compile("QC|Québec|St-", re.I))
            final = "Final" in card.get_text() or "FINAL" in card.get_text()
            if date_tag and teams:
                matches.append({
                    "date": date_tag.text.strip(),
                    "teams": teams,
                    "scores": scores,
                    "arena": arena_tag.text.strip() if arena_tag else "",
                    "final": final
                })
        except Exception:
            continue

    print(f"[DEBUG] Total {len(matches)} matchs détectés au total sur la page.")
    return matches


def find_team_game(matches, team_name, future=False):
    """Trouve le dernier (ou prochain) match d'une équipe"""
    norm = re.sub(r"[^a-z0-9]", "", team_name.lower())
    team_matches = [m for m in matches if norm in "".join(re.sub(r"[^a-z0-9]", "", x.lower()) for x in m["teams"])]

    if not team_matches:
        print(f"[INFO] Aucun match trouvé pour {team_name}")
        return None

    if future:
        for m in team_matches:
            if not m["final"]:
                print(f"[DEBUG] Prochain match trouvé: {m['teams']}")
                return m
        return None
    else:
        finals = [m for m in team_matches if m["final"]]
        if finals:
            print(f"[DEBUG] Dernier match trouvé: {finals[-1]['teams']}")
            return finals[-1]
        print(f"[DEBUG] Aucun match final trouvé, dernier match brut: {team_matches[-1]['teams']}")
        return team_matches[-1]


# ===============================================================
# 🏒 PROCESSUS PAR ÉQUIPE
# ===============================================================
def handle_team(driver, name, url):
    """Traite une équipe complète avec un seul driver ouvert"""
    print(f"[INFO] --- Traitement catégorie {name} ---")

    # 1️⃣ Classement + logos
    standings_html = safe_get(driver, f"{url}?tab=standings")
    if standings_html:
        logos = parse_logos_from_standings(standings_html)
        publish_sensor(f"slqne_{slugify(name)}_logos_equipes", logos)

    # 2️⃣ Calendrier (même driver)
    schedule_url = f"{url}?tab=schedule"
    html = safe_get(driver, schedule_url)
    scroll_page(driver)
    matches = parse_games_from_schedule(driver.page_source or html)

    # 3️⃣ Dernier match
    last_game = find_team_game(matches, name, future=False)
    if last_game:
        publish_sensor(f"slqne_{slugify(name)}_dernier_match", last_game)

    # 4️⃣ Prochain match
    next_game = find_team_game(matches, name, future=True)
    if next_game:
        publish_sensor(f"slqne_{slugify(name)}_prochain_match", next_game)


def slugify(text):
    """Simplifie un nom pour usage MQTT"""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# ===============================================================
# 🚀 BOUCLE PRINCIPALE
# ===============================================================
def main_loop():
    """Boucle infinie avec protection timeout et relance"""
    print("[INFO] Attente 30s avant démarrage (MQTT warmup)...")
    time.sleep(30)

    while True:
        print("[INFO] --------------------------------------------------------")
        print(f"[INFO] Exécution du script Python SLQNE… ({datetime.now().isoformat()})")

        driver = None
        try:
            driver = create_driver()
            if not EQUIPES:
                print("[ERROR] Aucune équipe à traiter. Vérifie la variable EQUIPES_JSON.")
                break
            for equipe, url in EQUIPES.items():
                handle_team(driver, equipe, url)
        except Exception as e:
            print(f"[ERROR] Boucle principale: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

        print(f"[INFO] Attente {CHECK_INTERVAL}s avant prochaine exécution...\n")
        time.sleep(CHECK_INTERVAL)


# ===============================================================
# 🧭 ENTRY POINT
# ===============================================================
if __name__ == "__main__":
    main_loop()
