from __future__ import annotations

import json
import random
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# Intentar importar 'stem' para rotación de Tor. Si no está instalada, no rompe el script.
try:
    from stem import Signal
    from stem.control import Controller
    HAS_STEM = True
except ImportError:
    HAS_STEM = False

ANKERGAMES_LIST_URL = "https://ankergames.net/games-list"
OUTPUT_FILE = Path("public/ankergames.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

TOR_SOCKS_PORT = 9150  
TOR_CONTROL_PORT = 9151
TOR_PROXY = f"socks5://127.0.0.1:{TOR_SOCKS_PORT}"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def is_tor_running() -> bool:
  """Comprueba si Tor está escuchando en el puerto 9050 o 9150."""
  for port in (9150, 9050):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
      s.settimeout(1)
      if s.connect_ex(("127.0.0.1", port)) == 0:
        global TOR_SOCKS_PORT, TOR_PROXY
        TOR_SOCKS_PORT = port
        TOR_PROXY = f"socks5://127.0.0.1:{port}"
        return True
  return False

def renew_tor_ip() -> None:
    """Envia la señal NEWNYM al puerto de control de Tor si está disponible."""
    if not HAS_STEM:
        return

    try:
        with Controller.from_port(port=TOR_CONTROL_PORT) as controller:
            controller.authenticate()
            controller.signal(Signal.NEWNYM)
            time.sleep(3)  # Margen para rehacer el circuito de Tor
            log("    [🔄] IP renovada con éxito vía Tor.")
    except Exception as e:
        log(f"    [!] No se pudo renovar la IP de Tor (Puerto {TOR_CONTROL_PORT}): {e}")


def parse_iso_date(date_str: str) -> str:
    """Convierte la fecha a formato ISO UTC (YYYY-MM-DDTHH:MM:SS.000Z)."""
    if not date_str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        clean_date = date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_date)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def process_single_game(page, game_info: Dict[str, Any], index: int, total: int) -> Optional[Dict[str, Any]]:
    game_url = game_info.get("url")
    title = game_info.get("title")
    file_size = game_info.get("size", "Unknown")
    raw_date = game_info.get("date", "")
    upload_date = parse_iso_date(raw_date)

    final_download_url: Optional[str] = None

    def intercept_request(request):
        nonlocal final_download_url
        req_url = request.url
        if "/generate-download-url/" in req_url:
            return
        if "/download/" in req_url or any(host in req_url for host in ["megadb", "gofile", "pixeldrain", "qiwi"]):
            if req_url != page.url and not final_download_url:
                final_download_url = req_url

    def intercept_response(response):
        nonlocal final_download_url
        resp_url = response.url
        if 300 <= response.status < 400:
            loc = response.headers.get("location")
            if loc and ("/download/" in loc or "http" in loc) and not final_download_url:
                final_download_url = loc
        if "/generate-download-url/" in resp_url and response.status == 200:
            try:
                data = response.json()
                target_url = data.get("url") or data.get("download_url") or data.get("link")
                if target_url and not final_download_url:
                    final_download_url = target_url
            except Exception:
                pass
        if "/download/" in resp_url and not final_download_url:
            final_download_url = resp_url

    page.on("request", intercept_request)
    page.on("response", intercept_response)

    try:
        page.goto(game_url, wait_until="domcontentloaded", timeout=45000)

        # 1. Abrir Modal de descarga inicial
        download_modal_btn = "button:has-text('Download')"
        page.wait_for_selector(download_modal_btn, timeout=15000)
        page.click(download_modal_btn, force=True)

        # 2. Esperar a que cargue el botón de descarga en el modal
        modal_download_btn = "a.download-button, button.download-button"
        page.wait_for_selector(modal_download_btn, state="attached", timeout=12000)

        # 3. Clic final
        page.evaluate("""() => {
            const btn = document.querySelector('a.download-button, button.download-button');
            if (btn) btn.click();
        }""")

        waited = 0
        while waited < 8000 and not final_download_url:
            page.wait_for_timeout(500)
            waited += 500

    except PlaywrightTimeoutError:
        pass
    except Exception:
        pass
    finally:
        page.remove_listener("request", intercept_request)
        page.remove_listener("response", intercept_response)

    if not final_download_url:
        log(f"[{index}/{total}] {title} ... ❌ ERROR")
        return None

    log(f"[{index}/{total}] {title} ... ✔ OK")
    return {
        "title": title,
        "fileSize": file_size,
        "uploadDate": upload_date,
        "uris": [final_download_url],
    }


def main() -> int:
  tor_active = is_tor_running()

  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    def create_fresh_context():
      """Crea un contexto completamente limpio sin cookies ni historial previo."""
      kwargs: Dict[str, Any] = {
          "user_agent": USER_AGENT,
          "viewport": {"width": 1280, "height": 800},
          "locale": "es-ES",
      }
      if tor_active:
        kwargs["proxy"] = {"server": TOR_PROXY}
      
      ctx = browser.new_context(**kwargs)
      return ctx, ctx.new_page()

    # Contexto inicial para extraer el catálogo completo
    context, page = create_fresh_context()

    log(f"[*] Accediendo al catálogo: {ANKERGAMES_LIST_URL}")
    try:
      page.goto(ANKERGAMES_LIST_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
      log(f"[x] Error accediendo al catálogo: {e}")
      browser.close()
      return 1

    all_games = page.evaluate("""() => {
            const wraps = document.querySelectorAll('div[data-game-id]');
            const results = [];

            wraps.forEach(wrap => {
                const d = wrap.dataset;
                const article = wrap.querySelector('article[listing]');
                let size = "Unknown";
                let date = "";

                if (article) {
                    try {
                        const listingData = JSON.parse(article.getAttribute('listing'));
                        size = listingData.runtime || "Unknown";
                        date = listingData.updated_at || listingData.created_at || "";
                    } catch(e) {}
                }

                if (d.gameTitle && d.gameUrl) {
                    results.push({
                        id: d.gameId,
                        title: d.gameTitle,
                        url: d.gameUrl,
                        size: size,
                        date: date
                    });
                }
            });

            return results;
        }""")

    total_games = len(all_games)
    if total_games == 0:
      log("[x] No se encontró ningún juego.")
      browser.close()
      return 1

    log(f"[*] {total_games} juegos detectados. Iniciando extracción...\n")

    downloads_list: List[Dict[str, Any]] = []

    for idx, game_info in enumerate(all_games, start=1):
      # Procesar el juego en la página actual
      download_entry = process_single_game(page, game_info, idx, total_games)

      if download_entry:
        downloads_list.append(download_entry)

      # Criterio para renovar la identidad completa (IP + Limpieza de Cookies)
      should_renew = (
          download_entry is None or (tor_active and idx % 5 == 0)
      ) and idx < total_games

      if should_renew and tor_active:
        log("    [🧹] Limpiando cookies y solicitando nueva identidad a Tor...")
        context.close()  # Destruye las cookies y sesión local
        renew_tor_ip()  # Cambia la IP de salida
        context, page = create_fresh_context()  # Abre un entorno totalmente limpio

    browser.close()

    output_data = {
        "name": "AnkerGames",
        "downloads": downloads_list,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
      json.dump(output_data, f, ensure_ascii=False, indent=2)

    log(
        f"\n[✔] Completado: {len(downloads_list)}/{total_games} procesados"
        " correctamente."
    )
    log(f"[✔] Guardado en: {OUTPUT_FILE.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())