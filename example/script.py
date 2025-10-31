#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SLQNE – Scraper Spordle automatisé
----------------------------------
Version : 3.0 (Octobre 2025)
Fonctions :
 - Récupère le classement, les stats joueurs, le dernier et le prochain match
 - Extrait les logos des équipes
 - Publie sur MQTT
 - Gestion des timeouts et redémarrage auto
"""

import os
import re
import json
import time
import random
import paho.mqtt.publish as publish
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# ===================== CONFIG =====================
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")
CHECK_INTERVAL = 7200  # secondes

EQUIPES = {
    "PATRIOTES QUÉBEC-CENTRE": "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings/bf27e08e-8d52-41be-a097-a6cf79f4466a",
    "PATRIOTES QUÉBEC-CENTRE 2": "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings/13c38dd1-e464-4835-af5f-75be8561daf6",
}
# ===================================================


def publish_sensor(sensor, payload):
    """Publie un sensor MQTT"""
    try:
        topic = f"homeassistant/sensor/{sensor}/state"
        publish.single(topic, json.dumps(payload, ensure_ascii=False),
                       hostname=MQTT_HOST, port=MQTT_PORT,
                       auth={'username': MQTT_USER, 'password': MQTT_PASS} if MQTT_USER else None)
        print(f"[MQTT] Sensor publié: {sensor}")
    except Exception as e:
        print(f"[ERROR] MQTT publish échoué: {e}")


def create_driver():
    """Initialise le navigateur headless"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(45)
    return driver


def safe_get(driver, url, retries=3):
    """Ouvre une page avec retries si 504"""
    for i in range(retries):
        try:
            driver.get(url)
            time.sleep(random.uniform(1.5, 3.5))
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
    """Scroll progressif jusqu'à la fin du contenu"""
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


def parse_logos_from_standings(html):
    """Extrait les logos et noms d'équipes du classement"""
    soup = BeautifulSoup(html, "html.parser")
    logos = {}
    for row in soup.select("tr"):
        team = row.select_one("td:nth-child(2)")
        logo = row.select_one("img")
        if team and logo and team.text.strip():
            name = team.text.strip()
            url = logo.get("src")
            logos[name] = url
    print(f"[DEBUG] {len(logos)} logos d'équipes extraits")
    return logos


def parse_games_from_schedule(html):
    """Analyse les matchs depuis la page HTML"""
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    cards = soup.find_all("div", class_=re.compile("GameCard|game-card|card"))
    for card in cards:
        try:
            date_tag = card.find("div", string=re.compile(r"\w+ \d{1,2}"))
            teams = [t.get_text(strip=True) for t in card.find_all("div", class_=re.compile("team-name"))]
            scores = [s.get_text(strip=True) for s in card.find_all("div", class_=re.compile("score|final-score"))]
            arena_tag = card.find("div", string=re.compile("QC"))
            final = "Final" in card.get_text()
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
        last_final = [m for m in team_matches if m["final"]]
        return last_final[-1] if last_final else team_matches[-1]


def handle_team(driver, name, url):
    """Process complet d'une équipe"""
    print(f"[INFO] --- Traitement catégorie {name} ---")

    # 1️⃣ Classement / logos
    standings_html = safe_get(driver, f"{url}?tab=standings")
    if standings_html:
        logos = parse_logos_from_standings(standings_html)
        publish_sensor(f"slqne_{slugify(name)}_logos_equipes", logos)

    # 2️⃣ Dernier match
    schedule_html = safe_get(driver, f"{url}?tab=schedule")
    scroll_page(driver)
    matches = parse_games_from_schedule(schedule_html)
    last_game = find_team_game(matches, name, future=False)
    if last_game:
        publish_sensor(f"slqne_{slugify(name)}_dernier_match", last_game)

    # 3️⃣ Prochain match
    next_game = find_team_game(matches, name, future=True)
    if next_game:
        publish_sensor(f"slqne_{slugify(name)}_prochain_match", next_game)


def slugify(text):
    """Simplifie un nom pour usage MQTT"""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def main_loop():
    """Boucle infinie avec protection timeout"""
    while True:
        print("[INFO] --------------------------------------------------------")
        print(f"[INFO] Exécution du script Python SLQNE… ({datetime.now().isoformat()})")

        try:
            driver = create_driver()
            for equipe, url in EQUIPES.items():
                handle_team(driver, equipe, url)
            driver.quit()
        except Exception as e:
            print(f"[ERROR] Boucle principale: {e}")
            try:
                driver.quit()
            except Exception:
                pass

        print(f"[INFO] Attente {CHECK_INTERVAL}s avant prochaine exécution...\n")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main_loop()
