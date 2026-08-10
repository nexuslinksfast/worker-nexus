import json
import os
import platform
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================================================
# CONFIGURACIÓN
# ============================================================
TARGET_URL = "https://www.instant-gaming.com/en/"
OUTPUT_FILE = os.path.join("public", "instant-gaming-deals.json")
SELENIUM_URL = os.environ.get("SELENIUM_URL", "http://localhost:4444/wd/hub")

def get_driver():
    options = Options()
    # Forzar modo headless en entornos que no sean Windows (servidores/CI)
    if platform.system() != "Windows" or os.environ.get("HEADLESS") == "1":
        options.add_argument("--headless=new")
    
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    if os.environ.get("SELENIUM_URL"):
        try:
            return webdriver.Remote(command_executor=SELENIUM_URL, options=options)
        except Exception:
            pass

    return webdriver.Chrome(options=options)

def clean_val(val):
    if not val: return ""
    if hasattr(val, 'get_text'):
        val = val.get_text()
    return str(val).strip().replace('\xa0', ' ')

# ============================================================
# PARSERS
# ============================================================

def parse_standard_item(article):
    try:
        title = clean_val(article.find("span", class_="title"))
        price = clean_val(article.find("div", class_="price"))
        discount = clean_val(article.find("div", class_="discount"))
        link_tag = article.find("a", class_="cover")
        url = link_tag["href"].strip() if link_tag else ""
        img_tag = article.find("img", class_="picture")
        image = (img_tag.get("data-src") or img_tag.get("src") or "").strip()
        date_tag = article.find("div", class_="date")
        release = clean_val(date_tag) if date_tag else None

        return {"title": title, "price": price, "discount": discount, "image": image, "url": url, "release": release}
    except: return None

def parse_hero_item(hero_div):
    try:
        title = clean_val(hero_div.find("span", class_="banner-title"))
        price = clean_val(hero_div.find("span", class_="price"))
        discount = clean_val(hero_div.find("span", class_="discount"))
        parent = hero_div.find_parent()
        link_tag = parent.find("a", class_="full-link") if parent else None
        url = link_tag["href"].strip() if link_tag else ""
        img_tag = parent.find("img") if parent else None
        image = (img_tag.get("src") or img_tag.get("data-src") or "").strip()
        return {"title": title, "price": price, "discount": discount, "image": image, "url": url}
    except: return None

def parse_review_item(article):
    try:
        # 1. Texto de la reseña
        text_div = article.find("div", class_="text-content")
        review_text = text_div.get_text(separator="\n").strip() if text_div else ""
        
        # 2. Enlace del juego y Nombre (está en el <a> con clase "cover")
        link_tag = article.find("a", class_="cover")
        game_url = link_tag["href"].strip() if link_tag else ""
        game_name = link_tag["title"].replace("reviews ", "").strip() if link_tag and link_tag.has_attr("title") else ""
        
        # 3. Imagen del juego (dentro del picture)
        img_tag = article.find("img", class_="picture")
        game_image = ""
        if img_tag:
            # Priorizamos data-src por el lazyload, si no, src
            game_image = (img_tag.get("data-src") or img_tag.get("src") or "").strip()
        
        # 4. Info de usuario
        user_img = article.find("img", class_="ig-avatar")
        username = user_img.get("alt", "Gamer") if user_img else "Gamer"
        user_avatar = (user_img.get("data-src") or user_img.get("src") or "").strip() if user_img else ""
        
        # 5. Sentimiento (Like/Dislike)
        sentiment = "like" if article.find("div", class_="icon-like") else "dislike"

        return {
            "game": game_name,
            "game_image": game_image,
            "game_url": game_url,
            "user": username,
            "avatar": user_avatar,
            "sentiment": sentiment,
            "content": review_text
        }
    except Exception as e:
        print(f"Error parseando review: {e}")
        return None

def parse_weekly_deal(article):
    try:
        title = clean_val(article.find("span", class_="title"))
        discount = clean_val(article.find("div", class_="discount"))
        retail = clean_val(article.find("span", class_="retail"))
        old_price = clean_val(article.find("span", class_="old"))
        final_price = clean_val(article.find("span", class_="final"))
        timer = clean_val(article.find("div", class_="details"))
        link_tag = article.find("a", class_="cover")
        url = link_tag["href"].strip() if link_tag else ""
        img_tag = article.find("img", class_="picture")
        image = (img_tag.get("data-src") or img_tag.get("src") or "").strip()

        return {"title": title, "discount": discount, "retail_price": retail, "old_price": old_price, "final_price": final_price, "time_left": timer, "image": image, "url": url}
    except: return None

# ============================================================
# MAIN
# ============================================================

def main():
    print(f"[*] Iniciando el asalto a Instant Gaming (EN)...")
    driver = get_driver()
    
    try:
        # Entramos a la URL base
        driver.get(TARGET_URL)
        time.sleep(2) # Un pequeño respiro para que cargue el dominio antes de meter cookies
        
        # --- FORZAR CATÁLOGO ESPAÑA + IDIOMA INGLÉS + MONEDA DÓLAR ---
        try:
            # Borramos cookies previas por si acaso
            driver.delete_all_cookies()
            
            # Inyectamos la combinación exacta de tu captura de pantalla
            driver.add_cookie({"name": "ig_country", "value": "ES"})   # Catálogo/Región: Spain
            driver.add_cookie({"name": "ig_lang", "value": "en"})      # Idioma: English
            driver.add_cookie({"name": "ig_currency", "value": "USD"})  # Moneda: USD
            
            # Refrescamos para que el servidor procese nuestras cookies
            driver.refresh() 
            print("[*] Cookies de configuración (ES + EN + USD) inyectadas con éxito.")
        except Exception as e:
            print(f"[!] No se pudieron inyectar las cookies de configuración: {e}")

        # Continuamos con el comportamiento normal del scraper...
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "products-trending")))
        
        scroll_steps = [1500, 3000, 4500, 5500]
        for step in scroll_steps:
            driver.execute_script(f"window.scrollTo(0, {step});")
            time.sleep(1.2)
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        data_final = {
            "last_update": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "hero": [], "trending": [], "preorders": [], "bestsellers": [], "reviews": [], "weekly_deals": []
        }

        # 1. HERO (Revisado)
        hero_section = soup.find("section", class_="highlights-container")
        if hero_section:
            item = parse_hero_item(hero_section)
            if item: data_final["hero"].append(item)

        for hc in soup.find_all("div", class_="content"):
            if hc.find("span", class_="banner-title"):
                item = parse_hero_item(hc)
                if item and item not in data_final["hero"]: 
                    data_final["hero"].append(item)

        # 2. TRENDING
        section_t = soup.find("section", class_="products-trending")
        if section_t:
            for art in section_t.find_all("article", class_="item"):
                game = parse_standard_item(art)
                if game: data_final["trending"].append(game)

        # 3. PREORDERS
        section_p = soup.find("section", class_="preorders-container")
        if section_p:
            for art in section_p.find_all("article", class_="item"):
                game = parse_standard_item(art)
                if game: data_final["preorders"].append(game)

        # 4. BESTSELLERS
        section_b = soup.find("section", class_="bestsellers-container")
        if section_b:
            for art in section_b.find_all("article", class_="item"):
                game = parse_standard_item(art)
                if game: data_final["bestsellers"].append(game)

        # 5. REVIEWS
        section_r = soup.find("section", class_="reviews-panel")
        if section_r:
            for art in section_r.find_all("article", class_="review"):
                rev = parse_review_item(art)
                if rev: data_final["reviews"].append(rev)

        # 6. WEEKLY DEALS
        section_w = soup.find("section", id="promotions-home-block")
        if section_w:
            for art in section_w.find_all("article", class_="item"):
                deal = parse_weekly_deal(art)
                if deal: data_final["weekly_deals"].append(deal)

        # Guardado del JSON
        os.makedirs("public", exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data_final, f, indent=2, ensure_ascii=False)
        
        print(f"--- Resumen de Extracción ---")
        for key, value in data_final.items():
            if isinstance(value, list):
                print(f"{key.capitalize():<15}: {len(value)} items")
        print(f"-----------------------------")
        print(f"[*] Datos guardados en {OUTPUT_FILE}")

    except Exception as e:
        print(f"[!] Error crítico: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
