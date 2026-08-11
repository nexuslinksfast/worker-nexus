from __future__ import annotations

import sys
import time
from typing import Optional
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)

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

def get_direct_download_url(game_url: str) -> Optional[str]:
    intermediate_url: Optional[str] = None
    real_cdn_url: Optional[str] = None

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--headless=new",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
            ]
        )

        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="es-ES",
            ignore_https_errors=True,
        )

        page = context.new_page()

        if HAS_STEALTH:
            stealth_sync(page)

        # Capturador 1: Para obtener la URL intermedia
        def intercept_request(request):
            nonlocal intermediate_url
            req_url = request.url
            if "/download/" in req_url and "dlproxy" not in req_url and req_url != page.url:
                if not intermediate_url:
                    intermediate_url = req_url

        page.on("request", intercept_request)

        try:
            log(f"[*] Accediendo a: {game_url}")
            page.goto(game_url, wait_until="domcontentloaded", timeout=45000)

            if not handle_cloudflare_challenge(page):
                log("    [❌] ERROR: Bloqueado por Cloudflare")
                return None

            # 1. Abrir Modal inicial
            download_modal_btn = "button:has-text('Download')"
            page.wait_for_selector(download_modal_btn, timeout=15000)
            page.click(download_modal_btn, force=True)

            # 2. Esperar al botón dentro del modal
            modal_download_btn = "a.download-button, button.download-button"
            page.wait_for_selector(modal_download_btn, state="attached", timeout=12000)

            # 3. Hacer clic para obtener la URL intermedia de la cuenta atrás
            page.evaluate("""() => {
                const btn = document.querySelector('a.download-button, button.download-button');
                if (btn) btn.click();
            }""")

            waited = 0
            while waited < 8000 and not intermediate_url:
                page.wait_for_timeout(500)
                waited += 500

            if not intermediate_url:
                log("    [❌] No se pudo obtener la URL intermedia.")
                return None

            log(f"    [🔗] Página de descarga obtenida: {intermediate_url[:65]}...")
            log("    [⏳] Entrando a la página de descarga y esperando los 5 segundos de cuenta atrás...")

            # 4. Escuchar peticiones hacia dlproxy o archivos directos
            def intercept_cdn_request(request):
                nonlocal real_cdn_url
                req_url = request.url
                if "dlproxy" in req_url or ".zip" in req_url or ".rar" in req_url or "tunnel" in req_url:
                    real_cdn_url = req_url

            page.on("request", intercept_cdn_request)

            # 5. Navegar a la página intermedia y esperar a que pase el timer
            page.goto(intermediate_url, wait_until="domcontentloaded", timeout=30000)

            # Esperar 8 segundos para asegurar que pasen los 5s de la cuenta atrás de la web y el JS haga el click/fetch
            waited_cdn = 0
            while waited_cdn < 10000 and not real_cdn_url:
                page.wait_for_timeout(500)
                waited_cdn += 500

            return real_cdn_url

        except PlaywrightTimeoutError:
            log("    [❌] ERROR: Timeout procesando la descarga.")
        except Exception as e:
            log(f"    [❌] ERROR: {e}")
        finally:
            browser.close()

    return real_cdn_url


if __name__ == "__main__":
    target_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://ankergames.net/game/iron-nest-heavy-turret-simulator"
    )

    download_link = get_direct_download_url(target_url)

    if download_link:
        print("\n================ ENLACE DIRECTO REAL ================")
        print(download_link)
        print("=====================================================")
    else:
        log("\n[x] No se pudo obtener el enlace directo real.")
        sys.exit(1)