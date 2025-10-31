#!/usr/bin/env python3
# coding: utf-8
"""
SLQNE Hockey Stats Add-on
- Classement
- Stats joueurs
- Dernier & prochain match
"""

import os, time, json, re, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import paho.mqtt.publish as publish

# -----------------------------------------------
# CONFIG
# -----------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "192.168.2.65")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
DISCOVERY_PREFIX = os.getenv("DISCOVERY_PREFIX", "homeassistant")
LOCAL_TZ = "America/Toronto"
ENTITY_PREFIX = "slqne"

TEAMS = {
    "Hayden Hockey": "bf27e08e-8d52-41be-a097-a6cf79f4466a",
    "Loik Hockey": "13c38dd1-e464-4835-af5f-75be8561daf6",
}

# -----------------------------------------------
# SELENIUM (pour pages HTML)
# -----------------------------------------------
def get_html_selenium(url):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=chrome_options)
    driver.get(url)
    time.sleep(4)
    html = driver.page_source
    driver.quit()
    return html

# -----------------------------------------------
# CLASSEMENT (tab=standings)
# -----------------------------------------------
def parse_standings(html):
    soup = BeautifulSoup(html, "html.parser")
    standings = []
    tables = soup.find_all("table")
    for table in tables:
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        for tr in table.find_all("tr")[1:]:
            values = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(values) == len(headers):
                standings.append(dict(zip(headers, values)))
    return standings

# -----------------------------------------------
# JOUEURS (tab=playerstats)
# -----------------------------------------------
def parse_playerstats(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    players = []
    if not table:
        return players
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    for tr in table.find_all("tr")[1:]:
        values = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(values) == len(headers):
            players.append(dict(zip(headers, values)))
    return players

# -----------------------------------------------
# MATCHS (tab=schedule)
# -----------------------------------------------
def parse_schedule_games(html: str):
    """Analyse le HTML de l’onglet 'schedule' pour extraire les derniers et prochains matchs"""
    soup = BeautifulSoup(html, "html.parser")
    games = []

    for li in soup.find_all("li", {"data-event": "true"}):
        article = li.find("article", {"itemtype": "https://schema.org/SportsEvent"})
        if not article:
            continue

        # 📅 Date
        time_tag = article.find("time")
        date_iso = time_tag.get("datetime") if time_tag else None
        date_obj = None
        if date_iso:
            try:
                date_obj = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
            except Exception:
                pass

        # 🏟️ Lieu
        venue_tag = article.find("address")
        venue = venue_tag.get_text(strip=True) if venue_tag else ""

        # 🏒 Équipes
        teams = article.find_all("article", {"itemtype": "https://schema.org/SportsTeam"})
        team_away, team_home = "", ""
        if len(teams) >= 2:
            team_away = teams[0].get_text(strip=True).split("\n")[0]
            team_home = teams[-1].get_text(strip=True).split("\n")[0]

        # 🕐 Score ou heure
        score = ""
        score_tags = article.select(".font-brand.font-size-lg.d-flex")
        if score_tags and len(score_tags) == 2:
            away_score = re.sub(r"\D", "", score_tags[0].text)
            home_score = re.sub(r"\D", "", score_tags[1].text)
            score = f"{away_score}-{home_score}" if away_score and home_score else ""

        time_display = ""
        if not score:
            time_display = article.select_one(".font-brand.font-size-lg.text-dark.text-nowrap")
            if time_display:
                score = time_display.get_text(strip=True)

        games.append({
            "date": date_obj,
            "venue": venue,
            "away": team_away,
            "home": team_home,
            "score": score,
        })

    # ⏳ Tri chronologique
    games = [g for g in games if g["date"]]
    games.sort(key=lambda x: x["date"])

    now = datetime.now(ZoneInfo(LOCAL_TZ))
    past_games = [g for g in games if g["date"] <= now]
    future_games = [g for g in games if g["date"] > now]

    result = {
        "last": past_games[-1] if past_games else None,
        "next": future_games[0] if future_games else None
    }

    print(f"[DEBUG] {len(games)} matchs extraits ({len(past_games)} passés, {len(future_games)} futurs)")
    print(f"[DEBUG] Dernier match: {result['last']}")
    print(f"[DEBUG] Prochain match: {result['next']}")

    return result

# -----------------------------------------------
# MQTT Publishing
# -----------------------------------------------
def publish_sensor(name, payload):
    topic = f"{DISCOVERY_PREFIX}/sensor/{ENTITY_PREFIX}_{name}/state"
    publish.single(topic, json.dumps(payload, ensure_ascii=False), hostname=MQTT_HOST, port=MQTT_PORT)
    print(f"[MQTT] Sensor publié: {ENTITY_PREFIX}_{name}")

# -----------------------------------------------
# MAIN
# -----------------------------------------------
def main():
    print("[INFO] Démarrage de l'add-on SLQNE Hockey Stats")
    print(f"[INFO] MQTT = {MQTT_HOST}:{MQTT_PORT}")
    print(f"[INFO] Discovery prefix = {DISCOVERY_PREFIX}")
    print(f"[INFO] Entity prefix = {ENTITY_PREFIX}")
    print(f"[INFO] Équipes configurées : {', '.join(TEAMS.keys())}")

    for team_name, schedule_id in TEAMS.items():
        print(f"[INFO] --- Traitement catégorie {team_name} ---")
        base_url = f"https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings/{schedule_id}"

        # Classement
        url_standings = f"{base_url}?tab=standings&scheduleId={schedule_id}"
        html_standings = get_html_selenium(url_standings)
        standings = parse_standings(html_standings)
        publish_sensor(f"{team_name.lower().replace(' ', '_')}_classement", {"standings": standings})

        # Stats joueurs
        url_stats = f"{base_url}?tab=playerstats&scheduleId={schedule_id}"
        html_stats = get_html_selenium(url_stats)
        players = parse_playerstats(html_stats)
        publish_sensor(f"{team_name.lower().replace(' ', '_')}_stats_joueurs", {"players": players})

        # Matchs
        url_schedule = f"{base_url}?tab=schedule&scheduleId={schedule_id}"
        html_schedule = get_html_selenium(url_schedule)
        games = parse_schedule_games(html_schedule)

        if games["last"]:
            publish_sensor(f"{team_name.lower().replace(' ', '_')}_dernier_match", games["last"])
        else:
            print(f"[WARN] Aucun dernier match détecté pour {team_name}")

        if games["next"]:
            publish_sensor(f"{team_name.lower().replace(' ', '_')}_prochain_match", games["next"])
        else:
            print(f"[WARN] Aucun prochain match détecté pour {team_name}")

    print("[INFO] Tous les teams traités.")
    print("[INFO] Attente 7200s avant prochaine exécution...")

if __name__ == "__main__":
    main()
