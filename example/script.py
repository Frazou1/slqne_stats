#!/usr/bin/env python3
import os, re, json, time, argparse, unicodedata, urllib.parse
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

LOCAL_TZ = "America/Toronto"
DEFAULT_BASE_URL = "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings"

# ===============================================================
# 🔧 Utils & Parsing d'URL
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

def clean_name(name: str) -> str:
    """Nettoyage et suppression d'une lettre initiale doublée."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9\s]", "", s)
    s = s.strip()
    if len(s) > 1 and s[0] == s[1]:
        s = s[1:]
    return s

def parse_spordle_url(spordle_url: Optional[str], default_league_id: Optional[str] = None, default_schedule_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str], str]:
    """
    Extrait (league_id, schedule_id, base_url) depuis l'URL Spordle / RSEQ.
    
    Exemples gérés :
      - https://page.spordle.com/lhqca/schedule-stats-standings/c43095cf-c7e6-4562-994c-a71a9a0cbf3a
      - https://page.spordle.com/lhqca/teams/211183?tab=schedule
      - https://scolaire.rseqhockey.com/fr/teams/179927?organizationId=ae5bed83-a302-4ac5-927b-639d2c20a3c9
    """
    league_id = default_league_id
    schedule_id = default_schedule_id
    base_url = DEFAULT_BASE_URL

    if not spordle_url:
        return league_id, schedule_id, base_url

    parsed = urllib.parse.urlparse(spordle_url.strip())
    
    # 1. Reconstitution de l'URL de base (ex: https://page.spordle.com/lhqca/schedule-stats-standings)
    if parsed.scheme and parsed.netloc:
        path_parts = [p for p in parsed.path.split('/') if p]
        if path_parts:
            league_slug = path_parts[0] if path_parts[0] not in ['fr', 'en'] else (path_parts[1] if len(path_parts) > 1 else path_parts[0])
            base_url = f"{parsed.scheme}://{parsed.netloc}/{league_slug}/schedule-stats-standings"
        else:
            base_url = f"{parsed.scheme}://{parsed.netloc}/schedule-stats-standings"

    # 2. Extraction du league_id (UUID d'organisation)
    query_params = urllib.parse.parse_qs(parsed.query)
    if 'organizationId' in query_params:
        league_id = query_params['organizationId'][0]
    else:
        uuid_match = re.search(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', parsed.path, re.IGNORECASE)
        if uuid_match:
            league_id = uuid_match.group(0)

    # 3. Extraction du schedule_id (chiffres d'équipe ou de calendrier)
    path_segments = [seg for seg in parsed.path.split('/') if seg]
    for seg in reversed(path_segments):
        if seg.isdigit():
            schedule_id = seg
            break

    return league_id, schedule_id, base_url

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
                if "Nom" in row:
                    row["Nom"] = clean_name(row.get("Nom", ""))
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
            row = dict(zip(headers, tds))
            if "Nom" in row:
                row["Nom"] = clean_name(row.get("Nom", ""))
            rows.append(row)
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
def get_games_from_schedule(league_id: str, schedule_id: str, team_name: str, base_url: str = DEFAULT_BASE_URL, periode="30 derniers jours"):
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
            print(f"    → {p.get('player_name','?')} ({p.get('team_name','?')})")

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
            player_name = clean_name(player_name)
            slug = slugify(player_name)

            print(f"[INFO] --- Publication joueur {player_name} ({team_name}) ---")

            team_info = next((t for t in teams if normalize(t.get("name")) == normalize(team_name)), {})

            # Résolution des IDs + URL (soit au niveau joueur, soit hérité de l'équipe)
            raw_url = player.get("spordle_url") or team_info.get("spordle_url")
            raw_league = player.get("league_id") or player.get("league_uuid") or player.get("leagueId") or team_info.get("league_id")
            raw_schedule = player.get("schedule_id") or player.get("scheduleId") or team_info.get("schedule_id")

            league_id, schedule_id, base_url = parse_spordle_url(raw_url, raw_league, raw_schedule)

            if not league_id or not schedule_id:
                print(f"[WARN] IDs ou URL manquants pour {player_name}. Saut.")
                continue

            print(f"[CTX] {player_name} → league_id={league_id} schedule_id={schedule_id} base_url={base_url}")

            try:
                html_standings = get_html_selenium(f"{base_url}/{league_id}?tab=standings&scheduleId={schedule_id}")
                standings = parse_standings_multi_division(html_standings)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "classement", "mdi:trophy",
                             f"{len(standings)} équipes", {"standings": standings, "updated": now_local_iso()})

                html_players = get_html_selenium(f"{base_url}/{league_id}?tab=playerstats&scheduleId={schedule_id}")
                players_stats = parse_table_generic(html_players)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "stats_joueurs", "mdi:hockey-sticks",
                             f"{len(players_stats)} joueurs", {"players": players_stats, "updated": now_local_iso()})

                matchs_passes = get_games_from_schedule(league_id, schedule_id, team_name, base_url=base_url, periode="30 derniers jours")
                if matchs_passes:
                    last = matchs_passes[-1]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "dernier_match", "mdi:hockey-puck",
                                 f"{last['score_home']}-{last['score_visitor']}",
                                 {"match": last, "updated": now_local_iso()})

                matchs_futurs = get_games_from_schedule(league_id, schedule_id, team_name, base_url=base_url, periode="30 prochains jours")
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
            raw_url = team.get("spordle_url")
            raw_league = team.get("league_id")
            raw_schedule = team.get("schedule_id")

            league_id, schedule_id, base_url = parse_spordle_url(raw_url, raw_league, raw_schedule)

            if not league_id or not schedule_id:
                print(f"[WARN] IDs ou URL manquants pour l'équipe {name}. Saut.")
                continue

            slug = slugify(name)
            print(f"[INFO] --- Traitement {name} (league_id={league_id}, schedule_id={schedule_id}) ---")

            try:
                html_standings = get_html_selenium(f"{base_url}/{league_id}?tab=standings&scheduleId={schedule_id}")
                standings = parse_standings_multi_division(html_standings)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "classement", "mdi:trophy",
                             f"{len(standings)} équipes", {"standings": standings, "updated": now_local_iso()})

                html_players = get_html_selenium(f"{base_url}/{league_id}?tab=playerstats&scheduleId={schedule_id}")
                players_stats = parse_table_generic(html_players)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "stats_joueurs", "mdi:hockey-sticks",
                             f"{len(players_stats)} joueurs", {"players": players_stats, "updated": now_local_iso()})

                matchs_passes = get_games_from_schedule(league_id, schedule_id, name, base_url=base_url, periode="30 derniers jours")
                if matchs_passes:
                    last = matchs_passes[-1]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "dernier_match", "mdi:hockey-puck",
                                 f"{last['score_home']}-{last['score_visitor']}",
                                 {"match": last, "updated": now_local_iso()})

                matchs_futurs = get_games_from_schedule(league_id, schedule_id, name, base_url=base_url, periode="30 prochains jours")
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
