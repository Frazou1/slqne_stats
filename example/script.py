#!/usr/bin/env python3
import os, re, json, time, argparse
from datetime import datetime
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
from zoneinfo import ZoneInfo

LOCAL_TZ = "America/Toronto"
LOGO_CACHE_FILE = "/data/team_logos_cache.json"

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
        "User-Agent": "Mozilla/5.0 (compatible; SLQNEStats/1.1; +https://frazhome.zapto.org)"
    })
    if r.status_code != 200:
        raise RuntimeError(f"Erreur HTTP {r.status_code} sur {url}")
    print(f"[DEBUG] Taille HTML: {len(r.text)} caractères")
    return r.text

# ===============================================================
# 📦 Gestion du cache logo (pour éviter rechargement inutile)
# ===============================================================
def load_logo_cache() -> Dict[str, str]:
    if os.path.exists(LOGO_CACHE_FILE):
        try:
            with open(LOGO_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_logo_cache(cache: Dict[str, str]):
    try:
        with open(LOGO_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] Impossible d’enregistrer le cache logo: {e}")

# ===============================================================
# 🏒 Extraction du classement multi-division
# ===============================================================
def parse_standings(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    print(f"[DEBUG] {len(tables)} tables trouvées dans la page standings")
    rows = []

    for table in tables:
        # Repérer la division associée
        division_title = "Inconnue"
        previous = table.find_previous("h2")
        if previous:
            division_title = previous.get_text(strip=True)
        else:
            h3 = table.find_previous("h3")
            if h3:
                division_title = h3.get_text(strip=True)

        headers = [th.get_text(strip=True) for th in table.select("thead th")]
        body_rows = table.select("tbody tr")
        print(f"[DEBUG] {len(body_rows)} lignes extraites pour {division_title}")

        for tr in body_rows:
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) >= 3:
                entry = dict(zip(headers, tds))
                entry["division"] = division_title

                # Lien vers la page d’équipe
                team_link = tr.find("a", href=True)
                entry["team_url"] = (
                    f"https://page.spordle.com{team_link['href']}"
                    if team_link else ""
                )
                rows.append(entry)

    print(f"[DEBUG] Total {len(rows)} lignes multi-division extraites")
    return rows

# ===============================================================
# 🧠 Stats joueurs
# ===============================================================
def parse_players_stats(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        print("[WARN] Table joueurs non trouvée")
        return []
    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    rows = []
    for tr in table.select("tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) >= 3:
            rows.append(dict(zip(headers, tds)))
    print(f"[DEBUG] {len(rows)} lignes extraites ({headers[:5]}...)")
    return rows

# ===============================================================
# 🏒 Logo des équipes
# ===============================================================
def fetch_team_logo(team_url: str, cache: Dict[str, str]) -> str:
    """Récupère le logo d’une équipe depuis sa page (avec cache)."""
    if not team_url:
        return ""
    if team_url in cache:
        return cache[team_url]

    try:
        print(f"[INFO] Lecture logo: {team_url}")
        full_url = team_url if team_url.startswith("http") else f"https://page.spordle.com{team_url}"
        r = requests.get(full_url, timeout=20)
        if r.status_code != 200:
            print(f"[WARN] Logo HTTP {r.status_code} sur {team_url}")
            return ""
        soup = BeautifulSoup(r.text, "html.parser")

        logo_tag = soup.select_one("img[src*='team'], img[class*='logo'], div[class*='logo'] img")
        if logo_tag and logo_tag.get("src"):
            logo = logo_tag["src"]
            if logo.startswith("/"):
                logo = f"https://page.spordle.com{logo}"
            cache[team_url] = logo
            print(f"[DEBUG] Logo trouvé: {logo}")
            return logo
        print(f"[WARN] Aucun logo trouvé sur {team_url}")
        return ""
    except Exception as e:
        print(f"[ERROR] fetch_team_logo: {e}")
        return ""

# ===============================================================
# 🚀 MQTT
# ===============================================================
def mqtt_publish(client, prefix, slug, label, icon, state, attributes):
    sensor_id = f"{slug}_{label}"
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
# 🧩 MAIN
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
        print("[ERREUR] Aucune équipe/catégorie fournie")
        return

    client = mqtt.Client(client_id=f"slqne_hockey_{int(time.time())}")
    if args.mqtt_user:
        client.username_pw_set(args.mqtt_user, args.mqtt_pass)
    client.connect(args.mqtt_host, int(args.mqtt_port), 60)
    client.loop_start()
    print("[INFO] Connecté à MQTT")

    logo_cache = load_logo_cache()

    for team in teams:
        name = team.get("name", "Catégorie")
        league_id = team.get("league_id")
        schedule_id = team.get("schedule_id")
        slug = slugify(name)

        base_url = f"https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings/{league_id}?scheduleId={schedule_id}"
        standings_url = f"{base_url}&tab=standings"
        players_url = f"{base_url}&tab=playerstats"

        print(f"[INFO] --- Traitement catégorie {name} ---")

        try:
            # --- Classement ---
            html = get_html(standings_url)
            standings = parse_standings(html)
            for entry in standings:
                entry["team_logo"] = fetch_team_logo(entry.get("team_url", ""), logo_cache)
            save_logo_cache(logo_cache)

            mqtt_publish(
                client, args.discovery_prefix, slug, "slqne_classement", "mdi:trophy",
                f"{len(standings)} équipes",
                {"standings": standings, "updated": now_local_iso()}
            )

            # --- Stats joueurs ---
            html_players = get_html(players_url)
            players = parse_players_stats(html_players)
            mqtt_publish(
                client, args.discovery_prefix, slug, "slqne_stats_joueurs", "mdi:hockey-sticks",
                f"{len(players)} joueurs",
                {"players": players, "updated": now_local_iso()}
            )

        except Exception as e:
            print(f"[ERREUR] {name}: {e}")

    print("[INFO] Tous les teams traités.")
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
