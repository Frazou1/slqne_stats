#!/usr/bin/env python3
import os, re, json, time, argparse
from datetime import datetime
from typing import List, Dict, Optional

import requests
import paho.mqtt.client as mqtt
from bs4 import BeautifulSoup

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

LOCAL_TZ = "America/Toronto"

# ===============================================================
# 🔧 Utils
# ===============================================================
def now_local_iso():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(LOCAL_TZ)).isoformat()

def slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')

def build_driver() -> webdriver.Chrome:
    """Prépare un navigateur Chromium headless"""
    chrome_options = Options()
    env_flags = os.getenv("CHROMIUM_FLAGS", "")
    if env_flags:
        for flag in env_flags.split():
            chrome_options.add_argument(flag)
    else:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,2400")
    chrome_options.add_argument("--lang=fr-CA")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )
    service = Service("/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=chrome_options)

# ===============================================================
# 📊 Extraction dynamique via Selenium
# ===============================================================
def scrape_category(league_id: str, schedule_id: str, driver: webdriver.Chrome) -> List[Dict]:
    """Ouvre la page Spordle de la catégorie et extrait le tableau de classement"""
    url = f"https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings/{league_id}?tab=standings&scheduleId={schedule_id}"
    print(f"[DEBUG] URL générée: {url}")

    driver.get(url)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
        )
        time.sleep(2)
    except Exception as e:
        print(f"[WARN] Aucune table détectée pour {league_id}: {e}")

    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    # Les tableaux Spordle utilisent des classes dynamiques de type StatsStandingsTable_table__xxx
    table = None
    for t in soup.find_all("table"):
        if "StatsStandingsTable" in str(t) or len(t.find_all("th")) > 5:
            table = t
            break

    if not table:
        print("[WARN] Table de classement non trouvée dans le HTML.")
        try:
            os.makedirs("/share", exist_ok=True)
            with open("/share/slqne_last.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("[DEBUG] Snapshot HTML écrit dans /share/slqne_last.html")
        except Exception as e:
            print(f"[ERROR] Impossible d'écrire le snapshot HTML: {e}")
        return []

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    print(f"[DEBUG] En-têtes détectées: {headers}")

    rows = []
    for tr in table.select("tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) < len(headers):
            continue
        entry = dict(zip(headers, tds))
        rows.append(entry)

    print(f"[INFO] {len(rows)} lignes extraites pour cette catégorie.")
    return rows

# ===============================================================
# 🚀 MQTT
# ===============================================================
def mqtt_publish(client, prefix, slug, label, icon, state, attributes):
    sensor_id = f"{prefix}_{slug}_{label}"
    base = f"{prefix}/sensor/{sensor_id}"
    cfg_topic = f"{base}/config"
    state_topic = f"{base}/state"
    attr_topic = f"{base}/attributes"

    config_payload = {
        "name": f"SLQNE – {label.title().replace('_',' ')}",
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
        print("[ERREUR] Aucune catégorie fournie (teams-json vide)")
        return

    # Connexion MQTT
    client = mqtt.Client(client_id=f"slqne_hockey_{int(time.time())}")
    if args.mqtt_user:
        client.username_pw_set(args.mqtt_user, args.mqtt_pass)
    client.connect(args.mqtt_host, int(args.mqtt_port), 60)
    client.loop_start()
    print("[INFO] Connecté à MQTT")

    driver = build_driver()

    for team in teams:
        name = team.get("name", "Catégorie")
        league_id = team.get("league_id")
        schedule_id = team.get("schedule_id")
        slug = slugify(name)
        print(f"[INFO] --- Traitement catégorie {name} ---")

        if not league_id or not schedule_id:
            print(f"[ERREUR] {name}: league_id ou schedule_id manquant")
            continue

        try:
            standings = scrape_category(league_id, schedule_id, driver)
            if not standings:
                print(f"[WARN] Aucun classement trouvé pour {name}")
                continue

            mqtt_publish(
                client,
                args.discovery_prefix,
                slug,
                "classement",
                "mdi:trophy",
                f"{len(standings)} équipes",
                {"standings": standings, "updated": now_local_iso()}
            )

        except Exception as e:
            print(f"[ERREUR] {name}: {e}")

    driver.quit()
    client.loop_stop()
    client.disconnect()
    print("[INFO] Tous les teams traités.")
    print("[INFO] Terminé.")

if __name__ == "__main__":
    main()
