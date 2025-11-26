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

def normalize(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", s.lower())

def setup_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(options=opts)

def get_html_selenium(url: str) -> str:
    print(f"[INFO] Ouverture de {url}")
    driver = setup_driver()
    driver.get(url)
    time.sleep(15)
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
# 🔄 Scroll global pour charger tous les matchs Spordle
# ===============================================================
def scroll_to_load_all_matches(driver):
    try:
        last_total = 0
        same_count = 0
        for i in range(25):
            driver.execute_script("window.scrollBy(0, window.innerHeight);")
            time.sleep(1.6)
            driver.execute_script("window.scrollBy(0, -150);")
            time.sleep(1.2)

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
        print(f"[WARN] Scroll erreur: {e}")

# ===============================================================
# 🧭 Lecture interactive du calendrier
# ===============================================================
def get_schedule_html_interactive(url: str, filtre="30 derniers jours") -> str:
    print(f"[INFO] Ouverture interactive de {url}")
    driver = setup_driver()
    driver.get(url)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(3.0)

    try:
        btn = WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button.btn-outline-primary"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", btn)
        driver.execute_script("arguments[0].click();", btn)
        print(f"[DEBUG] Bouton calendrier cliqué par JS: {btn.text.strip() if btn.text else 'Chargement...'}")

        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.dropdown-menu.show"))
        )
        print("[DEBUG] Menu déroulant du calendrier ouvert.")
        time.sleep(0.8)

        dropdown = driver.find_element(By.CSS_SELECTOR, "div.dropdown-menu.show")
        items = dropdown.find_elements(By.CSS_SELECTOR, "li.list-group-item, li.list-group-item-action")
        for item in items:
            txt = item.text.strip().lower()
            if filtre in txt:
                driver.execute_script("arguments[0].scrollIntoView(true);", item)
                driver.execute_script("arguments[0].click();", item)
                print(f"[DEBUG] → Option '{filtre}' sélectionnée.")
                break

        time.sleep(2.0)
        try:
            apply_button = dropdown.find_element(By.CSS_SELECTOR, "footer button.btn.btn-primary")
            driver.execute_script("arguments[0].scrollIntoView(true);", apply_button)
            driver.execute_script("arguments[0].click();", apply_button)
            print("[DEBUG] → Bouton 'Appliquer' cliqué.")
        except Exception as e:
            print(f"[WARN] Impossible de cliquer sur 'Appliquer': {e}")

        time.sleep(2.0)
        scroll_to_load_all_matches(driver)

    except Exception as e:
        print(f"[WARN] Interaction dropdown échouée : {e}")

    time.sleep(1.0)
    html = driver.page_source
    driver.quit()
    print(f"[DEBUG] Taille du HTML après sélection: {len(html)} caractères")
    return html

# ===============================================================
# 🏒 Extraction des matchs et filtrage dernier / prochain
# ===============================================================
def get_games_from_schedule(league_id: str, schedule_id: str, team_name: str, periode="30 derniers jours"):
    base_url = "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings"
    url_schedule = f"{base_url}/{league_id}?tab=schedule&scheduleId={schedule_id}"
    html = get_schedule_html_interactive(url_schedule, filtre=periode)
    soup = BeautifulSoup(html, "html.parser")
    
    normalized_team = normalize(team_name)
    all_matches = []

    for date_section in soup.select("li[data-date-section]"):
        date_title = date_section.find("h4")
        date_text = date_title.get_text(strip=True) if date_title else ""
        for event in date_section.select("li[data-event='true'] article[itemtype='https://schema.org/SportsEvent']"):
            teams = [t.get_text(strip=True) for t in event.select("article[itemtype='https://schema.org/SportsTeam'] h5 a")]
            scores = [s.get_text(strip=True) for s in event.select(".font-brand.font-size-lg")]
            final = "FINAL" in event.get_text()
            arena_el = event.find("a", href=re.compile("maps/search"))
            arena = arena_el.get_text(strip=True) if arena_el else ""
            print(f"[DEBUG] Match détecté: {date_text} | {teams} | scores={scores} | final={final}")

            if not teams:
                continue

            joined = normalize("".join(teams))
            involving_team = normalized_team in joined
            if not involving_team:
                continue

            match = {
                "date": date_text,
                "home": teams[-1],
                "visitor": teams[0],
                "arena": arena,
                "score_home": scores[-1] if len(scores) >= 2 else "",
                "score_visitor": scores[0] if len(scores) >= 2 else "",
                "final": final,
            }
            all_matches.append(match)

    print(f"[DEBUG] Total {len(all_matches)} matchs trouvés pour {team_name}.")
    return all_matches

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

    if players:
        for player in players:
            player_name = player.get("player_name", "").strip()
            team_name = player.get("team_name", "").strip()
            slug = slugify(player_name)
            print(f"[INFO] --- Publication joueur {player_name} ({team_name}) ---")

            team_info = next((t for t in teams if normalize(t.get("name")) == normalize(team_name)), None)

            player_league_id = player.get("league_id") or player.get("league_uuid") or player.get("leagueId") or player.get("league")
            player_schedule_id = player.get("schedule_id") or player.get("scheduleId") or player.get("schedule")

            if not team_info and not (player_league_id and player_schedule_id):
                print(f"[WARN] Aucune équipe trouvée pour {team_name} et aucun ID propre au joueur.")
                continue

            league_id = player_league_id or (team_info.get("league_id") if team_info else None)
            schedule_id = player_schedule_id or (team_info.get("schedule_id") if team_info else None)

            if not league_id or not schedule_id:
                print(f"[WARN] IDs manquants pour {player_name}. Saut.")
                continue

            src = "player" if (player_league_id or player_schedule_id) else "team_map"
            print(f"[CTX] {player_name} → league_id={league_id} schedule_id={schedule_id} (src={src})")

            try:
                base_url = "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings"
                html_standings = get_html_selenium(f"{base_url}/{league_id}?tab=standings&scheduleId={schedule_id}")
                standings = parse_standings_multi_division(html_standings)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "classement", "mdi:trophy",
                             f"{len(standings)} équipes", {"standings": standings, "updated": now_local_iso()})

                html_players = get_html_selenium(f"{base_url}/{league_id}?tab=playerstats&scheduleId={schedule_id}")
                players_stats = parse_table_generic(html_players)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "stats_joueurs", "mdi:hockey-sticks",
                             f"{len(players_stats)} joueurs", {"players": players_stats, "updated": now_local_iso()})

                matchs_passes = get_games_from_schedule(league_id, schedule_id, team_name, "30 derniers jours")
                if matchs_passes:
                    last = matchs_passes[-1]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "dernier_match", "mdi:hockey-puck",
                                 f"{last['score_home']}-{last['score_visitor']}",
                                 {"match": last, "updated": now_local_iso()})

                matchs_futurs = get_games_from_schedule(league_id, schedule_id, team_name, "30 prochains jours")
                if matchs_futurs:
                    next_match = matchs_futurs[0]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "prochain_match", "mdi:calendar-clock",
                                 f"{next_match['visitor']} vs {next_match['home']}",
                                 {"match": next_match, "updated": now_local_iso()})
            except Exception as e:
                print(f"[ERREUR] {player_name}: {e}")
    else:
        for team in teams:
            name = team.get("name")
            league_id = team.get("league_id")
            schedule_id = team.get("schedule_id")
            slug = slugify(name)
            print(f"[INFO] --- Traitement {name} ---")

            try:
                base_url = "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings"
                html_standings = get_html_selenium(f"{base_url}/{league_id}?tab=standings&scheduleId={schedule_id}")
                standings = parse_standings_multi_division(html_standings)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "classement", "mdi:trophy",
                             f"{len(standings)} équipes", {"standings": standings, "updated": now_local_iso()})

                html_players = get_html_selenium(f"{base_url}/{league_id}?tab=playerstats&scheduleId={schedule_id}")
                players_stats = parse_table_generic(html_players)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "stats_joueurs", "mdi:hockey-sticks",
                             f"{len(players_stats)} joueurs", {"players": players_stats, "updated": now_local_iso()})

                matchs_passes = get_games_from_schedule(league_id, schedule_id, name, "30 derniers jours")
                if matchs_passes:
                    last = matchs_passes[-1]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "dernier_match", "mdi:hockey-puck",
                                 f"{last['score_home']}-{last['score_visitor']}",
                                 {"match": last, "updated": now_local_iso()})

                matchs_futurs = get_games_from_schedule(league_id, schedule_id, name, "30 prochains jours")
                if matchs_futurs:
                    next_match = matchs_futurs[0]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "prochain_match", "mdi:calendar-clock",
                                 f"{next_match['visitor']} vs {next_match['home']}",
                                 {"match": next_match, "updated": now_local_iso()})
            except Exception as e:
                print(f"[ERREUR] {name}: {e}")

    print("[INFO] Tous les sensors publiés.")
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
