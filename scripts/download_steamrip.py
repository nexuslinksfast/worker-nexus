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

# Secciones
UPDATED_GAMES_URL = "https://steamrip.com/updated-games/"
HOME_URL = "https://steamrip.com/"
AJAX_URL = "https://steamrip.com/wp-admin/admin-ajax.php"

# Configuración del botón "Load More"
MAX_LOAD_MORE_CLICKS = 3  # Máximo 3 cargas adicionales

SOCIAL_HOSTS = {
    "discord.gg", "discord.com", "facebook.com", "instagram.com", "patreon.com", 
    "reddit.com", "telegram.me", "t.me", "tiktok.com", "twitter.com", "x.com", 
    "youtube.com", "youtu.be"
}

DOWNLOAD_HOSTS = {
    "1fichier.com", "buzzheavier.com", "bzzhr.to", "ddownload.com", "fuckingfast.co", 
    "gofile.io", "krakenfiles.com", "mediafire.com", "mega.nz", "megadb.net", 
    "multiup.io", "pixeldrain.com", "qiwi.gg", "rapidgator.net", "send.cm", 
    "sendcm.com", "upload.ee", "vikingfile.com"
}


# --- RECOLECCIÓN DE SESIÓN CLOUDFLARE ---
def check_flaresolverr():
    try:
        req = requests.get(FLARESOLVERR_HEALTH_URL, timeout=5)
        return req.status_code == 200
    except Exception:
        return False

def get_page_and_session_via_flaresolverr(url):
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
        print(f"[x] Error al conectar con FlareSolverr para {url}: {e}")
        return "", [], ""


# --- PARSEO Y AUXILIARES ---
def clean_title(title):
    if not title:
        return ""
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

def extract_updated_games(html_content):
    """ Extrae tarjetas de la sección /updated-games/ """
    soup = BeautifulSoup(html_content, 'html.parser')
    games = []
    unique_urls = set()

    cards = soup.find_all("a", class_="updated-card")
    if not cards:
        cards = soup.find_all("a", href=True)

    for anchor in cards:
        raw_href = anchor.get("href", "").strip()
        if not raw_href:
            continue

        href = urljoin(BASE_URL, raw_href)

        if not href.startswith("https://steamrip.com/"):
            continue
        if any(x in href for x in ["/games-list-page/", "/all-games-list/", "/category/", "/tag/", "/faq/", "/discord", "#"]):
            continue
        if href.rstrip('/') == "https://steamrip.com/updated-games":
            continue

        title_el = anchor.find(class_="updated-card-title")
        text = title_el.get_text().strip() if title_el else anchor.get_text().strip()

        if len(text) < 3:
            continue

        if href not in unique_urls:
            unique_urls.add(href)
            clean_text = text if len(text) > 5 else raw_href.strip("/").split("/")[-1].replace("-", " ").title()
            games.append({"title": clean_text, "url": href})

    return games

def parse_recently_added_posts(soup):
    """ Extrae solo los posts pertenecientes al bloque 'Recently Added' """
    games = []
    # Nos centramos únicamente en la lista principal de entradas
    container = soup.find("ul", class_="posts-items") or soup
    posts_items = container.find_all("li", class_="post-item")

    for item in posts_items:
        anchor = item.find("a", href=True)
        if not anchor:
            continue

        raw_href = anchor.get("href", "").strip()
        href = urljoin(BASE_URL, raw_href)

        text = (
            anchor.get("aria-label", "").strip() or 
            (anchor.find("h2").get_text().strip() if anchor.find("h2") else "") or
            anchor.get_text().strip()
        )

        if not href.startswith("https://steamrip.com/") or len(text) < 3:
            continue

        games.append({"title": text, "url": href})

    return games

def fetch_recently_added_with_load_more(session, initial_html):
    """
    Lee la Home inicial e invoca directamente la API AJAX de WordPress
    para simular los clics de 'Load More' (hasta MAX_LOAD_MORE_CLICKS veces).
    """
    soup = BeautifulSoup(initial_html, 'html.parser')
    games = parse_recently_added_posts(soup)
    print(f"   └─ Inicial (Página 1): Encontrados {len(games)} juegos.")

    # Intentamos obtener los parámetros que WordPress necesita para el AJAX Load More
    # Normalmente están almacenados en la etiqueta o botón con la clase 'tie-pagination-load-more'
    load_more_btn = soup.find(class_=["tie-pagination-load-more", "load-more-button"])
    
    # Si no se localiza mediante botón, usamos la configuración estandard del tema JNews / TieLabs
    block_data = {}
    if load_more_btn:
        block_data = {
            "action": load_more_btn.get("data-action", "tie_blocks_load_more"),
            "block": load_more_btn.get("data-block", {}),
            "max_num_pages": load_more_btn.get("data-max", 100),
            "page": 1
        }
    
    # Si no pudimos extraer los atributos exactos automáticamente, preparamos un payload fallback estándar del tema
    page_num = 2
    for click_i in range(1, MAX_LOAD_MORE_CLICKS + 1):
        print(f"   └─ Simulando clic #{click_i} en 'Load More' (Cargando página AJAX {page_num})...")
        
        # Petición a la API AJAX de WordPress
        ajax_payload = {
            "action": "tie_blocks_load_more",
            "page": page_num,
            "block[type]": "posts-list",
            "block[number]": 18,
            "block[pagination]": "load-more"
        }
        
        try:
            res = session.post(AJAX_URL, data=ajax_payload, timeout=15)
            if res.status_code == 200:
                try:
                    data = res.json()
                    html_code = data.get("code", "") or data.get("html", "") or res.text
                except Exception:
                    html_code = res.text

                ajax_soup = BeautifulSoup(html_code, 'html.parser')
                new_games = parse_recently_added_posts(ajax_soup)

                if new_games:
                    print(f"      [ok] +{len(new_games)} juegos obtenidos en la iteración #{click_i}.")
                    games.extend(new_games)
                else:
                    print(f"      [!] No se encontraron nuevos juegos en el clic #{click_i}.")
                    break
            else:
                print(f"      [x] Error HTTP {res.status_code} al llamar al endpoint AJAX.")
                break

        except Exception as e:
            print(f"      [x] No se pudo realizar la carga AJAX: {e}")
            break

        page_num += 1
        time.sleep(0.5)

    return games

def extract_post_details(html_content, game_title):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    current_title = game_title
    h1_title = soup.find("h1", class_=["entry-title", "td-page-title"])
    if h1_title:
        current_title = h1_title.get_text().strip()

    upload_date = None
    meta_date = soup.find("meta", property="article:published_time")
    if meta_date and meta_date.get("content"):
        upload_date = meta_date["content"].strip()
    else:
        time_tag = soup.find("time", datetime=True)
        if time_tag:
            upload_date = time_tag["datetime"].strip()

    article = soup.find(class_=["entry-content", "td-post-content"]) or soup.find("article") or soup.body

    file_size = None
    if article:
        body_text = " ".join(article.get_text().split())
        size_match = re.search(r'(?:file\s*size|size)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:KB|MB|GB|TB))', body_text, re.IGNORECASE)
        if size_match:
            file_size = size_match.group(1).strip()

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

            keywords = ["download", "mirror", "gofile", "buzzheavier", "bzzhr", "pixeldrain", "vikingfile", "qiwi", "megadb", "fuckingfast"]
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
    print("=" * 65)
    print("  Scraper SteamRIP (Sincronización: Updated & Recently Added)")
    print("=" * 65)

    if not check_flaresolverr():
        print("[x] FlareSolverr no está corriendo en localhost:8191.")
        sys.exit(1)
        
    print("[ok] FlareSolverr detectado.")
    existing_map = load_existing_json()
    session = requests.Session()
    
    collected_games = []
    seen_urls = set()

    # 1. Extraer juegos de /updated-games/
    print(f"\n[*] Solicitando lista de actualizados a FlareSolverr: {UPDATED_GAMES_URL}")
    html_updated, cookies, user_agent = get_page_and_session_via_flaresolverr(UPDATED_GAMES_URL)
    if html_updated:
        updated_list = extract_updated_games(html_updated)
        print(f"[ok] Encontrados {len(updated_list)} juegos en /updated-games/")
        for g in updated_list:
            if g['url'] not in seen_urls:
                seen_urls.add(g['url'])
                collected_games.append(g)

        # Configurar la sesión con los headers/cookies devueltos por FlareSolverr
        session.headers.update({"User-Agent": user_agent})
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])

    # 2. Extraer juegos de Recently Added en la Home (con hasta 3 clics en Load More)
    print(f"\n[*] Solicitando juegos 'Recently Added' (Home + Load More) a FlareSolverr...")
    html_home, _, _ = get_page_and_session_via_flaresolverr(HOME_URL)
    if html_home:
        recently_added_list = fetch_recently_added_with_load_more(session, html_home)
        print(f"[ok] Total capturado en 'Recently Added': {len(recently_added_list)} juegos.")
        for g in recently_added_list:
            if g['url'] not in seen_urls:
                seen_urls.add(g['url'])
                collected_games.append(g)

    total_games = len(collected_games)
    if total_games == 0:
        print("[x] No se pudieron obtener juegos de ninguna de las fuentes.")
        sys.exit(1)

    print(f"\n[*] Procesando {total_games} juegos únicos conseguidos...")
    
    updated_count = 0
    scraped_count = 0
    start_time = time.time()

    for idx, game in enumerate(collected_games, 1):
        game_key = clean_title(game['title'])
        cached_item = existing_map.get(game_key)
        
        try:
            response = session.get(game['url'], timeout=15)
            if response.status_code == 200:
                details = extract_post_details(response.text, game['title'])
                
                if details["uris"]:
                    if cached_item:
                        updated_count += 1
                        print(f"[{idx}/{total_games}] [ACTUALIZADO] {cached_item['title']} -> {details['title']} ({details['fileSize']})")
                    else:
                        scraped_count += 1
                        print(f"[{idx}/{total_games}] [NUEVO] {details['title']} ({details['fileSize']})")
                    
                    existing_map[game_key] = details
                else:
                    print(f"[{idx}/{total_games}] [!] Saltado (Sin enlaces utilizables): {game['title']}")
            else:
                print(f"[{idx}/{total_games}] [x] HTTP Error {response.status_code} en {game['title']}")
        except Exception as e:
            print(f"[{idx}/{total_games}] [x] Error en {game['title']}: {e}")
            
        time.sleep(0.2)

    # Guardar resultados consolidados
    consolidated_results = list(existing_map.values())
    consolidated_results.sort(key=lambda x: x["title"])

    output_data = {
        "name": "SteamRip",
        "downloads": consolidated_results
    }
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        
    end_time = time.time()
    print(f"\n" + "="*65)
    print(f"[ok] ¡Sincronización Finalizada con Éxito!")
    print(f"[*] Juegos totales guardados en JSON: {len(consolidated_results)}")
    print(f"[*] Juegos nuevos añadidos: {scraped_count}")
    print(f"[*] Juegos actualizados: {updated_count}")
    print(f"[*] Tiempo de ejecución: {end_time - start_time:.2f} segundos.")
    print("="*65)


if __name__ == "__main__":
    main()