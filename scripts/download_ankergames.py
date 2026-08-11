from __future__ import annotations

import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from playwright.sync_api import sync_playwright

ANKERGAMES_LIST_URL = "https://ankergames.net/games-list"
OUTPUT_FILE = Path("public/ankergames.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

TOR_SOCKS_PORT = 9150  
TOR_PROXY = f"socks5://127.0.0.1:{TOR_SOCKS_PORT}"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def is_tor_running() -> bool:
    for port in (9150, 9050):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                global TOR_SOCKS_PORT, TOR_PROXY
                TOR_SOCKS_PORT = port
                TOR_PROXY = f"socks5://127.0.0.1:{port}"
                return True
    return False


def parse_iso_date(date_str: str) -> str:
    if not date_str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        clean_date = date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_date)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def handle_cloudflare_challenge(page) -> bool:
    try:
        content = page.content().lower()
        if "verificación de seguridad" in content or "challenges.cloudflare.com" in content or "just a moment" in content:
            log("    [⚠️] Cloudflare Challenge detectado. Esperando resolución...")
            time.sleep(5)
            for _ in range(10):
                if "challenges.cloudflare.com" not in page.content():
                    return True
                time.sleep(1)
            return False
    except Exception:
        pass
    return True


def main() -> int:
    tor_active = is_tor_running()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--headless=new",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ]
        )

        kwargs: Dict[str, Any] = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 800},
            "locale": "es-ES",
            "ignore_https_errors": True,
        }
        if tor_active:
            kwargs["proxy"] = {"server": TOR_PROXY}

        context = browser.new_context(**kwargs)
        page = context.new_page()

        log(f"[*] Accediendo al catálogo: {ANKERGAMES_LIST_URL}")
        try:
            page.goto(ANKERGAMES_LIST_URL, wait_until="domcontentloaded", timeout=60000)
            if not handle_cloudflare_challenge(page):
                log("[x] ERROR: Bloqueado por Cloudflare.")
                browser.close()
                return 1
        except Exception as e:
            log(f"[x] Error accediendo al catálogo: {e}")
            browser.close()
            return 1

        all_games_map: Dict[str, Dict[str, str]] = {}
        clicks = 0
        consecutive_failures = 0

        log("[*] Iniciando paginación fluida (con limpieza constante de memoria DOM)...")

        while True:
            # 1. Extraer los juegos visibles actualmente en el DOM de la página
            extracted = page.evaluate("""() => {
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
                            title: d.gameTitle,
                            url: d.gameUrl,
                            size: size,
                            date: date
                        });
                    }
                });

                return results;
            }""")

            # Guardar juegos en nuestro mapa (evita duplicados automáticamente)
            new_added = 0
            for item in extracted:
                if item["url"] not in all_games_map:
                    all_games_map[item["url"]] = item
                    new_added += 1

            # 2. Limpiar el DOM eliminando los contenedores procesados para mantener la velocidad
            page.evaluate("""() => {
                const wraps = document.querySelectorAll('div[data-game-id]');
                wraps.forEach(w => w.remove());
            }""")

            # 3. Intentar hacer clic en 'Load More Games'
            clicked = page.evaluate("""() => {
                const btn = Array.from(document.querySelectorAll('button')).find(
                    b => b.getAttribute('wire:click') === 'loadMoreGames' || b.textContent.includes('Load More')
                );
                if (btn && !btn.disabled) {
                    btn.click();
                    return true;
                }
                return false;
            }""")

            if not clicked:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    log("[*] No se encontró el botón de carga o se alcanzaron todos los juegos.")
                    break
                time.sleep(1.0)
                continue

            consecutive_failures = 0
            clicks += 1

            if clicks % 10 == 0 or clicks == 1:
                log(f"[*] Clic #{clicks} realizado | Juegos acumulados hasta ahora: {len(all_games_map)}")

            # Breve pausa para dar tiempo a Livewire a recibir el nuevo bloque
            time.sleep(0.4)

        browser.close()

        total_games = len(all_games_map)
        if total_games == 0:
            log("[x] No se encontró ningún juego en la lista.")
            return 1

        log(f"[*] Total de {total_games} juegos extraídos con éxito. Generando JSON...")

        downloads_list: List[Dict[str, Any]] = []
        for item in all_games_map.values():
            downloads_list.append({
                "title": item["title"],
                "fileSize": item["size"],
                "uploadDate": parse_iso_date(item["date"]),
                "uris": [item["url"]]
            })

        output_data = {
            "name": "AnkerGames",
            "downloads": downloads_list,
        }

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        log(f"\n[✔] Completado: {len(downloads_list)} enlaces extraídos.")
        log(f"[✔] Guardado en: {OUTPUT_FILE.resolve()}")
        return 0


if __name__ == "__main__":
    sys.exit(main())