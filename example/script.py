#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SLQNE – Scraper Spordle automatisé
----------------------------------
Version : 3.3 (Novembre 2025)

Compatible avec run.sh :
  → lit --teams-json et --players-json
  → garde un seul driver Selenium ouvert
  → publie les logos, dernier match et prochain match
"""

import os
import re
import json
import time
import random
import argparse
import paho.mqtt.publish as publish
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# ===============================================================
# ⚙️ CONFIGURATION VIA ARGPARSE
# ===============================================================
def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams-json", default="")
    parser.add_argument("--players-json", default="")
    parser.add_argument("--entity_prefix", default="slqne")
    parser.add_argument("--mqtt_host", default="127.0.0.1")
    parser.add_argument("--mqtt_port", type=int, default=1883)
    parser.add_argument("--mqtt_user", default="")
    parser.add_argument("--mqtt_pass", default="")
    parser.add_argument("--discovery_prefix", default="homeassistant")
    args = parser.parse_args()

    teams = json.loads(args.teams_json) if args.teams_json else []
    players = json.loads(args.players_json) if args.players_json else []

    EQUIPES = {}
    for team in teams:
        league_id = team.get("league_id")
        schedule_id = team.get("schedule_id")
        name = team.get("name")
        if league_id and schedule_id and name:
            url = f"https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings/{league_id}?tab=schedule&scheduleId={schedule_id}"
            EQUIPES[name] = url

    if not EQUIPES:
        print("[ERROR] Aucun bloc 'teams' valide trouvé dans la config.")
    else:
        print(f"[INFO] {len(EQUIPES)} équipes configurées à partir de run.sh.")

    if players:
        print(f"[INFO] {len(players)} joueur(s) suivis :")
        for p in players:
            print(f"   → {p.get('player_name','?')} ({p.get('team_name','?')})")

    return args, EQUIPES


# ===============================================================
# 📡 MQTT
# ===============================================================
def publish_sensor(sensor, payload, mqtt_host, mqtt_port, mqtt_user, mqtt_pass):
    try:
        topic = f"homeassistant/sensor/{sensor}/state"
        publish.single(
            topic,
            json.dumps(payload, ensure_ascii=False),
            hostname=mqtt_host,
            port=mqtt_port,
            auth={'username': mqtt_user, 'password': mqtt_pass} if mqtt_user else None,
        )
        print(f"[MQTT] Sensor publié: {sensor}")
    except Exception as e:
        print(f"[ERROR] MQTT publish échoué: {e}")


# ===============================================================
# 🌐 SELENIUM
# ===============================================================
def create_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver


def safe_get(driver, url, retries=3):
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
# 🏒 TRAITEMENT PAR ÉQUIPE
# ===============================================================
def handle_team(driver, name, url, args):
    print(f"[INFO] --- Traitement catégorie {name} ---")
    standings_html = safe_get(driver, url.replace("?tab=schedule", "?tab=standings"))
    if standings_html:
        logos = parse_logos_from_standings(standings_html)
        publish_sensor(f"{args.entity_prefix}_{slugify(name)}_logos_equipes", logos,
                       args.mqtt_host, args.mqtt_port, args.mqtt_user, args.mqtt_pass)

    schedule_html = safe_get(driver, url)
    scroll_page(driver)
    matches = parse_games_from_schedule(driver.page_source or schedule_html)

    last_game = find_team_game(matches, name, future=False)
    if last_game:
        publish_sensor(f"{args.entity_prefix}_{slugify(name)}_dernier_match", last_game,
                       args.mqtt_host, args.mqtt_port, args.mqtt_user, args.mqtt_pass)

    next_game = find_team_game(matches, name, future=True)
    if next_game:
        publish_sensor(f"{args.entity_prefix}_{slugify(name)}_prochain_match", next_game,
                       args.mqtt_host, args.mqtt_port, args.mqtt_user, args.mqtt_pass)


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# ===============================================================
# 🚀 MAIN LOOP
# ===============================================================
def main():
    args, EQUIPES = get_args()
    print("[INFO] Attente 30s avant démarrage (MQTT warmup)...")
    time.sleep(30)

    driver = None
    try:
        driver = create_driver()
        for equipe, url in EQUIPES.items():
            handle_team(driver, equipe, url, args)
    except Exception as e:
        print(f"[ERROR] Boucle principale: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
