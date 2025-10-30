#!/usr/bin/env python3
import os, re, json, time, argparse
from datetime import datetime
from typing import List, Dict, Optional
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
# 🧠 Extraction des sections du site Spordle
# ===============================================================
def parse_standings(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "standings"})
    if not table:
        print("[WARN] Table standings non trouvée")
        return []

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    print(f"[DEBUG] Headers standings: {headers}")

    rows = []
    for tr in table.select("tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) < 3:
            continue
        entry = dict(zip(headers, tds))
        rows.append(entry)

    print(f"[DEBUG] {len(rows)} lignes de classement extraites")
    return rows

def parse_players_stats(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "playersStats"})
    if not table:
        print("[WARN] Table playersStats non trouvée")
        return []

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    print(f"[DEBUG] Headers joueurs: {headers}")

    rows = []
    for tr in table.select("tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not tds or len(tds) < 3:
            continue
        player = dict(zip(headers, tds))
        rows.append(player)

    print(f"[DEBUG] {len(rows)} lignes de joueurs extraites")
    return rows

def parse_goalies_stats(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "goaliesStats"})
    if not table:
        print("[WARN] Table goaliesStats non trouvée")
        return []

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    print(f"[DEBUG] Headers gardiens: {headers}")

    rows = []
    for tr in table.select("tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not tds or len(tds) < 3:
            continue
        goalie = dict(zip(headers, tds))
        rows.append(goalie)

    print(f"[DEBUG] {len(rows)} lignes de gardiens extraites")
    return rows

def parse_last_game_from_standings(html: str) -> Optional[Dict]:
    """
    Tentative de repérage du dernier match à partir des tables standings / stats
    (si aucune info explicite n’est donnée ailleurs sur la page)
    """
    try:
        # Certains blocs Spordle incluent une table "recentGames"
        soup = BeautifulSoup(html, "html.parser")
        game_table = soup.find("table", {"id": "recentGames"})
        if not game_table:
            print("[WARN] Table recentGames non trouvée")
            return None

        first = game_table.select_one("tbody tr")
        if not first:
            return None

        cols = [td.get_text(strip=True) for td in first.find_all("td")]
        print(f"[DEBUG] Ligne match trouvée: {cols}")
        return {
            "date": cols[0] if len(cols) > 0 else "",
            "visitor": cols[1] if len(cols) > 1 else "",
            "home": cols[2] if len(cols) > 2 else "",
            "result": cols[3] if len(cols) > 3 else ""
        }
    except Exception as e:
        print(f"[DEBUG] Erreur parse_last_game_from_standings: {e}")
        return None

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

    # Charger les équipes
    teams = json.loads(args.teams_json) if args.teams_json else []
    if not teams:
        print("[ERREUR] Aucune équipe fournie")
        return

    # Connexion MQTT
    client = mqtt.Client(client_id=f"slqne_hockey_{int(time.time())}")
    if args.mqtt_user:
        client.username_pw_set(args.mqtt_user, args.mqtt_pass)
    client.connect(args.mqtt_host, int(args.mqtt_port), 60)
    client.loop_start()
    print("[INFO] Connecté à MQTT")

    for team in teams:
        name = team.get("name", "Équipe")
        url = team.get("team_url")
        slug = slugify(name)
        print(f"[INFO] --- Traitement équipe {name} ---")

        try:
            html = get_html(url)
            standings = parse_standings(html)
            players = parse_players_stats(html)
            goalies = parse_goalies_stats(html)
            last_game = parse_last_game_from_standings(html)

            # 🔹 Publier classement
            mqtt_publish(client, args.discovery_prefix, slug, "classement", "mdi:trophy",
                         f"{len(standings)} équipes",
                         {"standings": standings, "updated": now_local_iso()})

            # 🔹 Publier joueurs
            mqtt_publish(client, args.discovery_prefix, slug, "stats_joueurs", "mdi:hockey-sticks",
                         f"{len(players)} joueurs",
                         {"players": players, "updated": now_local_iso()})

            # 🔹 Publier gardiens
            mqtt_publish(client, args.discovery_prefix, slug, "stats_gardiens", "mdi:account-hard-hat",
                         f"{len(goalies)} gardiens",
                         {"goalies": goalies, "updated": now_local_iso()})

            # 🔹 Dernier match (si dispo)
            if last_game:
                mqtt_publish(client, args.discovery_prefix, slug, "dernier_match", "mdi:hockey-puck",
                             f"{last_game.get('visitor','')} @ {last_game.get('home','')}",
                             {"last_game": last_game, "updated": now_local_iso()})
            else:
                print(f"[WARN] Aucun dernier match détecté pour {name}")

        except Exception as e:
            print(f"[ERREUR] {name}: {e}")

    print("[INFO] Tous les teams traités.")
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
