import asyncio
import json
import os
import re
import time
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

# --- CONFIGURACIÓN ---
BASE_URL = "https://pcgamestorrents.com"
PAGES_TO_SCAN = 7 
JSON_FILE = "public/iggames.json"
SELENIUM_URL = os.environ.get("SELENIUM_URL", "http://localhost:4444/wd/hub")

def save_results(lista_juegos):
    os.makedirs("public", exist_ok=True)
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"name": "IGGames", "downloads": lista_juegos},
            f,
            indent=2,
            ensure_ascii=False
        )

async def fase_1_scan_portada(session):
    print(f"[*] Escaneando las primeras {PAGES_TO_SCAN} páginas...")
    juegos_portada = []
    for page in range(1, PAGES_TO_SCAN + 1):
        url = BASE_URL if page == 1 else f"{BASE_URL}/page/{page}"
        try:
            async with session.get(url, timeout=30) as response:
                if response.status != 200: continue
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                titles = soup.find_all("h2", class_=re.compile(r"uk-article-title|entry-title"))
                for t in titles:
                    link = t.find("a")
                    if link and link.get("href"):
                        juegos_portada.append({
                            "title": link.get_text(strip=True),
                            "url": link.get("href")
                        })
        except Exception as e:
            print(f"Error en página {page}: {e}")
    return juegos_portada

async def fase_2_extraer_datos(session, game_url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with session.get(game_url, headers=headers, timeout=15) as r:
            if r.status == 200:
                html = await r.text()
                # 1. Fecha
                date_m = re.search(r'datetime="([^"]+)"', html)
                date = date_m.group(1) if date_m else None
                # 2. Tamaño (Regex Directo)
                size = "N/A"
                size_m = re.search(r'Release Size:.*?([\d.]+\s*[GM]B)', html, re.I | re.S)
                if not size_m: 
                    size_m = re.search(r'Size:.*?([\d.]+\s*[GM]B)', html, re.I | re.S)
                if size_m: size = size_m.group(1)
                # 3. PHP Generator
                gen = re.search(r'href=["\'](https?://[^"\']*(?:url-generator|get-url)\.php\?url=[^"\']+)["\']', html, re.I)
                gen_url = gen.group(1) if gen else None
                return date, size, gen_url
    except: pass
    return None, "N/A", None

def resolve_magnet_selenium(generator_url):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    driver = None
    try:
        try:
            driver = webdriver.Remote(command_executor=SELENIUM_URL, options=options)
        except:
            driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(30)
        driver.get(generator_url)
        time.sleep(6)
        driver.execute_script("window.timeStart = Date.now() - 60000; if(window.generateDownloadUrl) window.generateDownloadUrl();")
        for _ in range(15):
            m = re.search(r'magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^\s\'"<>]*', driver.page_source, re.I)
            if m: return m.group(0)
            time.sleep(1)
    except: return None
    finally:
        if driver:
            try: driver.quit()
            except: pass
    return None

async def main():
    start_time = time.perf_counter()
    biblioteca = []
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                biblioteca = json.load(f).get("downloads", [])
        except: biblioteca = []

    huellas_existentes = {f"{g['title']}|{g.get('uploadDate')}" for g in biblioteca}

    async with aiohttp.ClientSession() as session:
        juegos_hoy = await fase_1_scan_portada(session)
        print(f"[*] Detectados {len(juegos_hoy)} juegos en portada.")

        a_procesar = []
        for j in juegos_hoy:
            # --- FILTRO HYPERVISOR ---
            if "hypervisor" in j["title"].lower():
                print(f"    - [OMITIDO] {j['title']} (Motivo: Bypass Hypervisor)")
                continue
            
            fecha, tamaño, gen_url = await fase_2_extraer_datos(session, j["url"])
            huella_web = f"{j['title']}|{fecha}"

            if huella_web not in huellas_existentes:
                j.update({"fecha": fecha, "tamaño": tamaño, "gen_url": gen_url})
                a_procesar.append(j)

        print(f"[*] Pendientes reales: {len(a_procesar)}")

        if a_procesar:
            executor = ThreadPoolExecutor(max_workers=1)
            for i, item in enumerate(a_procesar):
                print(f"[{i+1}/{len(a_procesar)}] {item['title']}")
                
                if item["gen_url"]:
                    loop = asyncio.get_event_loop()
                    magnet = await loop.run_in_executor(executor, resolve_magnet_selenium, item["gen_url"])
                    
                    # Limpieza por título para actualizaciones
                    biblioteca = [g for g in biblioteca if g["title"] != item["title"]]
                    
                    biblioteca.append({
                        "title": item["title"],
                        "uris": [magnet] if magnet else [],
                        "fileSize": item["tamaño"],
                        "uploadDate": item["fecha"]
                    })
                    
                    if magnet:
                        print(f"    [OK] Magnet guardado.")
                        save_results(biblioteca)
                    else:
                        print(f"    [!] No se obtuvo magnet.")
                else:
                    print(f"    [!] No se halló link de descarga.")

    save_results(biblioteca)
    print(f"\nFinalizado en {int(time.perf_counter()-start_time)}s.")

if __name__ == "__main__":
    asyncio.run(main())
