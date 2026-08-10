"""
Scraper multinivel para Tapochek.net (InsaneRamZes)
Detecta automáticamente la cantidad total de páginas, navega por todas ellas
usando requests y genera los enlaces magnet con trazabilidad completa.
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# --- CONFIGURACIÓN ---
USERNAME = os.environ.get("INSANERAMZES_USERNAME")
PASSWORD = os.environ.get("INSANERAMZES_PASSWORD")

if not USERNAME or not PASSWORD:
    raise EnvironmentError(
        "Faltan credenciales. Define INSANERAMZES_USERNAME y INSANERAMZES_PASSWORD "
        "como variables de entorno."
    )

FORUM_URL = "https://tapochek.net/viewforum.php?f=35"
BASE_DOMAIN = "https://tapochek.net/"
JSON_FILE = "public/InsaneRamZes.json"

SELENIUM_URL = os.environ.get("SELENIUM_URL", "http://localhost:4444")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def decode_bencode(data: bytes, index: int = 0):
    """Parsea estructuras bencode simples."""
    if data[index:index+1] == b'i':
        end = data.index(b'e', index)
        return int(data[index+1:end]), end + 1
    elif data[index:index+1] == b'l':
        index += 1
        items = []
        while data[index:index+1] != b'e':
            item, index = decode_bencode(data, index)
            items.append(item)
        return items, index + 1
    elif data[index:index+1] == b'd':
        index += 1
        items = {}
        while data[index:index+1] != b'e':
            key, index = decode_bencode(data, index)
            value, index = decode_bencode(data, index)
            items[key] = value
        return items, index + 1
    elif data[index:index+1].isdigit():
        colon = data.index(b':', index)
        length = int(data[index:colon])
        start = colon + 1
        return data[start:start+length], start + length
    else:
        raise ValueError("Estructura Bencode no válida")


def extract_info_hash(torrent_bytes: bytes) -> str | None:
    """Extrae el InfoHash SHA-1 del buffer .torrent."""
    try:
        info_start = torrent_bytes.find(b'4:info')
        if info_start == -1:
            return None
        
        info_dict_start = info_start + 6
        _, info_dict_end = decode_bencode(torrent_bytes, info_dict_start)
        
        raw_info = torrent_bytes[info_dict_start:info_dict_end]
        return hashlib.sha1(raw_info).hexdigest()
    except Exception:
        return None


def convert_torrent_url_to_magnet(session: requests.Session, torrent_url: str, title: str) -> str:
    """Descarga el torrent en memoria y retorna la URI magnet:."""
    try:
        resp = session.get(torrent_url, timeout=10)
        if resp.status_code == 200 and resp.content:
            info_hash = extract_info_hash(resp.content)
            if info_hash:
                import urllib.parse
                display_name = urllib.parse.quote(title)
                return f"magnet:?xt=urn:btih:{info_hash}&dn={display_name}"
    except Exception as e:
        print(f"      [X] Error descargando torrent: {e}")
    
    return torrent_url


def login_and_get_session() -> tuple[requests.Session, str]:
    """Inicia sesión única con Selenium y traspasa la sesión a Requests."""
    print("[*] Configurando navegador para Selenium...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-agent={USER_AGENT}")

    try:
        driver = webdriver.Remote(command_executor=f"{SELENIUM_URL}/wd/hub", options=options)
    except Exception:
        driver = webdriver.Chrome(options=options)

    try:
        print(f"[*] Entrando al foro: {FORUM_URL}...")
        driver.get(FORUM_URL)
        wait = WebDriverWait(driver, 15)

        user_field = wait.until(EC.presence_of_element_located((By.NAME, "login_username")))
        pass_field = driver.find_element(By.NAME, "login_password")

        try:
            remember_chk = driver.find_element(By.NAME, "autologin")
            if not remember_chk.is_selected():
                remember_chk.click()
        except Exception:
            pass

        print(f"[*] Iniciando sesión como '{USERNAME}'...")
        user_field.clear()
        user_field.send_keys(USERNAME)
        pass_field.clear()
        pass_field.send_keys(PASSWORD)

        submit_btn = driver.find_element(By.NAME, "login")
        driver.execute_script("arguments[0].click();", submit_btn)
        time.sleep(3)

        print("[OK] Sesión iniciada correctamente.")
        
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        for cookie in driver.get_cookies():
            session.cookies.set(cookie['name'], cookie['value'])

        return session, driver.page_source
    finally:
        driver.quit()


def get_total_pages(html: str) -> int:
    """Extrae el número máximo de páginas a partir de la paginación del HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    page_offsets = [0]

    # Busca enlaces tipo viewforum.php?f=35&start=3500
    for a in soup.find_all('a', href=re.compile(r'viewforum\.php\?f=\d+&amp;start=\d+|viewforum\.php\?f=\d+&start=\d+')):
        match = re.search(r'start=(\d+)', a.get('href', ''))
        if match:
            page_offsets.append(int(match.group(1)))

    max_offset = max(page_offsets)
    # Cada página en TorrentPier/phpBB muestra 50 resultados
    total_pages = (max_offset // 50) + 1
    return total_pages


def parse_page_table(session: requests.Session, html: str, page_num: int, total_pages: int) -> list[dict]:
    """Parsea las filas `#forum-table` de una página en concreto."""
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', id='forum-table')
    
    if not table:
        print(f"[!] No se encontró la tabla en la página {page_num}.")
        return []

    downloads = []
    tbodies = table.find_all('tbody', id=re.compile(r'^tb_\d+'))

    print(f"\n--- [PÁGINA {page_num}/{total_pages}] Procesando {len(tbodies)} elementos ---")

    for i, tbody in enumerate(tbodies, 1):
        row = tbody.find('tr')
        if not row:
            continue

        # 1. TÍTULO
        title_a = row.find('a', class_=re.compile(r'tp-topic-title-link|torTopic'))
        if not title_a:
            continue
        title = title_a.get_text(strip=True)

        short_title = (title[:48] + '...') if len(title) > 51 else title
        print(f"  [{i}/{len(tbodies)}] {short_title}")

        # 2. ENLACE Y TAMAÑO
        dl_a = row.find('a', href=re.compile(r'download\.php\?id=\d+'))
        uris = []
        file_size = "N/A"

        if dl_a:
            href = dl_a['href'].replace('./', '')
            full_torrent_url = BASE_DOMAIN + href
            file_size = dl_a.get_text(strip=True).replace('\xa0', ' ')
            
            t0 = time.time()
            magnet_uri = convert_torrent_url_to_magnet(session, full_torrent_url, title)
            elapsed = time.time() - t0
            
            uris.append(magnet_uri)
            print(f"      ├─ Size: {file_size} | Magnet obtenido en {elapsed:.2f}s")

        # 3. FECHA
        upload_date = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        tds = row.find_all('td')
        if tds:
            last_td = tds[-1]
            date_p = last_td.find('p')
            if date_p:
                date_str = date_p.get_text(strip=True)
                try:
                    dt = datetime.strptime(date_str, "%d-%m-%Y %H:%M")
                    upload_date = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                except Exception:
                    pass

        downloads.append({
            "title": title,
            "fileSize": file_size,
            "uploadDate": upload_date,
            "uris": uris
        })

    return downloads


def main():
    try:
        session, first_page_html = login_and_get_session()
        total_pages = get_total_pages(first_page_html)
        
        print(f"\n[+] Se detectaron {total_pages} páginas en total en este foro.")

        all_downloads = []
        start_global_time = time.time()

        for page in range(1, total_pages + 1):
            offset = (page - 1) * 50
            page_url = f"{FORUM_URL}&start={offset}" if page > 1 else FORUM_URL
            
            if page > 1:
                resp = session.get(page_url)
                if resp.status_code != 200:
                    print(f"[X] Falló al cargar página {page}. Saltando...")
                    continue
                html = resp.text
            else:
                html = first_page_html

            page_downloads = parse_page_table(session, html, page, total_pages)
            all_downloads.extend(page_downloads)

        total_elapsed = time.time() - start_global_time

        json_data = {
            "name": "InsaneRamZes",
            "downloads": all_downloads
        }

        os.makedirs("public", exist_ok=True)
        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        print(f"\n[=== PROCESO COMPLETO FINALIZADO ===]")
        print(f" Total procesado: {len(all_downloads)} entradas de {total_pages} páginas.")
        print(f" Tiempo total: {total_elapsed:.2f} segundos.")
        print(f" Guardado en: '{JSON_FILE}'")

    except Exception as e:
        print(f"[X] Error crítico durante la ejecución: {e}")


if __name__ == "__main__":
    main()