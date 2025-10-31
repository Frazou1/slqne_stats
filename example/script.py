#!/usr/bin/env python3
import os, re, json, time, argparse, unicodedata
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
# 🧠 Parsing standings, logos et stats joueurs
# ===============================================================
def parse_standings_multi_division(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    all_rows, seen_teams = [], set()
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

        print(f"[DEBUG] {len(rows)} lignes extraites pour {division_name}")
        all_rows.extend(rows)

    print(f"[DEBUG] Total {len(all_rows)} lignes multi-division uniques extraites")
    return all_rows


def parse_logos_from_standings(html: str) -> Dict[str, str]:
    """🆕 Extrait les logos et noms d’équipes du classement."""
    soup = BeautifulSoup(html, "html.parser")
    logos = {}
    for row in soup.select("tr"):
        team = row.select_one("td:nth-child(2)")
        logo = row.select_one("img")
        if team and logo and team.text.strip():
            logos[team.text.strip()] = logo.get("src")
    print(f"[DEBUG] {len(logos)} logos d’équipes extraits")
    return logos


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

# ===============================================================
# 🔄 Scroll complet pour charger tous les matchs
# ===============================================================
def scroll_to_load_all_matches(driver):
    """
    Fait défiler toute la page Spordle (et non seulement la liste UL)
    pour forcer le chargement dynamique de tous les matchs.
    """
    try:
        last_total = 0
        same_count = 0
        for i in range(12):  # jusqu’à 12 cycles de scroll complets
            driver.execute_script("window.scrollBy(0, window.innerHeight);")
            time.sleep(1.2)
            driver.execute_script("window.scrollBy(0, -200);")
            time.sleep(1)

            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            matches = soup.select("li[data-event='true']")
            total = len(matches)
            print(f"[DEBUG] Scroll global {i+1}: {total} matchs visibles...")

            if total == last_total:
                same_count += 1
                if same_count >= 3:
                    print("[DEBUG] Fin du scroll : plus de nouveaux matchs détectés.")
                    break
            else:
                same_count = 0
            last_total = total
    except Exception as e:
        print(f"[WARN] Impossible de scroller pour charger tous les matchs: {e}")


# ===============================================================
# 🚀 MQTT + MAIN
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
    players = json.loads(args.players_json) if args.players_json else []

    if players:
        print(f"[INFO] {len(players)} joueur(s) suivis :")
        for p in players:
            print(f"   → {p.get('player_name','?')} ({p.get('team_name','?')})")

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
            # 🏆 CLASSEMENT
            url_standings = f"{base_url}/{league_id}?tab=standings&scheduleId={schedule_id}"
            html_standings = get_html_selenium(url_standings)
            standings = parse_standings_multi_division(html_standings)
            mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug,
                         "classement", "mdi:trophy",
                         f"{len(standings)} équipes",
                         {"standings": standings, "updated": now_local_iso()})

            # 🆕 LOGOS
            logos = parse_logos_from_standings(html_standings)
            mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug,
                         "logos_equipes", "mdi:image-outline",
                         f"{len(logos)} logos",
                         {"logos": logos, "updated": now_local_iso()})

        except Exception as e:
            print(f"[ERREUR] {name}: {e}")

    print("[INFO] Tous les teams traités.")
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
