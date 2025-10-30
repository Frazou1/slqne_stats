#!/usr/bin/env python3
import os, re, json, time, argparse
from datetime import datetime
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
from zoneinfo import ZoneInfo

LOCAL_TZ = "America/Toronto"

# ===============================================================
# 🔧 Utils
# ===============================================================
def now_local_iso():
    return datetime.now(ZoneInfo(LOCAL_TZ)).isoformat()

def slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')

def get_html(url: str) -> str:
    print(f"[INFO] Téléchargement de la page {url}")
    r = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (compatible; SLQNEStats/1.0; +https://frazhome.zapto.org)"
    })
    if r.status_code != 200:
        raise RuntimeError(f"Erreur HTTP {r.status_code} sur {url}")
    print(f"[DEBUG] Taille HTML: {len(r.text)} caractères")
    return r.text

# ===============================================================
# 🧠 Extraction du classement Spordle
# ===============================================================
def parse_standings(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_=re.compile("StatsStandingsTable_table"))
    if not table:
        print("[WARN] Table de classement non trouvée dans le HTML.")
        with open("/share/slqne_last.html", "w", encoding="utf-8") as f:
            f.write(html)
        return []

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    print(f"[DEBUG] En-têtes détectées: {headers}")

    standings = []
    for tr in table.select("tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not tds or len(tds) < 2:
            continue
        row = dict(zip(headers, tds))
        standings.append(row)

    print(f"[DEBUG] {len(standings)} lignes extraites du classement.")
    return standings

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

    # Charger les équipes depuis options.json
    teams = json.loads(args.teams_json) if args.teams_json else []
    if not teams:
        print("[ERREUR] Aucune équipe fournie.")
        return

    # Connexion MQTT
    client = mqtt.Client(client_id=f"slqne_hockey_{int(time.time())}")
    if args.mqtt_user:
        client.username_pw_set(args.mqtt_user, args.mqtt_pass)
    client.connect(args.mqtt_host, int(args.mqtt_port), 60)
    client.loop_start()
    print("[INFO] Connecté à MQTT")

    # Boucle sur les catégories configurées
    for team in teams:
        name = team.get("name", "Catégorie")
        league_id = team.get("league_id")
        schedule_id = team.get("schedule_id")

        if not league_id or not schedule_id:
            print(f"[ERREUR] Catégorie {name} sans league_id ou schedule_id.")
            continue

        url = (
            f"https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/"
            f"schedule-stats-standings/{league_id}?tab=standings&scheduleId={schedule_id}"
        )

        slug = slugify(name)
        print(f"[INFO] --- Traitement catégorie {name} ---")
        print(f"[DEBUG] URL générée: {url}")

        try:
            html = get_html(url)
            standings = parse_standings(html)
            if not standings:
                print(f"[WARN] Aucun classement trouvé pour {name}")
                continue

            # Publier MQTT
            mqtt_publish(
                client,
                args.discovery_prefix,
                slug,
                "classement",
                "mdi:trophy",
                f"{len(standings)} équipes",
                {"category": name, "standings": standings, "updated": now_local_iso()}
            )

            print(f"[INFO] ✅ Catégorie {name}: {len(standings)} équipes publiées.")

        except Exception as e:
            print(f"[ERREUR] {name}: {e}")

    print("[INFO] Tous les teams traités.")
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
