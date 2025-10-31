#!/usr/bin/env python3
import os, re, json, time, argparse
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

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
    driver.quit()
    print(f"[DEBUG] Taille du HTML ({url.split('?tab=')[-1]}): {len(html)} caractères")
    return html

# ===============================================================
# 🧠 Parsing des sections
# ===============================================================
def parse_standings_multi_division(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    all_rows = []
    seen_teams = set()
    tables = soup.find_all("table")

    if not tables:
        print("[WARN] Aucune table trouvée dans le HTML.")
        return []

    print(f"[DEBUG] {len(tables)} tables trouvées dans la page standings")

    for i, table in enumerate(tables, start=1):
        division_name = "Division inconnue"
        prev = table.find_previous(string=re.compile(r"Division", re.I))
        if prev:
            division_name = prev.strip()

        headers = [th.get_text(strip=True) for th in table.select("thead th")]
        rows = []
        for tr in table.select("tbody tr"):
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) >= len(headers):
                row = dict(zip(headers, tds))
                row["division"] = division_name
                team_name = row.get("Équipe") or row.get("Equipe") or ""
                if team_name and team_name not in seen_teams:
                    rows.append(row)
                    seen_teams.add(team_name)

        if len(rows) > 15:
            print(f"[DEBUG] Table {i} ignorée ({len(rows)} lignes, probable tableau global).")
            continue

        all_rows.extend(rows)

    print(f"[DEBUG] Total {len(all_rows)} lignes multi-division uniques extraites")
    return all_rows


def parse_table_generic(html: str) -> List[Dict]:
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


def get_last_game_from_schedule(league_id: str, schedule_id: str, team_name: str) -> Optional[Dict]:
    """Récupère le dernier match complété (avec score) pour une équipe donnée."""
    base_url = "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings"
    url_schedule = f"{base_url}/{league_id}?tab=schedule&scheduleId={schedule_id}"
    print(f"[INFO] Lecture du calendrier de {team_name}: {url_schedule}")

    html = get_html_selenium(url_schedule)
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        print("[WARN] Aucun tableau de calendrier trouvé.")
        return None

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    rows = []
    for tr in table.select("tbody tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cols) >= len(headers):
            rows.append(dict(zip(headers, cols)))

    # 🔍 On garde seulement les matchs impliquant l'équipe
    filtered = [r for r in rows if team_name.lower() in " ".join(r.values()).lower()]
    if not filtered:
        print(f"[INFO] Aucun match trouvé pour {team_name}")
        return None

    # 🏁 Matchs terminés (avec score)
    played = [r for r in filtered if re.search(r"\d+-\d+", " ".join(r.values()))]
    if not played:
        print(f"[INFO] Aucun match terminé pour {team_name}")
        return None

    # 🗓️ Tri par date
    def parse_date(text):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return datetime.min

    played.sort(key=lambda x: parse_date(x.get("Date", "")), reverse=True)
    last = played[0]
    print(f"[DEBUG] Dernier match trouvé pour {team_name}: {last}")

    return {
        "date": last.get("Date", ""),
        "home": last.get("Local") or last.get("Home") or "",
        "visitor": last.get("Visiteur") or last.get("Visitor") or "",
        "score": re.search(r"\d+-\d+", " ".join(last.values())).group(0)
                  if re.search(r"\d+-\d+", " ".join(last.values())) else "",
        "raw": last
    }

# ===============================================================
# 🚀 MQTT
# ===============================================================
def mqtt_publish(client, discovery_prefix, entity_prefix, slug, label, icon, state, attributes):
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
    parser.add_argument("--players-json", default="")
    parser.add_argument("--entity_prefix", default="slqne")
    parser.add_argument("--mqtt_host", default="core-mosquitto")
    parser.add_argument("--mqtt_port", default="1883")
    parser.add_argument("--mqtt_user", default="")
    parser.add_argument("--mqtt_pass", default="")
    parser.add_argument("--discovery_prefix", default="homeassistant")
    args = parser.parse_args()

    teams = json.loads(args.teams_json) if args.teams_json else []
    players_followed = json.loads(args.players_json) if args.players_json else []

    if not teams:
        print("[ERREUR] Aucune équipe configurée.")
        return

    if players_followed:
        print(f"[INFO] {len(players_followed)} joueur(s) suivis :")
        for pj in players_followed:
            print(f"   → {pj['player_name']} ({pj['team_name']})")

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
            # --- Classement ---
            url_standings = f"{base_url}/{league_id}?tab=standings&scheduleId={schedule_id}"
            html_standings = get_html_selenium(url_standings)
            standings = parse_standings_multi_division(html_standings)
            mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug,
                         "classement", "mdi:trophy",
                         f"{len(standings)} équipes",
                         {"standings": standings, "updated": now_local_iso()})

            # --- Statistiques joueurs ---
            url_players = f"{base_url}/{league_id}?tab=playerstats&scheduleId={schedule_id}"
            html_players = get_html_selenium(url_players)
            players = parse_table_generic(html_players)

            filtered_players = []
            for pj in players_followed:
                if pj["team_name"].lower() == name.lower():
                    for pl in players:
                        nom_joueur = pl.get("Nom") or pl.get("Player") or ""
                        if pj["player_name"].lower() in nom_joueur.lower():
                            filtered_players.append(pl)

            mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug,
                         "stats_joueurs", "mdi:hockey-sticks",
                         f"{len(players)} joueurs",
                         {"players": players, "updated": now_local_iso()})

            if filtered_players:
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug,
                             "playerstats", "mdi:account",
                             f"{len(filtered_players)} joueur(s)",
                             {"players": filtered_players, "updated": now_local_iso()})

            # --- Dernier match à partir du calendrier ---
            last_game = get_last_game_from_schedule(league_id, schedule_id, name)
            if last_game:
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug,
                             "dernier_match", "mdi:hockey-puck",
                             last_game.get("score", "N/A"),
                             {"last_game": last_game, "updated": now_local_iso()})

                for pj in players_followed:
                    if pj["team_name"].lower() == name.lower():
                        mqtt_publish(client, args.discovery_prefix, args.entity_prefix,
                                     slugify(pj["player_name"]),
                                     "dernier_match", "mdi:hockey-puck",
                                     last_game.get("score", "N/A"),
                                     {"player": pj["player_name"], "last_game": last_game, "updated": now_local_iso()})

        except Exception as e:
            print(f"[ERREUR] {name}: {e}")

    print("[INFO] Tous les teams traités.")
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
