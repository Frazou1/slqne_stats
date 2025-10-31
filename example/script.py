#!/usr/bin/env python3
# coding: utf-8
"""
SLQNE Hockey Stats Add-on
→ Classement, statistiques joueurs, dernier match et prochain match
"""

import os, time, json, re
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import paho.mqtt.client as mqtt

# -----------------------------------------------
# ⚙️ CONFIGURATION GÉNÉRALE
# -----------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
DISCOVERY_PREFIX = os.getenv("DISCOVERY_PREFIX", "homeassistant")
ENTITY_PREFIX = "slqne"
LOCAL_TZ = "America/Toronto"

TEAMS = {
    "Hayden Hockey": "bf27e08e-8d52-41be-a097-a6cf79f4466a",
    "Loik Hockey": "13c38dd1-e464-4835-af5f-75be8561daf6",
}

# -----------------------------------------------
# 🧠 UTILITAIRES
# -----------------------------------------------
def get_html_selenium(url):
    """Charge une page Spordle avec Selenium (headless Chrome)"""
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=opts)
    driver.get(url)
    time.sleep(4)
    html = driver.page_source
    driver.quit()
    print(f"[DEBUG] Taille du HTML ({url.split('?tab=')[-1]}): {len(html)} caractères")
    return html


def now_local_iso():
    return datetime.now(ZoneInfo(LOCAL_TZ)).isoformat()


# -----------------------------------------------
# 📊 PARSING — CLASSEMENT
# -----------------------------------------------
def parse_standings(html):
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    all_rows = []
    for table in tables:
        headers = [th.get_text(strip=True) for th in table.select("thead th")]
        for tr in table.select("tbody tr"):
            values = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(values) == len(headers):
                all_rows.append(dict(zip(headers, values)))
    print(f"[DEBUG] {len(all_rows)} lignes extraites pour standings")
    return all_rows


# -----------------------------------------------
# 🧾 PARSING — STATS JOUEURS
# -----------------------------------------------
def parse_playerstats(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    players = []
    if not table:
        print("[WARN] Aucune table trouvée dans playerstats.")
        return players
    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    for tr in table.select("tbody tr"):
        values = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(values) == len(headers):
            players.append(dict(zip(headers, values)))
    print(f"[DEBUG] {len(players)} lignes extraites pour playerstats")
    return players


# -----------------------------------------------
# 🏒 PARSING — CALENDRIER (Dernier / Prochain match)
# -----------------------------------------------
def parse_schedule_games(html: str):
    """Analyse le HTML du calendrier (tab=schedule) pour extraire les matchs"""
    soup = BeautifulSoup(html, "html.parser")
    games = []

    for li in soup.find_all("li", {"data-event": "true"}):
        article = li.find("article", {"itemtype": "https://schema.org/SportsEvent"})
        if not article:
            continue

        # Date
        time_tag = article.find("time")
        date_iso = time_tag.get("datetime") if time_tag else None
        date_obj = None
        if date_iso:
            try:
                date_obj = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
            except Exception:
                pass

        # Lieu
        venue_tag = article.find("address")
        venue = venue_tag.get_text(strip=True) if venue_tag else ""

        # Équipes
        teams = article.find_all("article", {"itemtype": "https://schema.org/SportsTeam"})
        away_team = teams[0].get_text(strip=True).split("\n")[0] if len(teams) > 0 else ""
        home_team = teams[-1].get_text(strip=True).split("\n")[0] if len(teams) > 1 else ""

        # Score ou heure
        score = ""
        score_tags = article.select(".font-brand.font-size-lg.d-flex")
        if score_tags and len(score_tags) == 2:
            away_score = re.sub(r"\D", "", score_tags[0].text)
            home_score = re.sub(r"\D", "", score_tags[1].text)
            score = f"{away_score}-{home_score}" if away_score and home_score else ""

        # Si pas de score, on prend l’heure prévue
        if not score:
            time_display = article.select_one(".font-brand.font-size-lg.text-dark.text-nowrap")
            if time_display:
                score = time_display.get_text(strip=True)

        games.append({
            "date": date_obj,
            "venue": venue,
            "away": away_team,
            "home": home_team,
            "score": score,
        })

    # Tri chronologique
    games = [g for g in games if g["date"]]
    games.sort(key=lambda x: x["date"])

    now = datetime.now(ZoneInfo(LOCAL_TZ))
    past_games = [g for g in games if g["date"] <= now]
    future_games = [g for g in games if g["date"] > now]

    result = {
        "last": past_games[-1] if past_games else None,
        "next": future_games[0] if future_games else None
    }

    print(f"[DEBUG] {len(games)} matchs trouvés ({len(past_games)} passés / {len(future_games)} futurs)")
    return result


# -----------------------------------------------
# 📡 MQTT
# -----------------------------------------------
def setup_mqtt():
    client = mqtt.Client()
    mqtt_user = os.getenv("MQTT_USER")
    mqtt_pass = os.getenv("MQTT_PASS")
    if mqtt_user and mqtt_pass:
        client.username_pw_set(mqtt_user, mqtt_pass)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    print(f"[INFO] Connecté à MQTT ({MQTT_HOST}:{MQTT_PORT})")
    return client


def publish_sensor(client, name, payload):
    topic = f"{DISCOVERY_PREFIX}/sensor/{ENTITY_PREFIX}_{name}/state"
    client.publish(topic, json.dumps(payload, ensure_ascii=False), retain=True)
    print(f"[MQTT] Sensor publié: {ENTITY_PREFIX}_{name}")


# -----------------------------------------------
# 🚀 MAIN
# -----------------------------------------------
def main():
    print("[INFO] Démarrage de l'add-on SLQNE Hockey Stats")
    print(f"[INFO] MQTT = {MQTT_HOST}:{MQTT_PORT}")
    print(f"[INFO] Discovery prefix = {DISCOVERY_PREFIX}")
    print(f"[INFO] Entity prefix = {ENTITY_PREFIX}")
    print(f"[INFO] Équipes configurées : {', '.join(TEAMS.keys())}")

    client = setup_mqtt()

    for team_name, schedule_id in TEAMS.items():
        print(f"\n[INFO] --- Traitement catégorie {team_name} ---")
        base_url = f"https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings/{schedule_id}"

        # 🏆 Classement
        url_standings = f"{base_url}?tab=standings&scheduleId={schedule_id}"
        html_standings = get_html_selenium(url_standings)
        standings = parse_standings(html_standings)
        publish_sensor(client, f"{team_name.lower().replace(' ', '_')}_classement", {
            "standings": standings,
            "updated": now_local_iso()
        })

        # 👥 Stats joueurs
        url_players = f"{base_url}?tab=playerstats&scheduleId={schedule_id}"
        html_players = get_html_selenium(url_players)
        players = parse_playerstats(html_players)
        publish_sensor(client, f"{team_name.lower().replace(' ', '_')}_stats_joueurs", {
            "players": players,
            "updated": now_local_iso()
        })

        # 🏒 Dernier et prochain match
        url_schedule = f"{base_url}?tab=schedule&scheduleId={schedule_id}"
        html_schedule = get_html_selenium(url_schedule)
        games = parse_schedule_games(html_schedule)

        if games["last"]:
            publish_sensor(client, f"{team_name.lower().replace(' ', '_')}_dernier_match", {
                "last_game": games["last"],
                "updated": now_local_iso()
            })
        else:
            print(f"[WARN] Aucun dernier match trouvé pour {team_name}")

        if games["next"]:
            publish_sensor(client, f"{team_name.lower().replace(' ', '_')}_prochain_match", {
                "next_game": games["next"],
                "updated": now_local_iso()
            })
        else:
            print(f"[WARN] Aucun prochain match trouvé pour {team_name}")

    client.loop_stop()
    client.disconnect()
    print("\n[INFO] Tous les teams traités.")
    print("[INFO] Attente 7200s avant prochaine exécution...")


# -----------------------------------------------
# 🏁 EXECUTION
# -----------------------------------------------
if __name__ == "__main__":
    main()
