import argparse
import json
import os
import platform
import re
import time
import urllib.parse
import requests

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ============================================================
# CONFIGURACIÓN
# ============================================================
BASE_URL = "https://online-fix.me"
OUTPUT_FILE = os.path.join("public", "onlinefix-fixes.json")

def clean_title(title: str) -> str:
    """Limpia el título eliminando coletillas de Online-Fix."""
    patterns = [
        r"\s+Online$", r"\s+по сети$", r"\s+Free Download$", r"\s+[\-\–\|]\s*$",
    ]
    new_title = title or ""
    for pattern in patterns:
        new_title = re.sub(pattern, "", new_title, flags=re.IGNORECASE).strip()
    return new_title

def get_steam_metadata(game_title: str, existing_appid=None, existing_img=None):
    """
    Busca metadatos SOLO si no existen ya. 
    NUNCA devuelve None si ya había un valor previo.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    appid = existing_appid
    img = existing_img
    
    try:
        # 1. BUSCAR APPID (Solo si no hay uno manual)
        if appid is None:
            query = urllib.parse.quote(game_title)
            search_url = f"https://store.steampowered.com/api/storesearch/?term={query}&l=spanish&cc=ES"
            res = requests.get(search_url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("total", 0) > 0:
                    appid = data["items"][0]["id"]
        
        # 2. BUSCAR IMAGEN (Solo si no hay una manual/previa)
        if appid is not None and img is None:
            time.sleep(0.6)
            details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=spanish"
            res = requests.get(details_url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get(str(appid), {}).get("success"):
                    img = data[str(appid)]["data"].get("header_image")
                    
    except Exception as e:
        print(f"    [!] Error en API Steam: {e}")
    
    # CRÍTICO: Si no encontró nada nuevo, devuelve lo que ya había (no borra)
    return appid, img

def _find_brave_binary() -> str | None:
    env_path = os.environ.get("BRAVE_PATH")
    if env_path and os.path.exists(env_path): return env_path
    system = platform.system()
    if system == "Windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ]
        for c in candidates:
            if os.path.exists(c): return c
    else:
        for c in ["/usr/bin/brave-browser", "/usr/bin/brave", "/snap/bin/brave"]:
            if os.path.exists(c): return c
    return None

def get_driver():
    options = Options()
    
    # 1. Configurar ruta de Brave (Brave mantiene su AdBlock nativo)
    options.binary_location = _find_brave_binary()
    
    # 2. Configuración para entornos Headless / Contenedores
    if platform.system() != "Windows" and os.environ.get("HEADLESS", "1") != "0":
        options.add_argument("--headless=new")
    else:
        # En tu Windows local, forzamos headless para evitar conflictos de ventanas con Docker
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})

    # 3. Detectar de forma inteligente si hay un servidor de Selenium (Docker o Actions)
    # En Actions usará 'SELENIUM_URL'. Si estás en local y no encuentra la variable, usará el puerto por defecto de tu Docker.
    selenium_url = os.environ.get("SELENIUM_URL", "http://localhost:4444/wd/hub")

    print(f"[*] Conectando mediante Selenium Remote a: {selenium_url}")
    try:
        return webdriver.Remote(
            command_executor=selenium_url,
            options=options
        )
    except Exception as e:
        # Si por algún motivo falla el remote en tu local (ej. Docker apagado), intenta fallback local
        print(f"[!] Falló la conexión remota ({e}). Intentando levantar Chrome/Brave local...")
        return webdriver.Chrome(options=options)

def scrape_game(driver, game_url, raw_title):
    game_title = clean_title(raw_title)
    print(f"\n[*] Analizando: {game_title}")
    driver.get(game_url)
    time.sleep(4)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    link_tag = soup.find("a", href=lambda h: h and "hosters.online-fix.me" in h)
    if not link_tag: return None
    try:
        main_window = driver.current_window_handle
        wait = WebDriverWait(driver, 15)
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, f"//a[@href='{link_tag['href']}']")))
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(8)
        if len(driver.window_handles) > 1:
            for handle in driver.window_handles:
                if handle != main_window:
                    driver.switch_to.window(handle)
                    break
        
        # Extraer links
        soup_h = BeautifulSoup(driver.page_source, "html.parser")
        uris = []
        for opt in soup_h.find_all("div", class_="option"):
            if any(h in opt.get_text().lower() for h in ["rootz", "gofile"]):
                try:
                    links = json.loads(opt.get("data-links"))
                    for l in links:
                        name = l.get("file_name", "").lower()
                        if any(k in name for k in ["fix", "crack"]) and ".part" not in name:
                            if l["direct_link"] not in uris: uris.append(l["direct_link"])
                except: continue
        
        if uris:
            return {"title": game_title, "uploadDate": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "uris": uris}
    except Exception as e: print(f"    [-] Error: {e}")
    finally:
        for h in driver.window_handles:
            if h != main_window: driver.switch_to.window(h); driver.close()
        driver.switch_to.window(main_window)
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=1)
    args = parser.parse_args()

    os.makedirs("public", exist_ok=True)
    data_final = {"name": "OnlineFix Fixes", "downloads": []}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            try: data_final = json.load(f)
            except: pass

    driver = get_driver()
    games_to_scrape = []

    try:
        # FASE 1: LISTAR URLS
        for p in range(args.start, args.end + 1):
            driver.get(BASE_URL if p == 1 else f"{BASE_URL}/page/{p}/")
            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            for art in soup.find_all("article", class_="news"):
                l, t = art.find("a", class_="big-link"), art.find("h2", class_="title")
                if l and t: games_to_scrape.append({"url": l["href"], "title": t.get_text(strip=True)})

        # FASE 2: SCRAPE Y PRESERVAR MANUALES
        for game in reversed(games_to_scrape):
            game_data = scrape_game(driver, game["url"], game["title"])
            if game_data:
                clean_t = game_data["title"]
                # Buscar si este juego ya estaba en el JSON para no perder lo manual
                old_version = next((d for d in data_final["downloads"] if d["title"] == clean_t), None)
                if old_version:
                    game_data["appId"] = old_version.get("appId")
                    game_data["header-image"] = old_version.get("header-image")
                else:
                    game_data["appId"] = None
                    game_data["header-image"] = None
                
                data_final["downloads"] = [d for d in data_final["downloads"] if d["title"] != clean_t]
                data_final["downloads"].insert(0, game_data)
                
                with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                    json.dump(data_final, f, indent=2, ensure_ascii=False)

        # FASE 3: RELLENAR SOLO LO VACÍO (SIN SOBRESCRIBIR)
        print("\n[*] Buscando metadatos solo para campos vacíos...")
        any_meta_updated = False
        for item in data_final["downloads"]:
            c_id = item.get("appId")
            c_img = item.get("header-image")

            # REGLA DE ORO: Si ya tiene ID e Imagen, no llamar a la API
            if c_id is not None and c_img is not None:
                continue

            new_id, new_img = get_steam_metadata(item["title"], existing_appid=c_id, existing_img=c_img)
            
            # Solo actualizamos si realmente encontramos algo que no estaba
            if new_id != c_id or new_img != c_img:
                item["appId"] = new_id
                item["header-image"] = new_img
                any_meta_updated = True
                print(f"    [SteamMeta] {item['title']} -> ID: {new_id}")
                time.sleep(1.0)

        if any_meta_updated:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(data_final, f, indent=2, ensure_ascii=False)

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
