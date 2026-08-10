import os
import json
import re
import sys
import time
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

# --- CONFIGURACIÓN ---
BASE_URL = "https://steamrip.com"
FLARESOLVERR_URL = "http://localhost:8191/v1"
FLARESOLVERR_HEALTH_URL = "http://localhost:8191/health"
OUTPUT_FILE = "public/steamrip.json"

LIST_URLS = [
    "https://steamrip.com/games-list-page/"
]

SOCIAL_HOSTS = {"discord.gg", "discord.com", "facebook.com", "instagram.com", "patreon.com", 
                 "reddit.com", "telegram.me", "t.me", "tiktok.com", "twitter.com", "x.com", "youtube.com", "youtu.be"}

DOWNLOAD_HOSTS = {"1fichier.com", "buzzheavier.com", "bzzhr.to", "ddownload.com", "fuckingfast.co", "gofile.io", 
                  "krakenfiles.com", "mediafire.com", "mega.nz", "megadb.net", "multiup.io", "pixeldrain.com", 
                  "qiwi.gg", "rapidgator.net", "send.cm", "sendcm.com", "upload.ee", "vikingfile.com"}


# --- RECOLECCIÓN DE SESIÓN CLOUDFLARE ---
def check_flaresolverr():
    try:
        req = requests.get(FLARESOLVERR_HEALTH_URL, timeout=5)
        return req.status_code == 200
    except Exception:
        return False

def get_list_and_session_via_flaresolverr(url):
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": 60000,
    }
    try:
        response = requests.post(FLARESOLVERR_URL, json=payload, timeout=90)
        res = response.json()
        if res.get("status") == "ok":
            solution = res.get("solution", {})
            html = solution.get("response", "")
            cookies = solution.get("cookies", [])
            user_agent = solution.get("userAgent", "")
            return html, cookies, user_agent
        return "", [], ""
    except Exception as e:
        print(f"[x] Error al conectar con FlareSolverr: {e}")
        return "", [], ""


# --- PARSEO Y AUXILIARES ---
def clean_title(title):
    if not title:
        return ""
    # Quitamos paréntesis, corchetes y coletillas comunes para enlazar el juego de forma unívoca por su ID/Nombre base
    title = re.sub(r'\(.*?\)', '', title)  
    title = re.sub(r'\[.*?\]', '', title)  
    title = title.replace("Free Download", "")
    return " ".join(title.split()).strip().lower()

def load_existing_json():
    existing_map = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                downloads = data.get("downloads", [])
                for download in downloads:
                    title = download.get("title")
                    key = clean_title(title)
                    if key and download.get("uris"):
                        existing_map[key] = {
                            "title": title,
                            "uploadDate": download.get("uploadDate"),
                            "fileSize": download.get("fileSize"),
                            "uris": download.get("uris")
                        }
            print(f"[ok] Archivo local detectado. Cargadas {len(existing_map)} entradas en caché.")
        except Exception as e:
            print(f"[!] Error al leer el JSON existente: {e}")
    else:
        print("[*] No se encontró un JSON previo. Se creará una base de datos nueva.")
    return existing_map

def extract_game_links(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    games = []
    unique_urls = set()

    containers = soup.find_all(class_="az-list-container")
    if not containers:
        containers = [soup.find(["article", "main"]) or soup.find(class_=["entry-content", "td-post-content"]) or soup.body]

    for container in containers:
        if not container:
            continue
        anchors = container.find_all("a", href=True)
        for anchor in anchors:
            raw_href = anchor["href"].strip()
            text = anchor.get_text().strip()

            href = urljoin(BASE_URL, raw_href)

            if not href.startswith("https://steamrip.com/"):
                continue
            if any(x in href for x in ["/games-list-page/", "/all-games-list/", "/updated-games/", "/category/", "/tag/", "/faq/", "/discord", "#"]):
                continue
            if len(text) < 3:
                continue

            if re.search(r'free download', text, re.IGNORECASE) or "free-download" in href.lower():
                if href not in unique_urls:
                    unique_urls.add(href)
                    # Si el texto del enlace era muy corto o raro, usamos una versión limpia basada en la URL
                    clean_text = text if len(text) > 5 else raw_href.strip("/").split("/")[-1].replace("-", " ").title()
                    games.append({"title": clean_text, "url": href})
    return games

def extract_post_details(html_content, game_title):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Intentar capturar el título exacto actual de la página (ej: v1.9.0)
    current_title = game_title
    h1_title = soup.find("h1", class_=["entry-title", "td-page-title"])
    if h1_title:
        current_title = h1_title.get_text().strip()

    # 2. Fecha de publicación
    upload_date = None
    meta_date = soup.find("meta", property="article:published_time")
    if meta_date and meta_date.get("content"):
        upload_date = meta_date["content"].strip()
    else:
        time_tag = soup.find("time", datetime=True)
        if time_tag:
            upload_date = time_tag["datetime"].strip()

    article = soup.find(class_=["entry-content", "td-post-content"]) or soup.find("article") or soup.body

    # 3. Tamaño del archivo
    file_size = None
    if article:
        body_text = " ".join(article.get_text().split())
        size_match = re.search(r'(?:file\s*size|size)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:KB|MB|GB|TB))', body_text, re.IGNORECASE)
        if size_match:
            file_size = size_match.group(1).strip()

    # 4. Enlaces de descarga legítimos
    uris = []
    if article:
        for anchor in article.find_all("a", href=True):
            href = anchor["href"].strip()
            
            if href.startswith("//"):
                href = "https:" + href
                
            if not href.startswith(("http://", "https://")):
                continue

            try:
                parsed_url = urlparse(href)
                hostname = parsed_url.netloc.replace("www.", "").lower()
                path = parsed_url.path.lower()
            except Exception:
                continue

            if "steamstatic.com" in hostname or "steampowered.com" in hostname:
                continue
            if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                continue
            if "steamrip.com" in hostname:
                continue
            if hostname in SOCIAL_HOSTS or any(hostname.endswith(f".{sh}") for sh in SOCIAL_HOSTS):
                continue

            anchor_text = anchor.get_text().lower()
            parent_text = anchor.parent.get_text().lower() if anchor.parent else ""

            keywords = ["download", "mirror", "gofile", "buzzheavier", "bzzhr", "pixeldrain", "vikingfile", "qiwi","megadb"]
            looks_like_download = (
                hostname in DOWNLOAD_HOSTS or 
                any(hostname.endswith(f".{dh}") for dh in DOWNLOAD_HOSTS) or
                any(kw in anchor_text for kw in keywords) or
                any(kw in parent_text for kw in keywords)
            )

            if looks_like_download and href not in uris:
                uris.append(href)

    return {
        "title": current_title,
        "uploadDate": upload_date,
        "fileSize": file_size,
        "uris": uris
    }


# --- PROCESO PRINCIPAL ---
def main():
    print("=" * 58)
    print("  Scraper SteamRIP Inteligente V2 (Sincronización de Updates)")
    print("=" * 58)

    if not check_flaresolverr():
        print("[x] FlareSolverr no está corriendo en localhost:8191.")
        sys.exit(1)
        
    print("[ok] FlareSolverr detectado.")
    existing_map = load_existing_json()
    session = requests.Session()
    
    # 1. Bypass Cloudflare e índice de la web
    games = []
    for list_url in LIST_URLS:
        print(f"[*] Solicitando bypass inicial a FlareSolverr para: {list_url}")
        html, cookies, user_agent = get_list_and_session_via_flaresolverr(list_url)
        
        if html:
            games = extract_game_links(html)
            if games:
                print(f"[ok] ¡Bypass exitoso! Encontrados {len(games)} juegos en el índice de la web.")
                session.headers.update({"User-Agent": user_agent})
                for cookie in cookies:
                    session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
                break
        time.sleep(1)
        
    if not games:
        print("[x] No se pudo obtener la sesión válida de Cloudflare.")
        sys.exit(1)

    results = []
    reused_count = 0
    updated_count = 0
    scraped_count = 0
    
    juegos_a_procesar = games 
    total_games = len(juegos_a_procesar)
    
    print(f"\n[*] Procesando {total_games} juegos evaluando actualizaciones...")
    start_time = time.time()

    for idx, game in enumerate(juegos_a_procesar, 1):
        game_key = clean_title(game['title'])
        cached_item = existing_map.get(game_key)
        
        try:
            # Consultamos la web nativamente a toda velocidad
            response = session.get(game['url'], timeout=15)
            if response.status_code == 200:
                details = extract_post_details(response.text, game['title'])
                
                # Si el juego ya existía en el JSON local...
                if cached_item:
                    # COMPARACIÓN INTELIGENTE DOBLE: Validamos fecha Y título exacto (versión)
                    if cached_item["uploadDate"] == details["uploadDate"] and cached_item["title"] == details["title"]:
                        # No ha cambiado absolutamente nada: Reutilizamos la caché
                        results.append({
                            "title": cached_item["title"],
                            "uploadDate": cached_item["uploadDate"],
                            "fileSize": cached_item["fileSize"],
                            "uris": cached_item["uris"]
                        })
                        reused_count += 1
                        # LOG INDIVIDUAL ACTIVADO PARA ELEMENTOS EN CACHÉ:
                        print(f"[{idx}/{total_games}] [cache] Sin cambios: {cached_item['title']}")
                    else:
                        # ¡O la fecha o la versión han cambiado en la web! Fuerza la actualización
                        if details["uris"]:
                            results.append(details)
                            updated_count += 1
                            print(f"[{idx}/{total_games}] [ACTUALIZACIÓN] {cached_item['title']} -> {details['title']} ({details['fileSize']})")
                        else:
                            # Si da un fallo raro de enlaces, conservamos lo que había
                            results.append(cached_item)
                            reused_count += 1
                            print(f"[{idx}/{total_games}] [cache] Sin cambios (Fallo links en web): {cached_item['title']}")
                else:
                    # Es un juego completamente nuevo en la web
                    if details["uris"]:
                        results.append(details)
                        scraped_count += 1
                        print(f"[{idx}/{total_games}] [NUEVO] {details['title']} ({details['fileSize']})")
                    else:
                        print(f"[{idx}/{total_games}] [!] Saltado (Sin enlaces utilizables): {game['title']}")
            else:
                print(f"[{idx}/{total_games}] [x] HTTP Error {response.status_code} en {game['title']}")
                if cached_item:  # Conservar caché si la web da error temporal
                    results.append(cached_item)
                    reused_count += 1
        except Exception as e:
            print(f"[{idx}/{total_games}] [x] Error en {game['title']}: {e}")
            if cached_item:
                results.append(cached_item)
                reused_count += 1
            
        time.sleep(0.2) # Control prudente de peticiones concurrentes

    # 3. Guardar resultados consolidados
    results.sort(key=lambda x: x["title"])
    output_data = {
        "name": "SteamRip",
        "downloads": results
    }
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        
    end_time = time.time()
    print(f"\n" + "="*58)
    print(f"[ok] ¡Sincronización de Updates Finalizada!")
    print(f"[*] Guardados totales en JSON: {len(results)}")
    print(f"[*] Juegos nuevos añadidos: {scraped_count}")
    print(f"[*] Versiones actualizadas indexadas: {updated_count}")
    print(f"[*] Juegos sin cambios (Caché): {reused_count}")
    print(f"[*] Tiempo de ejecución: {end_time - start_time:.2f} segundos.")
    print("="*58)


if __name__ == "__main__":
    main()