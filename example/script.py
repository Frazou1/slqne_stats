#!/usr/bin/env python3
import os, re, json, time, argparse
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

LOCAL_TZ = "America/Toronto"

# ===============================================================
# 🔧 Utils
# ===============================================================
def now_local_iso():
    return datetime.now(ZoneInfo(LOCAL_TZ)).isoformat()

def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

def setup_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=opts)
    return driver

def get_html_selenium(url: str) -> str:
    print(f"[INFO] Ouverture de {url}")
    driver = setup_driver()
    driver.get(url)
    time.sleep(4)
    html = driver.page_source
    print(f"[DEBUG] Taille du HTML ({url.split('?tab=')[-1]}): {len(html)} caractères")
    driver.quit()
    return html

# ===============================================================
# 🧠 Parsing des sections
# ===============================================================
def parse_table_generic(html: str) -> List[Dict]:
    """Utilisée pour standings ou playerstats."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        print("[WARN] Aucune table trouvée dans la page.")
        return []

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    rows = []
    for tr in table.select("tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) >= len(headers):
            rows.append(dict(zip(headers, tds)))

    print(f"[DEBUG] {len(rows)} lignes extraites ({headers[:5]}...)")
    return rows

def detect_last_game(html: str) -> Optional[Dict]:
    """Recherche un tableau ou bloc contenant les derniers matchs."""
    soup = BeautifulSoup(html, "html.parser")

    # --- Bloc 1 : table id="recentGames"
    tbl = soup.find("table", {"id": "recentGames"})
    if tbl:
        row = tbl.find("tr")
        if row:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            print(f"[DEBUG] Dernier match (recentGames): {cols}")
            return {
                "date": cols[0] if len(cols) > 0 else "",
                "visitor": cols[1] if len(cols) > 1 else "",
                "home": cols[2] if len(cols) > 2 else "",
                "result": cols[3] if len(cols) > 3 else ""
            }

    # --- Bloc 2 : recherche libre d’un div “Derniers matchs”
    candidates = soup.find_all(text=re.compile(r"(Derniers matchs|Recent Games)", re.I))
    for c in candidates:
        table = c.find_parent("div").find("table") if c.find_parent("div") else None
        if table:
            row = table.find("tr")
            if row:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                print(f"[DEBUG] Dernier match (bloc libre): {cols}")
                return {
                    "date": cols[0] if len(cols) > 0 else "",
                    "visitor": cols[1] if len(cols) > 1 else "",
                    "home": cols[2] if len(cols) > 2 else "",
                    "result": cols[3] if len(cols) > 3 else ""
                }

    print("[WARN] Aucun dernier match détecté dans le HTML.")
    return None

# ===============================================================
# 🚀 MQTT
# ===============================================================
def mqtt_publish(client, discovery_prefix, entity_prefix, slug, label, icon, state, attributes):
    """Publie un capteur MQTT avec MQTT Discovery."""
    sensor_id = f"{entity_prefix}_{slug}_{label}"
    base = f"{discovery_prefix}/sensor/{sensor_id}"
    cfg_topic = f"{base}/config"
    state_topic = f"{base}/state"
    attr_topic = f"{base}/attributes"

    config_payload = {
        "name": f"SLQNE – {label.replace('_', ' ').title()}",
        "uniq_id": sensor_id,
        "stat_t": state_topic,
        "json_attr_t": attr_topic,
        "dev": {"name": f"SLQNE {slug}", "ids": [f"slqne_{slug}"]},
        "icon": icon
    }

    client.publish(cfg_topic, json.dumps(config_payload), retain=True, qos=1)
    client.publish(attr_topic, json.dumps(attributes, ensure_ascii=False), retain=True, qos=0)
    client.publish(state_topic, state, retain=True, qos=0)
    print(f"[MQTT] Sensor publié: {sensor_id}")

# ===============================================================
# 🏒 MAIN
# ===============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams-json", default="")
    parser.add_argument("--entity_prefix", default="slqne")
    parser.add_argument("--mqtt_host", default="core-mosquitto")
    parser.add_argument("--mqtt_port", default="1883")
    parser.add_argument("--mqtt_user", default="")
    parser.add_argument("--mqtt_pass", default="")
    parser.add_argument("--discovery_prefix", default="homeassistant")
    args = parser.parse_args()

    teams = json.loads(args.teams_json) if args.teams_json else []
    if not teams:
        print("[ERREUR] Aucune catégorie configurée.")
        return

    client = mqtt.Client(client_id=f"slqne_hockey_{int(time.time())}")
    if args.mqtt_user:
        client.username_pw_set(args.mqtt_user, args.mqtt_pass)
    client.connect(args.mqtt_host, int(args.mqtt_port), 60)
    client.loop_start()
    print("[INFO] Connecté à MQTT")

    base_url = "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings"

    for team in teams:
        name = team.get("name", "Catégorie")
        league_id = team.get("league_id")
        schedule_id = team.get("schedule_id")
        slug = slugify(name)
        print(f"[INFO] --- Traitement catégorie {name} ---")

        try:
            # 1️⃣ Classement
            url_standings = f"{base_url}/{league_id}?tab=standings&scheduleId={schedule_id}"
            html_standings = get_html_selenium(url_standings)
            standings = parse_table_generic(html_standings)

            mqtt_publish(
                client, args.discovery_prefix, args.entity_prefix, slug,
                "classement", "mdi:trophy",
                f"{len(standings)} équipes",
                {"standings": standings, "updated": now_local_iso()}
            )

            # 2️⃣ Stats joueurs
            url_players = f"{base_url}/{league_id}?tab=playerstats&scheduleId={schedule_id}"
            html_players = get_html_selenium(url_players)
            players = parse_table_generic(html_players)

            mqtt_publish(
                client, args.discovery_prefix, args.entity_prefix, slug,
                "stats_joueurs", "mdi:hockey-sticks",
                f"{len(players)} joueurs",
                {"players": players, "updated": now_local_iso()}
            )

            # 3️⃣ Dernier match (si dispo)
            last_game = detect_last_game(html_standings)
            if last_game:
                mqtt_publish(
                    client, args.discovery_prefix, args.entity_prefix, slug,
                    "dernier_match", "mdi:hockey-puck",
                    last_game.get("result", "N/A"),
                    {"last_game": last_game, "updated": now_local_iso()}
                )
            else:
                print(f"[WARN] Aucun dernier match détecté pour {name}")

        except Exception as e:
            print(f"[ERREUR] {name}: {e}")

    print("[INFO] Tous les teams traités.")
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
