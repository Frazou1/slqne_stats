#!/usr/bin/env python3
import os, re, json, time, argparse, unicodedata, urllib.parse
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
from zoneinfo import ZoneInfo

# REMPLACEMENT DES IMPORTS SELENIUM STANDARDS PAR SELENIUMBASE
from seleniumbase import Driver
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

UUID_RE = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', re.IGNORECASE)

def parse_spordle_url(spordle_url: Optional[str], default_league_id: Optional[str] = None, default_schedule_id: Optional[str] = None) -> Dict:
    ctx = {"site": None, "base_url": DEFAULT_BASE_URL, "league_id": default_league_id,
           "schedule_id": default_schedule_id, "team_id": None}

    if not spordle_url:
        return ctx

    parsed = urllib.parse.urlparse(spordle_url.strip())
    if not (parsed.scheme and parsed.netloc):
        return ctx

    path_parts = [p for p in parsed.path.split('/') if p and p not in ('fr', 'en')]
    site = f"{parsed.scheme}://{parsed.netloc}/fr"
    if parsed.netloc.endswith("page.spordle.com") and path_parts:
        site += f"/{path_parts.pop(0)}"
    ctx["site"] = site
    ctx["base_url"] = f"{site}/schedule-stats-standings"

    if len(path_parts) >= 2 and path_parts[0] == "teams" and path_parts[1].isdigit():
        ctx["team_id"] = path_parts[1]
        return ctx

    query_params = urllib.parse.parse_qs(parsed.query)
    if 'organizationId' in query_params:
        ctx["league_id"] = query_params['organizationId'][0]
    else:
        uuid_match = UUID_RE.search(parsed.path)
        if uuid_match:
            ctx["league_id"] = uuid_match.group(0)

    if 'scheduleId' in query_params:
        ctx["schedule_id"] = query_params['scheduleId'][0]
    else:
        for seg in reversed(path_parts):
            if seg.isdigit():
                ctx["schedule_id"] = seg
                break

    return ctx

def resolve_team_page(ctx: Dict) -> Dict:
    """Pour une URL de page d'équipe : lit la catégorie et le nom réel de l'équipe."""
    driver = setup_driver()
    try:
        url = f"{ctx['site']}/teams/{ctx['team_id']}"
        print(f"[INFO] Lecture de la page d'équipe {url}")
        
        # Utilisation de la méthode uc_open de SeleniumBase au lieu de get() pour une connexion furtive initiale
        driver.uc_open(url)
        
        WebDriverWait(driver, 40).until(lambda d: d.execute_script(
            "return !!document.getElementById('__NEXT_DATA__')"))
        team = driver.execute_script(
            "return JSON.parse(document.getElementById('__NEXT_DATA__').textContent).props.pageProps.team || null")
        if not team:
            print("[WARN] Données d'équipe introuvables dans la page.")
            return ctx

        ctx["league_id"] = ctx.get("league_id") or team.get("categoryId")
        ctx["site_team_name"] = team.get("shortName") or team.get("name")
        print(f"[DEBUG] Équipe '{ctx['site_team_name']}' → catégorie {ctx['league_id']}")

        if not ctx.get("schedule_id") and ctx.get("league_id"):
            ctx["schedule_id"] = find_schedule_id(driver, f"{ctx['base_url']}/{ctx['league_id']}?tab=playerstats")
    except Exception as e:
        print(f"[WARN] Résolution de la page d'équipe échouée : {e}")
    finally:
        driver.quit()
    return ctx

def find_schedule_id(driver, url: str) -> Optional[str]:
    """Ouvre la liste 'Sélectionner un horaire' et choisit la saison régulière."""
    driver.uc_open(url)
    combo = WebDriverWait(driver, 40).until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "input[aria-label='Sélectionner un horaire']")))
    combo.click()
    options = WebDriverWait(driver, 15).until(
        lambda d: d.find_elements(By.CSS_SELECTOR, "[role='option']"))
    choice = next((o for o in options if "régulière" in o.text.lower()), options[0])
    print(f"[DEBUG] Horaire choisi : {choice.text.strip().splitlines()[0] if choice.text.strip() else '?'}")
    choice.click()
    WebDriverWait(driver, 15).until(lambda d: "scheduleId=" in d.current_url)
    schedule_id = urllib.parse.parse_qs(urllib.parse.urlparse(driver.current_url).query)["scheduleId"][0]
    print(f"[DEBUG] scheduleId = {schedule_id}")
    return schedule_id

def resolve_context(raw_url: Optional[str], raw_league: Optional[str], raw_schedule: Optional[str]) -> Dict:
    ctx = parse_spordle_url(raw_url, raw_league, raw_schedule)
    if ctx.get("team_id"):
        ctx = resolve_team_page(ctx)
    return ctx

# 🔧 INITIALISATION DU DRIVER MODIFIÉE POUR SELENIUMBASE UC MODE
def setup_driver():
    """Initialise un driver Chromium furtif indétectable par Cloudflare."""
    # uc=True active le mode indétectable
    # headless2=True applique le nouveau mode headless de Chrome (indispensable pour contourner Cloudflare sans interface)
    return Driver(uc=True, headless2=True, no_sandbox=True, disable_gpu=True)

def get_html_selenium(url: str) -> str:
    print(f"[INFO] Ouverture de {url}")
    driver = setup_driver()
    try:
        driver.uc_open(url)
        # Un délai de sécurité plus court peut suffire avec UC mode, ajustez si nécessaire
        time.sleep(10) 
        html = driver.page_source
        print(f"[DEBUG] Taille du HTML ({url.split('?tab=')[-1]}): {len(html)} caractères")
        return html
    finally:
        driver.quit()

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
    print(f"[DEBUG] {len(tables)} tables trouvées")
    # ... Reste de votre logique de parsing
