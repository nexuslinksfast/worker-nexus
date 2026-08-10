from playwright.sync_api import sync_playwright
import time

def obtener_enlace_directo(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Variable para guardar el link cuando lo encontremos
        enlace_encontrado = None

        # Definimos una función que "escucha" todas las peticiones de red
        def interceptar_peticion(request):
            nonlocal enlace_encontrado
            # Filtramos por el dominio que viste en DevTools (ej: megadb.xyz)
            if "megadb.xyz" in request.url:
                enlace_encontrado = request.url

        # Activamos el listener antes de navegar
        page.on("request", interceptar_peticion)
        
        print(f"Navegando a: {url}")
        page.goto(url)
        
        # Esperar a que el botón aparezca
        print("Esperando contador...")
        page.wait_for_selector("#downloadbtn")
        
        # Clic simple, sin esperar navegación
        print("Clic realizado. Escuchando red...")
        page.click("#downloadbtn")
        
        # Esperamos unos segundos a que la petición de descarga se dispare
        time.sleep(3) 
        
        if enlace_encontrado:
            print(f"\n--- ENLACE OBTENIDO ---")
            print(enlace_encontrado)
            print(f"-----------------------\n")
        else:
            print("No se pudo capturar el enlace.")
        
        browser.close()

if __name__ == "__main__":
    url = "https://megadb.net/z4hr8kfphjqt"
    obtener_enlace_directo(url)