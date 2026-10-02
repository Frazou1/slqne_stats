#!/usr/bin/env python3
import os, re, json, time, argparse, unicodedata, urllib.parse
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
from zoneinfo import ZoneInfo

# IMPORTS SELENIUMBASE ET SELENIUM
from seleniumbase import Driver
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

def build_team_tab_url(spordle_team_url: str, tab: str) -> str:
    """
    Nettoie l'URL pour retirer les query params parasites (ex: organizationId)
    et applique uniquement ?tab=<tab>.
    Exemple:
    https://page.spordle.com/lhqca/teams/211183?organizationId=c43095cf...
    -> https://page.spordle.com/lhqca/teams/211183?tab=standings
    """
    if not spordle_team_url or not spordle_team_url.startswith("http"):
        return spordle_team_url

    parsed = urllib.parse.urlparse(spordle_team_url)
    # Reconstruit l'URL propre sans aucun query param original, en ajoutant uniquement tab
    new_query = urllib.parse.urlencode({"tab": tab})
    
    return urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        "",
        new_query,
        ""
    ))

def setup_driver():
    """Initialise un driver Chromium furtif indétectable et ultra-rapide."""
    chrome_args = "--disable-dev-shm-usage,--no-first-run,--disable-blink-features=AutomationControlled,--blink-settings=imagesEnabled=false"

    return Driver(
        uc=True,
        headless2=True,
        no_sandbox=True,
        disable_gpu=True,
        chromium_arg=chrome_args
    )

def get_html_selenium(url: str) -> str:
    print(f"[INFO] Ouverture de {url}", flush=True)
    driver = setup_driver()
    try:
        driver.uc_open(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)  # Attente du rendu dynamique Spordle/RSEQ
        html = driver.page_source
        print(f"[DEBUG] Taille du HTML: {len(html)} caractères", flush=True)
        return html
    except Exception as e:
        print(f"[ERREUR] Échec du chargement de {url}: {e}", flush=True)
        return ""
    finally:
        driver.quit()

# ===============================================================
# 🧠 Parsing standings et stats
# ===============================================================
def parse_standings_multi_division(html: str) -> List[Dict]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    all_rows, seen_teams = [], set()
    tables = soup.find_all("table")
    if not tables:
        print("[WARN] Aucune table trouvée dans le HTML.", flush=True)
        return []

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
            continue
        all_rows.extend(rows)
    return all_rows

def parse_table_generic(html: str) -> List[Dict]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        print("[WARN] Aucune table trouvée dans la page.", flush=True)
        return []
    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    rows = []
    for tr in table.select("tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) >= len(headers):
            rows.append(dict(zip(headers, tds)))
    return rows

# ===============================================================
# 🔄 Scroll global pour charger tous les matchs
# ===============================================================
def scroll_to_load_all_matches(driver):
    try:
        last_total = 0
        same_count = 0
        for i in range(15):
            driver.execute_script("window.scrollBy(0, window.innerHeight);")
            time.sleep(0.8)
            driver.execute_script("window.scrollBy(0, -150);")
            time.sleep(0.5)

            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            matches = soup.select("li[data-event='true']")
            total = len(matches)

            if total == last_total:
                same_count += 1
                if same_count >= 2:
                    break
            else:
                same_count = 0
            last_total = total
    except Exception as e:
        print(f"[WARN] Scroll erreur: {e}", flush=True)

# ===============================================================
# 🧭 Lecture interactive du calendrier
# ===============================================================
def get_schedule_html_interactive(url: str, filtre="30 derniers jours") -> str:
    print(f"[INFO] Ouverture interactive de {url}", flush=True)
    driver = setup_driver()
    try:
        driver.uc_open(url)
        driver.execute_script("window.scrollTo(0, 0);")

        try:
            btn = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button.btn-outline-primary"))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            driver.execute_script("arguments[0].click();", btn)

            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.dropdown-menu.show"))
            )

            dropdown = driver.find_element(By.CSS_SELECTOR, "div.dropdown-menu.show")
            items = dropdown.find_elements(By.CSS_SELECTOR, "li.list-group-item, li.list-group-item-action")
            for item in items:
                txt = item.text.strip().lower()
                if filtre in txt:
                    driver.execute_script("arguments[0].scrollIntoView(true);", item)
                    driver.execute_script("arguments[0].click();", item)
                    break

            time.sleep(1.0)
            apply_button = dropdown.find_element(By.CSS_SELECTOR, "footer button.btn.btn-primary")
            driver.execute_script("arguments[0].scrollIntoView(true);", apply_button)
            driver.execute_script("arguments[0].click();", apply_button)
        except Exception as e:
            print(f"[DEBUG] Étape filtre non appliquée ou inutilisée : {e}", flush=True)

        time.sleep(1.5)
        scroll_to_load_all_matches(driver)
        return driver.page_source
    except Exception as e:
        print(f"[WARN] Chargement horaire échoué : {e}", flush=True)
        return driver.page_source if driver else ""
    finally:
        driver.quit()

# ===============================================================
# 🏒 Extraction des matchs
# ===============================================================
def get_games_from_schedule(spordle_team_url: str, team_name: str, periode="30 derniers jours"):
    url_schedule = build_team_tab_url(spordle_team_url, "schedule")
    html = get_schedule_html_interactive(url_schedule, filtre=periode)
    if not html:
        return []

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

            if not teams:
                continue

            joined = normalize("".join(teams))
            if normalized_team not in joined:
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
    print(f"[MQTT] Sensor publié: {sensor_id}", flush=True)

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
        print(f"[INFO] {len(players)} joueur(s) suivis :", flush=True)
        for p in players:
            print(f"   → {p.get('player_name','?')} ({p.get('team_name','?')})", flush=True)

    if not teams:
        print("[ERREUR] Aucune équipe configurée.", flush=True)
        return

    client = mqtt.Client(client_id=f"slqne_hockey_{int(time.time())}")
    if args.mqtt_user:
        client.username_pw_set(args.mqtt_user, args.mqtt_pass)
    client.connect(args.mqtt_host, int(args.mqtt_port), 60)
    client.loop_start()
    print("[INFO] Connecté à MQTT", flush=True)

    if players:
        for player in players:
            player_name = clean_name(player.get("player_name", "").strip())
            team_name = player.get("team_name", "").strip()
            slug = slugify(player_name)

            print(f"[INFO] --- Publication joueur {player_name} ({team_name}) ---", flush=True)

            team_info = next((t for t in teams if normalize(t.get("name")) in normalize(team_name) or normalize(team_name) in normalize(t.get("name"))), None)

            if not team_info:
                print(f"[WARN] Aucune URL d'équipe trouvée dans la config pour {team_name}.", flush=True)
                continue

            spordle_team_url = team_info.get("spordle_url", "")

            try:
                # 1. Classement
                url_standings = build_team_tab_url(spordle_team_url, "standings")
                html_standings = get_html_selenium(url_standings)
                standings = parse_standings_multi_division(html_standings)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "classement", "mdi:trophy",
                             f"{len(standings)} équipes", {"standings": standings, "updated": now_local_iso()})

                # 2. Stats Joueurs / Roster
                url_players = build_team_tab_url(spordle_team_url, "playerstats")
                html_players = get_html_selenium(url_players)
                players_stats = parse_table_generic(html_players)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "stats_joueurs", "mdi:hockey-sticks",
                             f"{len(players_stats)} joueurs", {"players": players_stats, "updated": now_local_iso()})

                # 3. Dernier Match
                matchs_passes = get_games_from_schedule(spordle_team_url, team_name, "30 derniers jours")
                if matchs_passes:
                    last = matchs_passes[-1]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "dernier_match", "mdi:hockey-puck",
                                 f"{last['score_home']}-{last['score_visitor']}",
                                 {"match": last, "updated": now_local_iso()})

                # 4. Prochain Match
                matchs_futurs = get_games_from_schedule(spordle_team_url, team_name, "30 prochains jours")
                if matchs_futurs:
                    next_match = matchs_futurs[0]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "prochain_match", "mdi:calendar-clock",
                                 f"{next_match['visitor']} vs {next_match['home']}",
                                 {"match": next_match, "updated": now_local_iso()})
            except Exception as e:
                print(f"[ERREUR] {player_name}: {e}", flush=True)
    else:
        for team in teams:
            name = team.get("name")
            spordle_team_url = team.get("spordle_url", "")
            slug = slugify(name)
            print(f"[INFO] --- Traitement {name} ---", flush=True)

            try:
                url_standings = build_team_tab_url(spordle_team_url, "standings")
                html_standings = get_html_selenium(url_standings)
                standings = parse_standings_multi_division(html_standings)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "classement", "mdi:trophy",
                             f"{len(standings)} équipes", {"standings": standings, "updated": now_local_iso()})

                url_players = build_team_tab_url(spordle_team_url, "playerstats")
                html_players = get_html_selenium(url_players)
                players_stats = parse_table_generic(html_players)
                mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "stats_joueurs", "mdi:hockey-sticks",
                             f"{len(players_stats)} joueurs", {"players": players_stats, "updated": now_local_iso()})

                matchs_passes = get_games_from_schedule(spordle_team_url, name, "30 derniers jours")
                if matchs_passes:
                    last = matchs_passes[-1]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "dernier_match", "mdi:hockey-puck",
                                 f"{last['score_home']}-{last['score_visitor']}",
                                 {"match": last, "updated": now_local_iso()})

                matchs_futurs = get_games_from_schedule(spordle_team_url, name, "30 prochains jours")
                if matchs_futurs:
                    next_match = matchs_futurs[0]
                    mqtt_publish(client, args.discovery_prefix, args.entity_prefix, slug, "prochain_match", "mdi:calendar-clock",
                                 f"{next_match['visitor']} vs {next_match['home']}",
                                 {"match": next_match, "updated": now_local_iso()})
            except Exception as e:
                print(f"[ERREUR] {name}: {e}", flush=True)

    print("[INFO] Tous les sensors publiés.", flush=True)
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
