import json
import os
import platform
import sys
import time
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================================================
# CONFIGURACIÓN
# ============================================================
URL = "https://hydralinks.cloud/sources/gog.json"
OUTPUT_FILE = "public/freegog.json"

def get_driver():
    import undetected_chromedriver as uc
    import platform
    import os
    import re

    # Función interna auxiliar para generar un objeto de opciones limpio cada vez
    def create_clean_options():
        opts = uc.ChromeOptions()
        if platform.system() != "Windows" or os.environ.get("HEADLESS") == "1":
            opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        return opts

    # INTENTO 1: Intentamos inicializar de forma estándar y automática
    try:
        options = create_clean_options()
        return uc.Chrome(options=options)
    except Exception as e:
        error_msg = str(e)
        
        # Si el error es debido a discrepancia de versiones, extraemos el número dinámicamente
        if "Current browser version is" in error_msg:
            match = re.search(r"Current browser version is ([\d]+)\.", error_msg)
            if match:
                detected_version = int(match.group(1))
                print(f"[*] Conflicto de versión mitigado. Forzando Chrome v{detected_version}...")
                
                # INTENTO 2: Generamos opciones frescas para evitar el RuntimeError de reutilización
                retry_options = create_clean_options()
                return uc.Chrome(options=retry_options, version_main=detected_version)
                
        # Si el error inicial era por otra causa ajena, lo propagamos
        raise e


def extract_json(body_text):
    try:
        return json.loads(body_text)
    except json.JSONDecodeError:
        pass
    
    try:
        soup = BeautifulSoup(body_text, "html.parser")
        # El JSON plano a veces se renderiza en un <pre> o directamente en el body
        pre_tag = soup.find("pre")
        if pre_tag:
            return json.loads(pre_tag.get_text())
        
        body_tag = soup.find("body")
        if body_tag:
            return json.loads(body_tag.get_text())
    except Exception:
        pass

    raise ValueError("No se encontró una estructura JSON válida en la respuesta del navegador.")


def count_entries(data):
    if isinstance(data, dict):
        for key in ("downloads", "games", "sources"):
            if key in data and hasattr(data[key], "__len__"):
                return len(data[key])
        return len(data)
    return len(data)


def normalize_output(data):
    if isinstance(data, dict) and isinstance(data.get("downloads"), list):
        return {"name": "FreeGOG", "downloads": data["downloads"]}

    if isinstance(data, dict):
        for key in ("games", "sources", "items", "data"):
            if isinstance(data.get(key), list):
                return {"name": "FreeGOG", "downloads": data[key]}

    if isinstance(data, list):
        return {"name": "FreeGOG", "downloads": data}

    raise ValueError("El JSON descargado no tiene una estructura reconocible para normalizarlo.")


def download():
    print("=" * 58)
    print("  Descargador freegog.json via Undetected Selenium")
    print("=" * 58)
    print()

    print("[*] Iniciando navegador indetectable...")
    driver = get_driver()
    body_content = ""

    try:
        print(f"[*] Solicitando: {URL}")
        driver.get(URL)
        
        print("[*] Saltando Cloudflare dinámicamente...")
        time.sleep(10) # Damos unos segundos para que cargue e intercepte el reto solo
        
        # Esperamos a que el contenido real de la página (el JSON) aparezca
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        body_content = driver.page_source
        
    except Exception as error:
        print(f"[x] El navegador falló al procesar la página: {error}")
        driver.quit()
        sys.exit(1)
    finally:
        driver.quit()

    # Procesamiento del JSON extraído
    try:
        data = extract_json(body_content)
    except Exception as error:
        print(f"[x] Error al extraer el JSON del navegador: {error}")
        sys.exit(1)

    try:
        normalized = normalize_output(data)
    except Exception as error:
        print(f"[x] No se pudo normalizar el JSON: {error}")
        sys.exit(1)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file_handle:
        json.dump(normalized, file_handle, ensure_ascii=False, indent=2)

    print(f"[ok] JSON guardado exitosamente en: {OUTPUT_FILE}")
    print(f"[ok] Entradas encontradas: {count_entries(normalized)}")


if __name__ == "__main__":
    download()