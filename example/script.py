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
# 🧠 Parsing standings et stats joueurs
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
    try:
        container = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ul.list-unstyled"))
        )
        last_height = 0
        same_count = 0
        for i in range(10):  # max 10 scrolls
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", container)
            time.sleep(1.5)
            new_height = driver.execute_script("return arguments[0].scrollHeight;", container)
            lis = container.find_elements(By.CSS_SELECTOR, "li[data-event='true']")
            print(f"[DEBUG] Scroll {i+1}: {len(lis)} matchs chargés, hauteur={new_height}")
            if new_height == last_height:
                same_count += 1
                if same_count >= 2:
                    print("[DEBUG] Fin du scroll : plus de nouveaux matchs chargés.")
                    break
            else:
                same_count = 0
            last_height = new_height
    except Exception as e:
        print(f"[WARN] Impossible de scroller pour charger tous les matchs: {e}")

# ===============================================================
# 🧭 Lecture interactive du calendrier (30 derniers jours)
# ===============================================================
def get_schedule_html_interactive(url: str) -> str:
    print(f"[INFO] Ouverture interactive de {url}")
    driver = setup_driver()
    driver.get(url)

    try:
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1.5)

        btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-outline-primary"))
        )
        print(f"[DEBUG] Texte du bouton calendrier initial: {btn.text.strip()}")
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(1)

        dropdown = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.dropdown-menu.show"))
        )

        items = dropdown.find_elements(By.CSS_SELECTOR, "li.list-group-item, li.list-group-item-action")
        for item in items:
            txt = item.text.strip().lower()
            if "30 derniers jours" in txt:
                driver.execute_script("arguments[0].scrollIntoView(true);", item)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", item)
                print("[DEBUG] → Option '30 derniers jours' cliquée dans le menu déroulant.")
                break

        # Attendre le calendrier actif
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#date-picker [data-in-range='true']"))
            )
            print("[DEBUG] → Le calendrier montre bien la plage de dates sélectionnée.")
        except Exception:
            print("[WARN] Aucun jour marqué 'in-range' détecté après la sélection.")

        # Clic sur "Appliquer"
        try:
            apply_button = dropdown.find_element(By.CSS_SELECTOR, "footer button.btn.btn-primary")
            driver.execute_script("arguments[0].scrollIntoView(true);", apply_button)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", apply_button)
            print("[DEBUG] → Bouton 'Appliquer' cliqué avec succès.")
        except Exception as e:
            print(f"[WARN] Impossible de cliquer sur 'Appliquer': {e}")

        # Scroll pour charger tous les matchs
        scroll_to_load_all_matches(driver)

    except Exception as e:
        print(f"[WARN] Interaction dropdown échouée : {e}")

    html = driver.page_source
    driver.quit()
    print(f"[DEBUG] Taille du HTML (calendrier après sélection + Appliquer): {len(html)} caractères")
    return html

# ===============================================================
# 🏒 Parsing du calendrier (structure “cards”)
# ===============================================================
def get_last_game_from_schedule(league_id: str, schedule_id: str, team_name: str) -> Optional[Dict]:
    base_url = "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings"
    url_schedule = f"{base_url}/{league_id}?tab=schedule&scheduleId={schedule_id}"
    print(f"[INFO] Lecture du calendrier (structure cards) de {team_name}: {url_schedule}")

    html = get_schedule_html_interactive(url_schedule)
    soup = BeautifulSoup(html, "html.parser")

    def clean_text(txt):
        txt = ''.join(c for c in unicodedata.normalize('NFD', txt) if unicodedata.category(c) != 'Mn')
        txt = txt.lower()
        txt = re.sub(r'[^a-z0-9]', '', txt)
        return txt

    normalized_team = clean_text(team_name)
    all_events = []

    for date_section in soup.select("li[data-date-section]"):
        date_title = date_section.find("h4")
        date_text = date_title.get_text(strip=True) if date_title else ""

        for event in date_section.select("li[data-event='true'] article[itemtype='https://schema.org/SportsEvent']"):
            teams = [t.get_text(strip=True) for t in event.select("article[itemtype='https://schema.org/SportsTeam'] h5 a")]
            scores = [s.get_text(strip=True) for s in event.select(".font-brand.font-size-lg")]
            location = event.find("a", href=re.compile("maps/search"))
            arena = location.get_text(strip=True) if location else ""
            final = "FINAL" in event.get_text()

            print(f"[DEBUG] Match détecté: {date_text} | {teams} | scores={scores} | arena={arena} | final={final}")

            if not teams or len(scores) < 2 or not final:
                continue

            joined = clean_text("".join(teams))
            match = {
                "date": date_text,
                "home": teams[-1],
                "visitor": teams[0],
                "score_home": scores[-1],
                "score_visitor": scores[0],
                "arena": arena,
                "raw": " | ".join(teams) + " : " + " - ".join(scores),
                "match_involving_team": normalized_team in joined
            }

            print(f"[DEBUG] → Comparaison équipe: '{normalized_team}' in '{joined}' = {match['match_involving_team']}")
            all_events.append(match)

    print(f"[DEBUG] Total {len(all_events)} matchs détectés au total sur la page.")
    team_events = [m for m in all_events if m["match_involving_team"]]

    if not team_events:
        print(f"[INFO] Aucun match joué trouvé pour {team_name}")
        return None

    def parse_date(txt):
        mois = {"janv":1,"févr":2,"mars":3,"avr":4,"mai":5,"juin":6,"juil":7,"août":8,"sept":9,"oct":10,"nov":11,"déc":12}
        m = re.search(r"(\d{1,2}) (\w+)", txt)
        if not m:
            return datetime.min
        jour = int(m.group(1))
        mois_txt = m.group(2).lower()[:4]
        mois_num = mois.get(mois_txt, 1)
        return datetime(datetime.now().year, mois_num, jour)

    team_events.sort(key=lambda e: parse_date(e["date"]), reverse=True)
    last = team_events[0]
    score_str = f"{last['score_home']}-{last['score_visitor']}"
    print(f"[DEBUG] ✅ Dernier match trouvé pour {team_name}: {last['visitor']} vs {last['home']} ({score_str})")
    return {
        "date": last["date"],
        "home": last["home"],
        "visitor": last["visitor"],
        "score": score_str,
        "arena": last["arena"],
        "raw": last["raw"]
    }

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
            # Classement
            url_standings = f"{base_url}/{league_id}?tab=standings&scheduleId={schedule_id}"
            html_standings = get_html_selenium(url_standings)
            standings = parse_standings_multi_division(html_standings)

            mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug,
                         "classement", "mdi:trophy",
                         f"{len(standings)} équipes",
                         {"standings": standings, "updated": now_local_iso()})

            # Stats joueurs
            url_players = f"{base_url}/{league_id}?tab=playerstats&scheduleId={schedule_id}"
            html_players = get_html_selenium(url_players)
            players_stats = parse_table_generic(html_players)

            mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug,
                         "stats_joueurs", "mdi:hockey-sticks",
                         f"{len(players_stats)} joueurs",
                         {"players": players_stats, "updated": now_local_iso()})

            # Dernier match
            last_game = get_last_game_from_schedule(league_id, schedule_id, name)
            if last_game:
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug,
                             "dernier_match", "mdi:hockey-puck",
                             last_game.get("score", "N/A"),
                             {"last_game": last_game, "updated": now_local_iso()})

        except Exception as e:
            print(f"[ERREUR] {name}: {e}")

    print("[INFO] Tous les teams traités.")
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
