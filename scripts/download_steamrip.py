import os
import json
import re
import sys
import time
from urllib.parse import urlparse, urljoin, urlencode
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
DEBUG_AJAX = True         # Imprime la respuesta del servidor en cada carga

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


def flaresolverr_post(url, data):
    """
    Hace un POST a través de FlareSolverr (útil si Cloudflare bloquea a requests).
    Devuelve el cuerpo de la respuesta como texto plano (sin el <pre> que mete el navegador).
    """
    payload = {
        "cmd": "request.post",
        "url": url,
        "postData": urlencode(data, doseq=True),
        "maxTimeout": 60000,
    }
    try:
        r = requests.post(FLARESOLVERR_URL, json=payload, timeout=90).json()
        if r.get("status") != "ok":
            return ""
        body = r.get("solution", {}).get("response", "")
        # FlareSolverr suele devolver el JSON envuelto en HTML: <html>...<pre>{...}</pre>
        if body.lstrip().startswith("<"):
            soup = BeautifulSoup(body, "html.parser")
            pre = soup.find("pre")
            return pre.get_text() if pre else soup.get_text()
        return body
    except Exception as e:
        print(f"      [x] Error en POST vía FlareSolverr: {e}")
        return ""


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


def parse_post_items(soup, seen_urls, games):
    """
    Extrae todos los <li class="post-item"> de un soup y los añade a `games`
    evitando duplicados. Devuelve cuántos juegos nuevos se añadieron.
    """
    added = 0
    for item in soup.find_all("li", class_="post-item"):
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

        if href.startswith("https://steamrip.com/") and len(text) >= 3 and href not in seen_urls:
            seen_urls.add(href)
            games.append({"title": text, "url": href})
            added += 1
    return added


def extract_block_config(html):
    """
    Busca las variables js_tie_block_XXXX = {...}; que el tema Jannah mete en un <script>
    y devuelve la configuración del bloque con paginación 'load-more'.
    Usa raw_decode para parsear bien el JSON aunque tenga llaves anidadas.
    """
    decoder = json.JSONDecoder()
    candidates = []

    for m in re.finditer(r'js_tie_block_(\d+)\s*=\s*', html):
        start = m.end()
        # Saltar hasta la primera llave
        brace = html.find("{", start)
        if brace == -1 or brace - start > 5:
            continue
        try:
            cfg, _ = decoder.raw_decode(html[brace:])
            if isinstance(cfg, dict):
                candidates.append((m.group(1), cfg))
        except Exception:
            continue

    print(f"    [*] Bloques tie encontrados en el HTML: {[c[0] for c in candidates]}")

    for block_id, cfg in candidates:
        if str(cfg.get("pagi", "")).lower() in ("load-more", "load_more"):
            print(f"    [ok] Usando bloque {block_id}: {cfg}")
            return cfg

    if candidates:
        print(f"    [!] Ningún bloque con 'load-more'; usando el primero ({candidates[0][0]}).")
        return candidates[0][1]
    return {}


def build_ajax_payload(action, page_num, block_data):
    """
    Construye el payload igual que jQuery: block[clave]=valor,
    y block[clave][]=valor para listas.
    """
    payload = {
        "action": action,
        "page": page_num,
        "block": None,  # se elimina más abajo
    }
    payload.pop("block")

    for k, v in block_data.items():
        if isinstance(v, (list, tuple)):
            payload[f"block[{k}][]"] = [str(x) for x in v]
        elif isinstance(v, dict):
            for sk, sv in v.items():
                payload[f"block[{k}][{sk}]"] = sv
        elif isinstance(v, bool):
            payload[f"block[{k}]"] = "true" if v else "false"
        elif v is None:
            payload[f"block[{k}]"] = ""
        else:
            payload[f"block[{k}]"] = v
    return payload


def parse_ajax_response(raw_text):
    """ Devuelve (html, hide_next) a partir de la respuesta del endpoint AJAX. """
    raw_text = raw_text.strip()
    data = raw_text
    # Jannah a veces devuelve el JSON doblemente codificado (un string que contiene otro JSON),
    # así que decodificamos hasta 3 veces mientras el resultado siga siendo un str.
    for _ in range(3):
        if not isinstance(data, str):
            break
        try:
            data = json.loads(data)
        except Exception:
            break

    if isinstance(data, dict):
        html_code = data.get("code") or data.get("html") or ""
        hide_next = bool(data.get("hide_next", False))
        return html_code, hide_next

    # Si no era JSON, devolvemos el texto tal cual (podría ser HTML directo)
    return data if isinstance(data, str) else raw_text, False


def fetch_recently_added_with_load_more(session, initial_html):
    """
    Extrae los juegos del bloque 'Recently Added' y simula la paginación AJAX
    del tema Jannah (action=tie_blocks_load_more).
    """
    soup = BeautifulSoup(initial_html, 'html.parser')

    # 1. Localizar el contenedor exclusivo de "Recently Added"
    recent_section = None
    for wrapper in soup.find_all("div", class_="container-wrapper"):
        title_el = wrapper.find("h3")
        if title_el and "recently added" in title_el.get_text().strip().lower():
            recent_section = wrapper
            break

    target_container = recent_section if recent_section else soup

    games = []
    seen_local_urls = set()

    containers = target_container.find_all("ul", class_=lambda x: x and "posts-items" in x)
    if not containers:
        containers = [target_container]

    for container in containers:
        parse_post_items(container, seen_local_urls, games)

    print(f"    └─ Inicial (Página 1): Encontrados {len(games)} juegos en 'Recently Added'.")

    # 2. Comprobar que existe el botón Load More
    load_more_btn = target_container.find("a", class_="load-more-button")
    if not load_more_btn:
        print("    [!] No se encontró el botón 'Load More' en la sección Recently Added.")
        return games

    # 3. La configuración NO está en el botón: está en un <script> (js_tie_block_XXXX)
    action = load_more_btn.get("data-action", "tie_blocks_load_more")
    block_data = extract_block_config(initial_html)
    if not block_data:
        print("    [!] No se encontró la configuración del bloque en el HTML.")
        print("        Abre DevTools > Network > filtro 'admin-ajax.php', pulsa 'Load More'")
        print("        y copia los campos block[...] que se envían.")
        return games

    session.headers.update({
        "X-Requested-With": "XMLHttpRequest",
        "Referer": HOME_URL,
        "Origin": BASE_URL,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    })

    use_flaresolverr_post = False  # se activa si requests es bloqueado por Cloudflare

    page_num = 2
    for click_i in range(1, MAX_LOAD_MORE_CLICKS + 1):
        print(f"    └─ Simulando carga de página AJAX {page_num}...")

        ajax_payload = build_ajax_payload(action, page_num, block_data)
        raw_text = ""

        try:
            if not use_flaresolverr_post:
                res = session.post(AJAX_URL, data=ajax_payload, timeout=20)
                raw_text = res.text
                if DEBUG_AJAX:
                    print(f"      [debug] status={res.status_code} body[:300]={raw_text[:300]!r}")

                blocked = (
                    res.status_code in (403, 503) or
                    "just a moment" in raw_text.lower()
                )
                if blocked:
                    print("      [!] Cloudflare bloqueó a requests. Reintentando vía FlareSolverr...")
                    use_flaresolverr_post = True
                elif res.status_code != 200:
                    print(f"      [x] Error HTTP {res.status_code} al llamar al endpoint AJAX.")
                    break

            if use_flaresolverr_post:
                raw_text = flaresolverr_post(AJAX_URL, ajax_payload)
                if DEBUG_AJAX:
                    print(f"      [debug] (flaresolverr) body[:300]={raw_text[:300]!r}")
                if not raw_text:
                    print("      [x] FlareSolverr no devolvió respuesta para el POST.")
                    break

            html_code, hide_next = parse_ajax_response(raw_text)

            if not html_code or html_code.strip() in ("0", "-1"):
                print("      [!] Respuesta vacía del servidor. Fin de la paginación.")
                break

            ajax_soup = BeautifulSoup(html_code, 'html.parser')
            new_games_count = parse_post_items(ajax_soup, seen_local_urls, games)

            if new_games_count > 0:
                print(f"      [ok] +{new_games_count} juegos obtenidos en la iteración #{click_i}.")
            else:
                print(f"      [!] No se encontraron nuevos juegos en el clic #{click_i}. Fin de la paginación.")
                break

            if hide_next:
                print("      [*] El servidor indica que no hay más páginas.")
                break

        except Exception as e:
            print(f"      [x] No se pudo realizar la carga AJAX: {e}")
            break

        page_num += 1
        time.sleep(1.0)

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

    def apply_session(cookies, user_agent):
        if user_agent:
            session.headers.update({"User-Agent": user_agent})
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain'))

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

        apply_session(cookies, user_agent)

    # 2. Extraer juegos de Recently Added en la Home (con hasta 3 clics en Load More)
    print(f"\n[*] Solicitando juegos 'Recently Added' (Home + Load More) a FlareSolverr...")
    html_home, home_cookies, home_ua = get_page_and_session_via_flaresolverr(HOME_URL)
    if html_home:
        # Usar también las cookies más recientes de la home (por si cambian)
        apply_session(home_cookies, home_ua)

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

    # Limpiar cabeceras AJAX para las peticiones GET normales de cada juego
    for h in ("X-Requested-With", "Origin", "Accept"):
        session.headers.pop(h, None)

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
    print("\n" + "=" * 65)
    print("[ok] ¡Sincronización Finalizada con Éxito!")
    print(f"[*] Juegos totales guardados en JSON: {len(consolidated_results)}")
    print(f"[*] Juegos nuevos añadidos: {scraped_count}")
    print(f"[*] Juegos actualizados: {updated_count}")
    print(f"[*] Tiempo de ejecución: {end_time - start_time:.2f} segundos.")
    print("=" * 65)


if __name__ == "__main__":
    main()
