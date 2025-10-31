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
    """Parse les standings Spordle avec plusieurs divisions, incluant le logo et le lien de chaque équipe."""
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
            tds = tr.find_all("td")
            if not tds or len(tds) < len(headers):
                continue

            row = dict(zip(headers, [td.get_text(strip=True) for td in tds]))
            row["division"] = division_name

            # --- Extraction logo + lien d’équipe ---
            team_cell = None
            for td in tds:
                if td.find("a", href=True):
                    team_cell = td
                    break

            if team_cell:
                a = team_cell.find("a", href=True)
                img = a.find("img") if a else None
                team_url = a["href"] if a else ""
                team_logo = img["src"] if img and img.has_attr("src") else ""
                team_name = a.get_text(strip=True)

                # Correction du nom
                row["Équipe"] = team_name
                row["team_url"] = f"https://page.spordle.com{team_url}" if team_url.startswith("/") else team_url
                row["team_logo"] = team_logo

            # Évite doublons
            team_name_key = row.get("Équipe") or row.get("Equipe") or ""
            if team_name_key and team_name_key not in seen_teams:
                seen_teams.add(team_name_key)
                rows.append(row)

        # Ignore les grands tableaux combinés
        if len(rows) > 15:
            print(f"[DEBUG] Table {i} ignorée ({len(rows)} lignes, probable tableau global).")
            continue

        print(f"[DEBUG] {len(rows)} lignes extraites pour {division_name}")
        all_rows.extend(rows)

    print(f"[DEBUG] Total {len(all_rows)} lignes multi-division uniques extraites (avec logos).")
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

def detect_last_game(html: str) -> Optional[Dict]:
    soup = BeautifulSoup(html, "html.parser")
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
    print("[WARN] Aucun dernier match détecté dans le HTML.")
    return None

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
            url_standings = f"{base_url}/{league_id}?tab=standings&scheduleId={schedule_id}"
            html_standings = get_html_selenium(url_standings)
            standings = parse_standings_multi_division(html_standings)

            mqtt_publish(
                client, args.discovery_prefix, args.entity_prefix, slug,
                "classement", "mdi:trophy",
                f"{len(standings)} équipes",
                {"standings": standings, "updated": now_local_iso()}
            )

            url_players = f"{base_url}/{league_id}?tab=playerstats&scheduleId={schedule_id}"
            html_players = get_html_selenium(url_players)
            players = parse_table_generic(html_players)

            mqtt_publish(
                client, args.discovery_prefix, args.entity_prefix, slug,
                "stats_joueurs", "mdi:hockey-sticks",
                f"{len(players)} joueurs",
                {"players": players, "updated": now_local_iso()}
            )

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
