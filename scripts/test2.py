from playwright.sync_api import sync_playwright
import time
import os

def obtener_enlace_directo_bzzhr(url):
    with sync_playwright() as p:
        user_data_dir = os.path.join(os.getcwd(), "chrome_profile")
        
        print("[*] Iniciando entorno de navegación limpio y camuflado...")
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,  # Cambiar a True si no quieres ver la ventana del navegador
            args=["--disable-blink-features=AutomationControlled"], 
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        # Destruir ventanas emergentes de publicidad al vuelo
        context.on("page", lambda popup: popup.close())

        # --- ANTIDOTE PARA EVITAR LA DESCARGA REAL ---
        # Interceptamos el evento del navegador cuando la web dice "¡A descargar!" y lo cancelamos
        page.on("download", lambda download: download.cancel())

        enlace_encontrado = None

        def interceptar_peticion(request):
            nonlocal enlace_encontrado
            if "ts.bzzhr.to/d/" in request.url:
                enlace_encontrado = request.url

        page.on("request", interceptar_peticion)
        
        print(f"Navegando a Buzzheavier: {url}")
        page.goto(url, wait_until="load", referer="https://steamrip.com/")
        
        selector_css = "a.download-btn.gay-button"
        
        print("Esperando al botón de descarga...")
        try:
            page.wait_for_selector(selector_css, timeout=15000)
            boton = page.locator(selector_css)
            
            # --- CLIC 1 ---
            print("[Clic 1] Abriendo anuncio obligatorio...")
            boton.click()
            page.wait_for_timeout(1500)
            
            # --- CLIC 2 ---
            if not enlace_encontrado:
                print("[Clic 2] Ejecutando el segundo intento real de descarga...")
                # page.bring_to_front()
                boton.click()
                
                print("[*] Esperando la captura del enlace en la red...")
                page.wait_for_timeout(4000)

        except Exception as e:
            print(f"[x] Error durante el proceso: {e}")
        
        if enlace_encontrado:
            print(f"\n--- ENLACE DIRECTO OBTENIDO ---")
            print(enlace_encontrado)
            print(f"--------------------------------\n")
        else:
            print("[x] No se pudo capturar el enlace directo de descarga.")
        
        context.close()

if __name__ == "__main__":
    url_prueba = "https://bzzhr.to/estn7eg43xm4"
    obtener_enlace_directo_bzzhr(url_prueba)